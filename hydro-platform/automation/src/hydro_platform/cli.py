from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from hydro_platform.card_draft import generate_subject_card_draft
from hydro_platform.card_validation import ValidationAssets, validate_subject_card_file
from hydro_platform.card_generators import build_card_generator_adapter
from hydro_platform.card_generation import (
    CardGenerationError,
    generate_evidence_card,
    generate_evidence_card_trial,
)
from hydro_platform.config import ConfigError, load_config
from hydro_platform.draft_export import export_evidence_draft
from hydro_platform.evidence_packages import EvidencePackageError, sync_evidence_packages
from hydro_platform.evidence_templates import (
    EvidenceTemplateError,
    validate_evidence_templates,
)
from hydro_platform.pdf_delivery import PdfDeliveryError, prepare_pdf_delivery
from hydro_platform.pdf_direct_trial import PdfDirectTrialError, run_pdf_direct_trial
from hydro_platform.pdf_gate import PdfGateError, evaluate_pdf_gate
from hydro_platform.failure_records import save_failure_record
from hydro_platform.progress import ConsoleProgress
from hydro_platform.pipeline import run_once
from hydro_platform.themes import run_themes
from hydro_platform.doctor import doctor
from hydro_platform.deployment import bootstrap
from hydro_platform.native_deployment import bootstrap_native
from hydro_platform.workstation_setup import setup_workstation
from hydro_platform.windows_schedule import manage_schedule
from hydro_platform.scheduled import scheduled_tick
from hydro_platform.runtime_recovery import recover_runtime
from hydro_platform.activity import sync_activity
from hydro_platform.daily_report import daily_report
from hydro_platform.snapshot import SnapshotError, scan_group
from hydro_platform.tasks import TaskStoreError, list_tasks, sync_tasks
from hydro_platform.zotero import ZoteroApiError, discover_groups, preflight


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "config.json"


def _default_config_path() -> str:
    return os.environ.get("HYDRO_PLATFORM_CONFIG", str(DEFAULT_CONFIG_PATH))


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hydro-platform",
        description="水利科研知识平台无人值守自动化",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("discover-groups", "列出本机 Zotero 当前可见的群组库"),
        ("preflight", "检查目标 Zotero 群组库能否被后台读取"),
        ("doctor", "集中检查配置、依赖、登录及 Zotero；不调用模型、不安装或修复"),
        ("bootstrap", "预览项目依赖安装计划；加 --install 创建独立 Python 环境，不改全局环境"),
        ("bootstrap-native", "预览项目Poppler安装计划；加 --install 按哈希安装，不改系统PATH"),
        ("setup", "统一安装/检查/恢复入口；默认只读计划，--apply才安装依赖、恢复状态及配置的每日计划"),
        ("schedule-plan", "预览 Windows 计划任务定义，不注册或运行"),
        ("schedule-status", "检查 Windows 计划任务定义、下一次启动和补跑状态"),
        ("schedule-install", "按总配置安装/更新本项目 Windows 计划任务，不覆盖其他任务"),
        ("schedule-remove", "移除本项目 Windows 计划任务，保留知识和运行记录"),
        ("schedule-tick", "执行一次每日到期/补跑检查，到期才进入原流水线"),
        ("recover", "全量对账并恢复本地任务和扫描基线；不调用模型、不覆盖共享知识"),
        ("activity-sync", "只读扫描共享库并记录关键贡献；首次建立基线，不调用模型"),
        ("daily-report", "从现有任务和事件生成老师每日摘要；不扫描 Zotero、不调用模型"),
        ("scan", "建立基线或检测目标群组中的文献变化"),
        ("pdf-gate", "检查一个父条目的 PDF 全文是否可进入后续处理"),
        ("pdf-delivery", "复核并交付一个任务对应的 Zotero 原始 PDF"),
        ("tasks-sync", "根据 Zotero 和 PDF 门禁同步本地任务清单"),
        ("tasks-list", "查看本地任务清单，不访问 Zotero"),
        ("packages-sync", "为已通过 PDF 门禁的任务创建证据包骨架"),
        ("evidence-templates-validate", "校验证据卡模板目录、来源和版本完整性"),
        ("generator-preflight", "检查 Codex CLI 和 ChatGPT 账号登录状态"),
        ("generator-smoke-test", "执行一次无论文、只读的 Codex 最小模型调用"),
        ("evidence-generate", "读取一篇 Zotero PDF 并生成首张粗证据卡"),
        ("evidence-validate", "离线校验主体卡草稿并保存记录，不调用模型、不正式发布"),
        ("evidence-draft-export", "离线导出已完成的制卡草稿为 Markdown 预览，不调用模型或修改正式卡"),
        ("run-once", "自动检查共享库并串行生成待处理证据卡；不安装调度、不推送 Git"),
        ("themes-run", "粗卡生成候选主题，逐篇定向精读并回填修订；自动续跑、不转正式主题"),
        ("pdf-direct-read-trial", "仅验证 Codex 自主读取本地 PDF 路径，不生成卡片、不使用 PDF MCP"),
        (
            "evidence-generate-trial",
            "按配置执行制卡试运行（当前单 Agent），不修改正式卡片和任务",
        ),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument(
            "--config",
            default=None if name == "evidence-validate" else _default_config_path(),
            help=("可选总配置；校验默认直接使用随仓库分发的资产" if name == "evidence-validate"
                  else "总配置文件路径；默认读取项目 config/config.json"),
        )
        command.add_argument("--json", action="store_true", help="输出机器可读取 JSON")
        if not name.startswith("schedule-") and name not in {"setup", "bootstrap", "bootstrap-native", "generator-preflight", "generator-smoke-test", "evidence-draft-export", "evidence-validate"}:
            command.add_argument("--base-url", help="覆盖本机 Zotero API 地址")
            command.add_argument("--timeout", type=float, help="请求超时秒数")
        if name in {
            "doctor",
            "recover",
            "activity-sync",
            "daily-report",
            "preflight",
            "scan",
            "pdf-gate",
            "pdf-delivery",
            "tasks-sync",
            "tasks-list",
            "packages-sync",
            "pdf-direct-read-trial",
            "evidence-generate",
            "evidence-generate-trial",
            "run-once",
            "themes-run",
        }:
            command.add_argument("--group-id", help="覆盖目标 Zotero 群组 ID")
        if name == "scan":
            command.add_argument(
                "--state",
                help="覆盖总配置中的本地快照路径",
            )
        if name == "evidence-validate":
            command.add_argument("--assets-root", help="选择另一份 hydro-platform 资产根；与 --config 互斥")
            command.add_argument("--report-dir", default=os.environ.get("HYDRO_PLATFORM_VALIDATION_REPORT_DIR"),
                                 help="校验记录根；默认草稿旁 validations/，支持环境变量 HYDRO_PLATFORM_VALIDATION_REPORT_DIR")
            command.add_argument("--draft", required=True, help="#30 保存的 draft.json")
            command.add_argument("--paper-input", required=True, help="对应的 #29 READY JSON 文件")
        if name == "evidence-draft-export":
            command.add_argument("--draft", required=True, help="失败结果中的 diagnostic.draft_path；相对路径基于当前目录")
        if name in {"run-once", "themes-run"}:
            command.add_argument("--dry-run", action="store_true", help="只预览本地任务/粗卡输入和配置；不扫描 Zotero、不写文件、不调用模型")
        if name == "themes-run":
            command.add_argument("--migrate-only", action="store_true", help="仅将已完成旧主题接入统一池；不调用模型、不重新精读")
        if name == "recover":
            command.add_argument("--dry-run", action="store_true", help="读取 Zotero 并预览对账；不写文件、不调用模型；预览不占用运行锁")
        if name in {"bootstrap", "bootstrap-native"}:
            command.add_argument("--install", action="store_true", help="安装到配置的项目独立环境；不覆盖未知环境、不修改总配置")
        if name == "setup":
            command.add_argument("--apply", action="store_true", help="执行项目安装、无模型对账、按配置恢复每日计划；不代登录或推Git")
        if name in {
            "pdf-gate",
            "pdf-delivery",
            "pdf-direct-read-trial",
            "evidence-generate-trial",
        }:
            command.add_argument(
                "--item-key",
                required=True,
                help="需要检查的 Zotero 父条目 Key",
            )
        if name == "evidence-generate":
            source = command.add_mutually_exclusive_group(required=True)
            source.add_argument("--item-key", help="旧证据包流程的 Zotero 父条目 Key")
            source.add_argument("--paper-input", help="#29 的单篇 READY JSON 文件，或 - 从 stdin 读取；仅生成待校验草稿")
            command.add_argument(
                "--retry-quality-failed",
                action="store_true",
                help="显式重试一个 QUALITY_FAILED 任务；默认不会自动重试",
            )
        if name == "pdf-direct-read-trial":
            command.add_argument("--preflight-only", action="store_true",
                                 help="仅检查 Windows 沙箱读 PDF 和渲染能力，不调用模型")
        if name in {"setup", "evidence-generate", "evidence-generate-trial", "pdf-direct-read-trial", "run-once", "themes-run"}:
            command.add_argument(
                "--no-progress", action="store_true",
                help="关闭 stderr 实时进度，仅保留最终结果",
            )

    return parser


def _render_human(result: dict[str, Any]) -> str:
    if result.get("operation") == "subject_card_validation":
        lines = ["主体卡代码校验：" + result["status"] + "（不代表科研结论正确或正式发布）"]
        lines += [f"- {item['code']} {item['path']}：{item['message']}"
                  for item in result.get("errors", []) + result.get("warnings", [])]
        if result.get("validation_path"):
            lines.append("校验记录：" + result["validation_path"])
        return "\n".join(lines)
    if result.get("operation") == "subject_card_draft":
        if not result.get("ok"):
            return f"主体卡草稿失败（{result.get('failed_stage', 'input')}）：{result['error']['message']}"
        return ("已生成待校验主体卡草稿；未通过内容门禁、未正式发布"
                f"\n- 正文：{result['card_path']}\n- 正文、机器字段与来源记录：{result['draft_path']}"
                f"\n- 精读产物根：{result['literature_root']}")
    if result.get("operation") == "setup":
        return "\n".join(["安装与恢复：" + result["status"]] +
            [f"- {row['name']}: {row['status']}" for row in result["steps"]] +
            [result.get("error", {}).get("message", result["note"])])
    if result.get("operation", "").startswith("schedule"):
        return (f"每日调度：{result.get('status')}\n"
                f"{result.get('error', {}).get('message', result.get('note', ''))}")
    if result.get("operation") == "bootstrap_native":
        return (f"项目PDF工具：{result.get('status')}\n目录：{result.get('tools_dir', '未确定')}\n"
                f"{result.get('error', {}).get('message', result.get('note', ''))}")
    if result.get("operation") == "bootstrap":
        return (f"项目依赖：{result.get('status')}\nPython：{result.get('python_executable', '未确定')}\n"
                f"{result.get('error', {}).get('message', result['note'])}")
    if result.get("ok") and result.get("operation") in {"activity_sync", "daily_report"}:
        return (f"完成：{result['operation']}；模型调用0\n"
                f"{result.get('report_path') or result.get('ledger_path')}\n"
                f"{result.get('note', '')}")
    if result.get("operation") == "doctor":
        return "\n".join(["环境检查通过" if result["ok"] else "环境检查未全部通过"] +
                         [f"- {row['name']}: {row['status']}" for row in result["checks"]] + [result["note"]])
    if result.get("operation") == "recover":
        return (f"本地状态对账：{result.get('status')}\n任务统计：{result.get('counts', {})}\n"
                f"模型调用：0；共享知识未修改\n{result.get('error', {}).get('message', result.get('note', ''))}")
    if result.get("operation") == "themes_run":
        return (f"主题流程：{result['status']}"
                f"\n- 粗卡：{result.get('source_count', 0)}；候选：{result['candidate_count']}；已回填：{result['refined_count']}"
                f"\n- 本轮模型调用：{result['model_call_count']}；复用步骤：{result['reused_step_count']}"
                f"\n- 统一主题入口：{result.get('index_path', '尚未创建')}"
                "\n- 修订结果仍为候选，不会自动成为正式主题"
                + (f"\n- 错误：{result['error']['message']}" if result.get("error") else ""))
    if result.get("operation") == "run_once":
        if result.get("dry_run"):
            cap = result['limits']['max_items_per_run']
            return ("本地任务预览（未扫描 Zotero、未写入、未调用模型）"
                    f"\n- 已记录任务：{len(result['tasks'])}"
                    + (f"\n- 每轮最多尝试：{cap} 篇" if cap is not None else "\n- 处理范围：本轮扫描到的全部可制卡论文"))
        counts = result["counts"]
        return (f"统一运行：{result['status']}"
                f"\n- 新发现：{result['new_discovered_count']}；新生成：{counts['completed']}；恢复：{counts['recovered']}"
                f"\n- 跳过：{counts['skipped']}；等待：{counts['waiting']}；延后：{counts['deferred']}"
                f"\n- 阻塞：{counts['blocked']}；失败：{counts['failed']}"
                f"\n- 摘要：{result.get('report_path', '未保存')}"
                + (f"\n- 主题阶段：{result['theme_pipeline']['status']}"
                   + (f"\n- 统一主题入口：{result['theme_pipeline']['index_path']}" if result['theme_pipeline'].get('index_path') else "")
                   if result.get("theme_pipeline") else "")
                + (f"\n- 错误：{result['error']['message']}" if result.get("error") else ""))
    if result.get("ok"):
        if result.get("operation") == "evidence_draft_export":
            return ("已从草稿导出 Markdown 预览；未调用模型、未修改正式卡或任务"
                    f"\n- 卡片：{result['card_path']}"
                    f"\n- 正文检查：{result['structure_validation']['status']}（不作为保存门槛）"
                    "\n- 仅预览，不是重新完成的生产验收")
        if result.get("operation") == "pdf_direct_read_trial":
            if result.get("preflight_only"):
                return "本机沙箱预检通过：PDF 可读、文字可提取、页面可渲染；未调用模型"
            return (
                "路径直读实验：报告结构通过，模型声明阅读完成；不是独立质量验收"
                f"\n- 报告：{result['model_report_path']}"
                "\n- 未生成或修改正式证据卡，不能作为生产质量验收"
            )
        if result.get("operation") == "evidence_generate_trial":
            return (
                "通过：粗证据卡试运行已保存，正式证据包和任务未修改"
                f"\n- 父条目：{result['parent_key']}"
                f"\n- 质量状态：{result['quality_status']}"
                f"\n- 模板：{result['template_id']}"
                f"\n- 试运行目录：{result['trial_path']}"
            )
        if result.get("operation") == "evidence_generate":
            if result.get("action") == "SKIPPED_EXISTING_CARD":
                return (
                    "跳过：证据包已经存在非占位卡，未调用模型、未覆盖文件"
                    f"\n- 父条目：{result['parent_key']}"
                    f"\n- 当前状态：{result.get('card_status') or '未知'}"
                    f"\n- 卡片：{result['card_path']}"
                )
            return (
                "通过：粗证据卡已生成并写入"
                f"\n- 父条目：{result['parent_key']}"
                f"\n- 模板：{result['template_id']} {result['template_version']}"
                f"\n- 分类置信度：{result['classification_confidence']}"
                f"\n- 任务状态：{result['task_state']}"
                f"\n- 卡片：{result['card_path']}"
            )
        if result.get("component") == "evidence_templates":
            return (
                "通过：证据卡模板目录完整"
                f"\n- 模板总数：{result['template_count']}"
                f"\n- 已启用：{result['enabled_count']}"
                f"\n- 目录版本：{result['catalog_version']}"
                f"\n- 来源提交：{result['source_commit']}"
                f"\n- 目录：{result['templates_dir']}"
            )
        if result.get("component") == "card_generator":
            if result.get("operation") == "smoke_test":
                usage = result.get("usage") or {}
                return (
                    "通过：Codex 最小模型调用成功"
                    f"\n- 适配器：{result['adapter']}"
                    f"\n- CLI 版本：{result['cli_version']}"
                    f"\n- 模型来源：{result['model_source']}"
                    "\n- 推理强度："
                    f"{result.get('configured_reasoning_effort') or '模型默认'}"
                    f"\n- 输出 token：{usage.get('output_tokens', '未知')}"
                    f"\n- 安全模式：{result['sandbox']} / ephemeral"
                )
            return (
                "通过：Codex CLI 制卡运行环境可用"
                f"\n- 适配器：{result['adapter']}"
                f"\n- CLI 版本：{result['cli_version']}"
                f"\n- 登录方式：{result['detected_auth_mode']}"
                f"\n- 可执行程序：{result['resolved_executable']}"
            )
        if "delivery_status" in result:
            return (
                "通过：Zotero 原始 PDF 已复核，可以交给制卡器"
                f"\n- 父条目：{result['parent_key']}"
                f"\n- 附件：{result['attachment_key']}"
                f"\n- PDF：{result['pdf_path']}"
                f"\n- SHA-256：{result['pdf_sha256']}"
                f"\n- 证据包：{result['evidence_package_path']}"
            )
        if "package_count" in result:
            return (
                "通过：证据包骨架已同步"
                f"\n- 可处理任务：{result['eligible_task_count']}"
                f"\n- 新建：{result['created_count']}"
                f"\n- 保持不变：{result['unchanged_count']}"
                f"\n- 目录：{result['evidence_packs_path']}"
            )
        if "task_count" in result:
            states = ", ".join(
                f"{name}={count}" for name, count in result.get("state_counts", {}).items()
            ) or "无任务"
            return (
                "通过：任务清单已读取"
                f"\n- 任务数：{result['task_count']}"
                f"\n- 状态变化：{result.get('changed_count', 0)}"
                f"\n- 状态分布：{states}"
                f"\n- 文件：{result['state_path']}"
            )
        if "gate_status" in result:
            pdf = result.get("pdf") or {}
            return (
                f"PDF 门禁：{result['gate_status']} [{result['reason_code']}]"
                f"\n- 父条目：{result['parent_key']}"
                f"\n- PDF 数量：{result['pdf_attachment_count']}"
                f"\n- 附件：{pdf.get('attachment_key') or '无'}"
                f"\n- 说明：{result['message']}"
            )
        if "mode" in result:
            return (
                f"通过：Zotero 扫描完成（{result['mode']}）"
                f"\n- 父条目：{result['counts']['parents']}"
                f"\n- PDF 附件：{result['counts']['pdf_attachments']}"
                f"\n- 本次变化：{result['change_count']}"
            )
        if "groups" in result:
            groups = result["groups"]
            if not groups:
                return "通过：Zotero 可访问，但当前没有可见群组。"
            lines = ["通过：发现以下 Zotero 群组："]
            lines.extend(f"- {group['group_id']}: {group['name'] or '(未命名)'}" for group in groups)
            return "\n".join(lines)
        return (
            "通过：目标 Zotero 群组可读取"
            f"\n- 群组：{result.get('group_name') or result.get('group_id')}"
            f"\n- 条目数：{result.get('item_count') if result.get('item_count') is not None else '未知'}"
        )

    error = result.get("error", {})
    return f"失败 [{error.get('code', 'UNKNOWN')}]: {error.get('message', '未知错误')}"


def _emit(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_render_human(result))


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdio()
    args = _parser().parse_args(argv)
    if args.command == "evidence-validate":
        try:
            if args.config and args.assets_root:
                raise ConfigError("--config 与 --assets-root 不能同时指定")
            assets = (ValidationAssets.from_config(load_config(args.config, require_group=False))
                      if args.config else ValidationAssets.from_root(args.assets_root))
            result = validate_subject_card_file(assets, args.draft, args.paper_input, report_dir=args.report_dir)
        except (ConfigError, OSError, ValueError) as exc:
            _emit({"schema_version": 1, "ok": False, "error": {
                "code": "CONFIG_ERROR", "message": str(exc)}}, args.json)
            return 2
        _emit(result, args.json)
        return 0 if result["ok"] else 3
    if getattr(args, "paper_input", None) and getattr(args, "retry_quality_failed", False):
        _emit({"schema_version": 1, "ok": False, "error": {
            "code": "CARD_DRAFT_RETRY_UNSUPPORTED", "message": "主体卡草稿为单次调用，不支持任务重试参数"}}, args.json)
        return 2
    try:
        app_config = load_config(
            args.config,
            base_url=getattr(args, "base_url", None),
            group_id=getattr(args, "group_id", None),
            timeout_seconds=getattr(args, "timeout", None),
            require_group=args.command
            in {
                "setup",
                "doctor",
                "recover",
                "activity-sync",
                "daily-report",
                "preflight",
                "scan",
                "pdf-gate",
                "pdf-delivery",
                "tasks-sync",
                "tasks-list",
                "packages-sync",
                "pdf-direct-read-trial",
                "evidence-generate",
                "evidence-generate-trial",
                "evidence-draft-export",
                "run-once",
                "themes-run",
                "schedule-plan", "schedule-status", "schedule-install", "schedule-remove", "schedule-tick",
            } and not getattr(args, "paper_input", None),
        )
    except ConfigError as exc:
        result = {
            "schema_version": 1,
            "ok": False,
            "error": {"code": "CONFIG_ERROR", "message": str(exc)},
        }
        _emit(result, args.json)
        return 2

    if args.command == "discover-groups":
        result = discover_groups(app_config.zotero)
    elif args.command == "preflight":
        result = preflight(app_config.zotero)
    elif args.command == "doctor":
        result = doctor(app_config)
    elif args.command == "bootstrap":
        result = bootstrap(app_config, install=args.install)
    elif args.command == "bootstrap-native":
        result = bootstrap_native(app_config, install=args.install)
    elif args.command == "setup":
        with ConsoleProgress(enabled=args.apply and app_config.card_generator.progress.enabled and not args.no_progress,
            heartbeat_interval_seconds=app_config.card_generator.progress.heartbeat_interval_seconds,
            label="安装进度", initial_activity="检查项目安装与恢复条件（不调用模型）") as progress:
            result = setup_workstation(app_config, apply=args.apply, progress=progress)
            if args.apply:
                progress.finish(result)
        if result.get("status") == "CANCELLED":
            _emit(result, args.json)
            return 130
    elif args.command.startswith("schedule-"):
        result = scheduled_tick(app_config) if args.command == "schedule-tick" else manage_schedule(app_config, args.command.split("-", 1)[1])
    elif args.command == "recover":
        result = recover_runtime(app_config, dry_run=args.dry_run)
    elif args.command in {"activity-sync", "daily-report"}:
        try:
            result = (sync_activity if args.command == "activity-sync" else daily_report)(app_config)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
            result = {"schema_version": 1, "ok": False, "operation": args.command.replace("-", "_"),
                      "model_call_count": 0, "error": {"code": getattr(exc, "code", "REPORTING_FAILED"),
                      "message": "共享事件或日报处理失败；保留现有文件，不调用模型，请检查来源/路径或文件冲突"}}
    elif args.command == "scan":
        readiness = preflight(app_config.zotero)
        if not readiness["ok"]:
            result = readiness
        else:
            try:
                state_path = (
                    Path(args.state).expanduser().resolve()
                    if args.state
                    else app_config.paths.snapshot_file
                )
                result = scan_group(
                    app_config.zotero,
                    state_path,
                    page_size=app_config.scan.page_size,
                )
            except (SnapshotError, ZoteroApiError) as exc:
                result = {
                    "schema_version": 1,
                    "ok": False,
                    "error": {"code": exc.code, "message": str(exc)},
                }
    elif args.command == "pdf-gate":
        readiness = preflight(app_config.zotero)
        if not readiness["ok"]:
            result = readiness
        else:
            try:
                result = evaluate_pdf_gate(
                    app_config.zotero,
                    app_config.pdf_gate,
                    args.item_key,
                )
            except (PdfGateError, ZoteroApiError) as exc:
                result = {
                    "schema_version": 1,
                    "ok": False,
                    "error": {"code": exc.code, "message": str(exc)},
                }
    elif args.command == "pdf-delivery":
        readiness = preflight(app_config.zotero)
        if not readiness["ok"]:
            result = readiness
        else:
            try:
                result = prepare_pdf_delivery(
                    app_config.zotero,
                    app_config.pdf_gate,
                    app_config.tasks,
                    app_config.paths.tasks_file,
                    app_config.paths.lock_file,
                    app_config.paths.evidence_packs_dir,
                    args.item_key,
                ).as_result()
            except (
                PdfDeliveryError,
                EvidencePackageError,
                TaskStoreError,
                PdfGateError,
                ZoteroApiError,
            ) as exc:
                result = {
                    "schema_version": 1,
                    "ok": False,
                    "error": {"code": exc.code, "message": str(exc)},
                }
    elif args.command == "tasks-sync":
        readiness = preflight(app_config.zotero)
        if not readiness["ok"]:
            result = readiness
        else:
            try:
                result = sync_tasks(
                    app_config.zotero,
                    app_config.pdf_gate,
                    app_config.tasks,
                    app_config.paths.tasks_file,
                    app_config.paths.lock_file,
                    page_size=app_config.scan.page_size,
                )
            except (TaskStoreError, SnapshotError, PdfGateError, ZoteroApiError) as exc:
                result = {
                    "schema_version": 1,
                    "ok": False,
                    "error": {"code": exc.code, "message": str(exc)},
                }
    elif args.command == "tasks-list":
        try:
            result = list_tasks(
                app_config.zotero.group_id,
                app_config.paths.tasks_file,
            )
        except TaskStoreError as exc:
            result = {
                "schema_version": 1,
                "ok": False,
                "error": {"code": exc.code, "message": str(exc)},
            }
    elif args.command == "packages-sync":
        try:
            result = sync_evidence_packages(
                app_config.zotero.group_id,
                app_config.tasks,
                app_config.paths.tasks_file,
                app_config.paths.lock_file,
                app_config.paths.evidence_packs_dir,
            )
        except (EvidencePackageError, TaskStoreError) as exc:
            result = {
                "schema_version": 1,
                "ok": False,
                "error": {"code": exc.code, "message": str(exc)},
            }
    elif args.command == "evidence-templates-validate":
        try:
            result = validate_evidence_templates(
                app_config.paths.evidence_card_templates_dir,
                app_config.paths.evidence_card_template_catalog_file,
            )
        except EvidenceTemplateError as exc:
            result = {
                "schema_version": 1,
                "ok": False,
                "error": {"code": exc.code, "message": str(exc)},
            }
    elif args.command in {"run-once", "themes-run"}:
        try:
            operation = run_once if args.command == "run-once" else run_themes
            extra = {"migration_only": args.migrate_only} if args.command == "themes-run" else {}
            if args.dry_run:
                result = operation(app_config, dry_run=True, **extra)
            else:
                with ConsoleProgress(enabled=app_config.card_generator.progress.enabled and not args.no_progress,
                    heartbeat_interval_seconds=app_config.card_generator.progress.heartbeat_interval_seconds) as progress:
                    result = operation(app_config, progress=progress, **extra)
                    progress.finish(result)
        except (TaskStoreError, OSError, ValueError) as exc:
            result = {"schema_version": 1, "ok": False, "error": {
                "code": getattr(exc, "code", "PIPELINE_LOCAL_ERROR"), "message": "无法读取本地任务或运行配置"}}
        if result.get("status") == "CANCELLED":
            _emit(result, args.json)
            return 130
    elif args.command == "evidence-draft-export":
        try:
            result = export_evidence_draft(app_config, Path(args.draft))
        except (CardGenerationError, EvidencePackageError) as exc:
            error = {"code": exc.code, "message": str(exc)}
            if getattr(exc, "diagnostic", None):
                error["diagnostic"] = exc.diagnostic
            result = {"schema_version": 1, "ok": False, "error": error}
        except OSError:
            result = {"schema_version": 1, "ok": False, "error": {
                "code": "CARD_DRAFT_EXPORT_IO_ERROR", "message": "无法读取草稿或写入预览目录；原草稿和正式卡未修改"}}
    elif args.command == "generator-preflight":
        try:
            result = build_card_generator_adapter(
                app_config.card_generator
            ).preflight()
        except ValueError as exc:
            result = {
                "schema_version": 1,
                "ok": False,
                "error": {
                    "code": "CARD_GENERATOR_ADAPTER_NOT_REGISTERED",
                    "message": str(exc),
                },
            }
    elif args.command == "generator-smoke-test":
        try:
            result = build_card_generator_adapter(
                app_config.card_generator
            ).smoke_test()
        except ValueError as exc:
            result = {
                "schema_version": 1,
                "ok": False,
                "error": {
                    "code": "CARD_GENERATOR_ADAPTER_NOT_REGISTERED",
                    "message": str(exc),
                },
            }
    elif args.command == "evidence-generate" and args.paper_input:
        try:
            raw = sys.stdin.read() if args.paper_input == "-" else Path(args.paper_input).read_text(encoding="utf-8-sig")
            paper_input = json.loads(raw)
        except (OSError, ValueError):
            result = {"schema_version": 1, "operation": "subject_card_draft", "ok": False,
                      "status": "FAILED", "failed_stage": "input", "model_invoked": False,
                      "error": {"code": "CARD_DRAFT_INPUT_INVALID", "message": "无法读取单篇论文输入 JSON"}}
        else:
            progress_config = app_config.card_generator.progress
            with ConsoleProgress(enabled=progress_config.enabled and not args.no_progress,
                                 heartbeat_interval_seconds=progress_config.heartbeat_interval_seconds,
                                 initial_activity="检查单篇输入、PDF 和精读产物根") as progress:
                result = generate_subject_card_draft(app_config, paper_input, progress=progress)
                progress.finish(result)
    elif args.command in {"evidence-generate", "evidence-generate-trial", "pdf-direct-read-trial"}:
        progress_config = app_config.card_generator.progress
        with ConsoleProgress(
            enabled=progress_config.enabled and not args.no_progress,
            heartbeat_interval_seconds=progress_config.heartbeat_interval_seconds,
        ) as progress:
            try:
                readiness = preflight(app_config.zotero)
                if not readiness["ok"]:
                    result = readiness
                elif args.command == "pdf-direct-read-trial":
                    delivery = prepare_pdf_delivery(
                        app_config.zotero, app_config.pdf_gate, app_config.tasks,
                        app_config.paths.tasks_file, app_config.paths.lock_file,
                        app_config.paths.evidence_packs_dir, args.item_key,
                        allow_trial_states=True,
                    )
                    result = run_pdf_direct_trial(app_config, delivery, progress=progress,
                                                  preflight_only=args.preflight_only)
                else:
                    adapter = build_card_generator_adapter(
                        app_config.card_generator, progress=progress,
                    )
                    if args.command == "evidence-generate-trial":
                        result = generate_evidence_card_trial(
                            app_config.zotero,
                            app_config.pdf_gate,
                            app_config.tasks,
                            app_config.paths.tasks_file,
                            app_config.paths.lock_file,
                            app_config.paths.evidence_packs_dir,
                            app_config.paths.card_trials_dir,
                            app_config.paths.evidence_card_templates_dir,
                            app_config.paths.evidence_card_template_catalog_file,
                            app_config.paths.evidence_card_generation_prompt_file,
                            app_config.paths.card_generation_output_schema_file,
                            args.item_key,
                            adapter,
                        )
                    else:
                        result = generate_evidence_card(
                            app_config.zotero,
                            app_config.pdf_gate,
                            app_config.tasks,
                            app_config.paths.tasks_file,
                            app_config.paths.lock_file,
                            app_config.paths.evidence_packs_dir,
                            app_config.paths.evidence_card_templates_dir,
                            app_config.paths.evidence_card_template_catalog_file,
                            app_config.paths.evidence_card_generation_prompt_file,
                            app_config.paths.card_generation_output_schema_file,
                            args.item_key,
                            adapter,
                            retry_quality_failed=args.retry_quality_failed,
                        )
            except (
                CardGenerationError,
                PdfDirectTrialError,
                PdfDeliveryError,
                EvidencePackageError,
                EvidenceTemplateError,
                TaskStoreError,
                PdfGateError,
                ZoteroApiError,
            ) as exc:
                error = {"code": exc.code, "message": str(exc)}
                diagnostic = getattr(exc, "diagnostic", None)
                if isinstance(diagnostic, dict):
                    error["diagnostic"] = diagnostic
                result = {
                    "schema_version": 1,
                    "ok": False,
                    "error": error,
                }
            except OSError:
                result = {
                    "schema_version": 1, "ok": False,
                    "error": {"code": "LOCAL_IO_ERROR", "message": "本地文件或程序访问失败，请检查配置路径和读写权限"},
                }
            except ValueError as exc:
                result = {
                    "schema_version": 1,
                    "ok": False,
                    "error": {
                        "code": "CARD_GENERATOR_ADAPTER_NOT_REGISTERED",
                        "message": str(exc),
                    },
                }
            except KeyboardInterrupt:
                result = {
                    "schema_version": 1, "ok": False,
                    "error": {"code": "CANCELLED", "message": "用户中止了本次生成"},
                }
                progress.finish(result)
                _emit(result, args.json)
                return 130
            if not result.get("ok"):
                try:
                    diagnostic_path = save_failure_record(
                        app_config.paths.logs_dir, args.command, args.item_key, result,
                    )
                    result["diagnostic_log_path"] = str(diagnostic_path)
                    progress({"event": "phase", "message": f"脱敏失败记录已保存：{diagnostic_path}"})
                except OSError:
                    result["diagnostic_log_warning"] = "无法保存本地诊断记录，原始失败结果仍保留在本次 JSON 中"
            progress.finish(result)
    else:
        raise AssertionError(f"未处理的命令：{args.command}")
    _emit(result, args.json)
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
