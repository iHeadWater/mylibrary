from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from hydrolitagent.cards.application.card_workflow import (
    finalize_session_run,
    generate_markdown_card_draft,
    prepare_session_run,
)
from hydrolitagent.cards.card_draft import generate_subject_card_draft
from hydrolitagent.cards.card_validation import ValidationAssets, validate_subject_card_file
from hydrolitagent.cards.ai_config import (
    AIConfigError,
    apply_ai_selection,
    describe_ai,
    resolve_ai_config,
    subject_card_config,
)
from hydrolitagent.cards.card_generators import build_card_generator_adapter
from hydrolitagent.cards.card_generation import (
    CardGenerationError,
    generate_evidence_card,
)
from hydrolitagent.cards.composition import (
    build_doctor_report,
    build_markdown_pipeline,
    build_session_pipeline,
    build_theme_pipeline,
)
from hydrolitagent.cards.config import ConfigError, load_config, resolve_pipeline_mode
from hydrolitagent.cards.paper_input_config import load_paper_input_config
from hydrolitagent.cards.evidence_packages import EvidencePackageError, sync_evidence_packages
from hydrolitagent.cards.evidence_templates import (
    EvidenceTemplateError,
    validate_evidence_templates,
)
from hydrolitagent.cards.pdf_delivery import PdfDeliveryError, prepare_pdf_delivery
from hydrolitagent.cards.pdf_gate import PdfGateError, evaluate_pdf_gate
from hydrolitagent.cards.paper_input import (
    prepare_demo_paper,
    prepare_paper_batch,
    prepare_paper_input,
)
from hydrolitagent.cards.failure_records import save_failure_record
from hydrolitagent.cards.progress import ConsoleProgress
from hydrolitagent.cards.themes import run_themes
from hydrolitagent.cards.tasks import TaskStoreError
from hydrolitagent.cards.zotero import ZoteroApiError, preflight
from hydrolitagent.cards._paths import DEFAULT_CONFIG_PATH





def _default_config_path() -> str:
    return os.environ.get("HYDROLITAGENT_CARDS_CONFIG", str(DEFAULT_CONFIG_PATH))


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hydrolitagent cards",
        description="用你自己的 Zotero 文献生成文献卡与主题卡",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("paper-input", "按题名搜索候选，或按 item key 检查单篇 Zotero 论文输入"),
        ("evidence-generate", "读取一篇 Zotero PDF 并生成首张粗证据卡"),
        ("evidence-validate", "离线校验主体卡草稿并保存记录，不调用模型、不正式发布"),
        ("themes-run", "粗卡生成候选主题，逐篇定向精读并回填修订；自动续跑、不转正式主题"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument(
            "--config",
            default=None if name in {"evidence-validate", "evidence-generate", "paper-input"} else _default_config_path(),
            help=("可选总配置；校验默认直接使用随仓库分发的资产" if name == "evidence-validate"
                  else "总配置文件路径；默认读取项目 config/config.json"),
        )
        command.add_argument("--json", action="store_true", help="输出机器可读取 JSON")
        if name != "evidence-validate":
            command.add_argument("--base-url", help="覆盖本机 Zotero API 地址")
            command.add_argument("--timeout", type=float, help="请求超时秒数")
        if name in {"paper-input", "evidence-generate", "themes-run"}:
            command.add_argument("--group-id", help="覆盖目标 Zotero 群组 ID")
        if name == "evidence-validate":
            command.add_argument("--assets-root", help="选择另一份资产根（templates/prompts/schemas）；与 --config 互斥")
            command.add_argument("--report-dir", default=os.environ.get("HYDROLITAGENT_CARDS_VALIDATION_REPORT_DIR"),
                                 help="校验记录根；默认草稿旁 validations/，支持环境变量 HYDROLITAGENT_CARDS_VALIDATION_REPORT_DIR")
            command.add_argument("--draft", required=True, help="待校验的主体卡草稿 draft.json")
            command.add_argument("--paper-input", required=True, help="对应的单篇 READY JSON（输入记录）文件")
        if name == "paper-input":
            paper_source = command.add_mutually_exclusive_group(required=True)
            paper_source.add_argument(
                "--query",
                help="按题名、DOI 或关键词搜索候选；只返回候选，不自动选择",
            )
            paper_source.add_argument(
                "--item-key",
                action="append",
                help="已人工确认的 Zotero 父条目 Key",
            )
            paper_source.add_argument(
                "--demo",
                action="store_true",
                help="检查内置公开演示论文；本地缺失时返回 Connector 抓取链接",
            )
            command.add_argument(
                "--user-library",
                action="store_true",
                help="读取个人文库；默认读取配置的群组库",
            )
            command.add_argument(
                "--limit",
                type=int,
                default=10,
                help="搜索候选数，范围 1-50，默认 10",
            )
        if name == "themes-run":
            command.add_argument("--dry-run", action="store_true", help="只预览本地粗卡输入和配置；不扫描 Zotero、不写文件、不调用模型")
            command.add_argument("--migrate-only", action="store_true", help="仅将已完成旧主题接入统一池；不调用模型、不重新精读")
            # The same selection the single-paper path accepts: a theme run
            # makes model calls too, so it must not be stuck on the adapter
            # baked into config.json.
            command.add_argument("--ai-config", help="模型选择 TOML；默认 configs/ai.toml")
            command.add_argument(
                "--ai-provider", metavar="RUNNER",
                help="制卡运行器 id，例如 codex、claude、openai_compatible；可用值见 ai-config --json 的 runners",
            )
            command.add_argument("--ai-model", help="所选服务可用的模型名")
            command.add_argument("--ai-executable", help="本机 CLI 可执行文件名或绝对路径")
            command.add_argument("--ai-timeout", type=float)
        if name == "evidence-generate":
            command.add_argument("--ai-config", help="模型选择 TOML；默认 configs/ai.toml")
            # The registry, not argparse, owns the list of runner ids: a new
            # adapter must not require editing this parser.
            command.add_argument(
                "--ai-provider", metavar="RUNNER",
                help="制卡运行器 id，例如 codex、claude、openai_compatible；可用值见 ai-config --json 的 runners",
            )
            command.add_argument("--ai-model", help="所选服务可用的模型名")
            command.add_argument("--ai-executable", help="本机 CLI 可执行文件名或绝对路径")
            command.add_argument("--ai-timeout", type=float)
            command.add_argument("--output-root", help="本次产物根；不传则用默认解析（configs/paths.toml → outputs/）")
            # The default comes from CARD_PIPELINE (``markdown`` since stage 3b);
            # the hidden override exists for one release as a rollback.
            command.add_argument(
                "--pipeline", choices=["legacy", "markdown"], default=None,
                help=argparse.SUPPRESS,
            )
            source = command.add_mutually_exclusive_group(required=True)
            source.add_argument("--item-key", help="旧证据包流程的 Zotero 父条目 Key")
            source.add_argument("--paper-input", help="单篇 READY JSON（输入记录）文件，或 - 从 stdin 读取；仅生成待校验草稿")
            command.add_argument(
                "--retry-quality-failed",
                action="store_true",
                help="显式重试一个 QUALITY_FAILED 任务；默认不会自动重试",
            )
        if name in {"evidence-generate", "themes-run"}:
            command.add_argument(
                "--no-progress", action="store_true",
                help="关闭 stderr 实时进度，仅保留最终结果",
            )

    run = subparsers.add_parser(
        "run",
        help="两阶段制卡：准备材料目录，或收口 agent 写好的 response.json（不调用模型）",
    )
    run_sub = run.add_subparsers(dest="run_command", required=True)
    for run_name, run_help in (
        ("prepare", "把 paper.md、图资产、schema 与请求写入 --run-dir，不调用模型"),
        ("finalize", "读取 --run-dir/response.json，校验接地后生成待校验草稿"),
    ):
        run_command = run_sub.add_parser(run_name, help=run_help)
        run_command.add_argument(
            "--config",
            default=None,
            help="总配置文件路径；默认读取项目 config/config.json",
        )
        run_command.add_argument("--json", action="store_true", help="输出机器可读取 JSON")
        run_command.add_argument(
            "--paper-input",
            required=True,
            help="单篇 READY JSON（输入记录）文件，或 - 从 stdin 读取",
        )
        run_command.add_argument("--run-dir", required=True, help="两阶段协议的运行目录")
        run_command.add_argument(
            "--output-root",
            help="收口时草稿产物根；不传则用默认解析（configs/paths.toml → outputs/）",
        )

    doctor = subparsers.add_parser(
        "doctor",
        help="只读自查转换器、运行器与存储；不调用模型、不读取用户 PDF",
    )
    doctor.add_argument("--config", default=_default_config_path(), help="总配置文件路径")
    doctor.add_argument("--output-root", help="检查另一个产物根是否可写")
    doctor.add_argument(
        "--network", action="store_true", help="额外检查 Zotero Local API；默认不联网"
    )
    doctor.add_argument("--json", action="store_true", help="输出机器可读取 JSON")

    ai = subparsers.add_parser("ai-config", help="查看模型选择与精读产物根，不运行模型")
    ai.add_argument("--ai-config")
    ai.add_argument(
        "--ai-provider", metavar="RUNNER",
        help="制卡运行器 id；可用值见本命令输出的 runners",
    )
    ai.add_argument("--ai-model")
    ai.add_argument("--ai-executable")
    ai.add_argument("--ai-timeout", type=float)
    ai.add_argument("--output-root")
    ai.add_argument("--json", action="store_true")
    return parser


def _render_human(result: dict[str, Any]) -> str:
    if result.get("operation") == "doctor":
        status = "通过" if result.get("ok") else "存在问题"
        lines = [f"能力自查：{status}（未调用模型）", f"- 平台：{result.get('platform')}"]
        for check in result.get("checks", []):
            line = (
                f"- [{check['status']}] {check['name']}（{check['capability']}）："
                f"{check['detail']}"
            )
            if check.get("fix"):
                line += f"；修复：{check['fix']}"
            lines.append(line)
        return "\n".join(lines)
    if result.get("operation") == "session_prepare":
        if not result.get("ok"):
            error = result.get("error", {})
            return (
                f"两阶段准备失败（{result.get('failed_stage', 'input')}）"
                f"[{error.get('code', 'UNKNOWN')}]：{error.get('message', '未知错误')}"
            )
        run_dir = result["run_dir"]
        return "\n".join(
            [
                "已准备两阶段制卡目录；平台未调用模型",
                f"- 运行目录：{run_dir}",
                f"- 论文 Markdown：{run_dir}/paper.md（sha256 {result['markdown_sha256']}）",
                f"- 答案 schema：{result['schema_path']}",
                f"- 给 agent 的说明：{result['instructions_path']}",
                (
                    f"- 页数：{result['page_count']}；"
                    f"canary：{len(result.get('canaries', []))}；"
                    f"图：{len(result.get('figures', []))}"
                ),
                f"- 写完后运行：cards run finalize --run-dir {run_dir} --paper-input <输入 JSON>",
            ]
        )
    if result.get("operation") == "session_finalize":
        if not result.get("ok"):
            error = result.get("error", {})
            return (
                f"两阶段收口失败（{result.get('failed_stage', 'input')}）"
                f"[{error.get('code', 'UNKNOWN')}]：{error.get('message', '未知错误')}"
            )
        return "\n".join(
            [
                "已收口 response.json 并生成待校验主体卡草稿；未通过内容门禁、未正式发布",
                f"- 正文：{result['card_path']}",
                f"- 正文、机器字段与来源记录：{result['draft_path']}",
                f"- 精读产物根：{result['literature_root']}",
                f"- Markdown 接地校验：{result.get('reading_status') or '未知'}",
            ]
        )
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
        lines = [
            "已生成待校验主体卡草稿；未通过内容门禁、未正式发布",
            f"- 正文：{result['card_path']}",
            f"- 正文、机器字段与来源记录：{result['draft_path']}",
            f"- 精读产物根：{result['literature_root']}",
        ]
        if result.get("pipeline") == "markdown":
            lines.append(f"- Markdown 接地校验：{result.get('reading_status') or '未知'}")
        return "\n".join(lines)
    if result.get("operation") == "paper_input_batch":
        lines = [
            f"单篇输入批处理：{result['status']}",
            (
                f"- 总数：{result['total']}；就绪：{result['ready_count']}；"
                f"问题：{result['problem_count']}"
            ),
        ]
        for problem in result.get("problems", []):
            title = f" {problem['title']}" if problem.get("title") else ""
            lines.append(
                f"- 问题 {problem['item_key']}{title} "
                f"[{problem['reason_code']}]：{problem['message']}"
            )
            lines.extend(
                (
                    f"  - 候选 {candidate.get('attachment_key')}: "
                    f"{candidate.get('filename') or ''}"
                )
                for candidate in problem.get("candidates", [])
            )
        return "\n".join(lines)
    if result.get("operation") == "paper_input":
        if result.get("error"):
            error = result["error"]
            return (
                f"单篇输入失败 [{error.get('code', 'UNKNOWN')}]："
                f"{error.get('message', '未知错误')}"
            )
        lines = [
            f"单篇输入：{result['status']}"
            + (
                f" [{result['reason_code']}]"
                if result.get("reason_code")
                else ""
            ),
            f"- 说明：{result.get('message', '')}",
        ]
        item = result.get("item")
        if isinstance(item, dict):
            lines.append(f"- 条目：{item.get('item_key')} {item.get('title') or ''}")
        pdf = result.get("pdf")
        if isinstance(pdf, dict):
            lines.append(
                f"- PDF：{pdf.get('attachment_key')} "
                f"{pdf.get('filename') or ''}"
            )
        if result.get("source_url"):
            lines.append(f"- 来源：{result['source_url']}")
        candidates = result.get("candidates")
        if isinstance(candidates, list):
            lines.append(f"- 候选数：{len(candidates)}")
            lines.extend(
                f"  - {candidate.get('item_key') or candidate.get('attachment_key')}: "
                f"{candidate.get('title') or candidate.get('filename') or ''}"
                for candidate in candidates
            )
        return "\n".join(lines)
    if result.get("operation") == "themes_run":
        kinds = result.get("sources_by_kind") or {}
        detail = (f"（证据包 {kinds.get('evidence_pack', 0)} · 已验证草稿 {kinds.get('draft', 0)}）"
                  if kinds else "")
        return (f"主题流程：{result['status']}"
                f"\n- 文献来源：{result.get('source_count', 0)}{detail}；"
                f"候选：{result['candidate_count']}；已回填：{result['refined_count']}"
                f"\n- 本轮模型调用：{result['model_call_count']}；复用步骤：{result['reused_step_count']}"
                f"\n- 统一主题入口：{result.get('index_path', '尚未创建')}"
                "\n- 修订结果仍为候选，不会自动成为正式主题"
                + (f"\n- 错误：{result['error']['message']}" if result.get("error") else ""))
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
    if args.command == "ai-config" or (args.command == "evidence-generate" and args.paper_input):
        try:
            selection = resolve_ai_config(args.ai_config, provider=args.ai_provider, model=args.ai_model,
                         executable=args.ai_executable, timeout_seconds=args.ai_timeout)
            if args.command == "ai-config":
                result = describe_ai(selection, output_root=args.output_root)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            base = load_config(args.config, require_group=False) if args.config else None
            config = subject_card_config(selection, base_config=base)
            raw = sys.stdin.read() if args.paper_input == "-" else Path(args.paper_input).read_text(encoding="utf-8-sig")
            record = json.loads(raw)
            with ConsoleProgress(enabled=not args.no_progress, heartbeat_interval_seconds=60,
                                 initial_activity="检查单篇输入与所选模型接口") as progress:
                pipeline = resolve_pipeline_mode() if args.pipeline is None else args.pipeline
                if pipeline == "markdown":
                    built = build_markdown_pipeline(config)
                    result = generate_markdown_card_draft(
                        config, record, converter=built.converter, store=built.store,
                        runner=built.runner, options=built.options,
                        progress=progress, output_root=args.output_root,
                    )
                else:
                    result = generate_subject_card_draft(config, record, progress=progress, output_root=args.output_root)
                progress.finish(result)
        except json.JSONDecodeError:
            result = {"ok": False, "error": {"code": "CARD_DRAFT_INPUT_INVALID", "message": "无法读取单篇论文输入 JSON"}}
        except (AIConfigError, ConfigError, OSError, ValueError, RuntimeError) as exc:
            result = {"ok": False, "error": {"code": "CARD_DRAFT_CONFIG_OR_INPUT_INVALID", "message": str(exc)}}
        _emit(result, args.json)
        return 0 if result["ok"] else 3
    if args.command == "doctor":
        try:
            config = load_config(args.config, require_group=False)
            result = build_doctor_report(
                config, output_root=args.output_root, network=args.network
            )
        except (ConfigError, OSError, ValueError) as exc:
            result = {
                "schema_version": 1,
                "operation": "doctor",
                "ok": False,
                "model_invoked": False,
                "platform": sys.platform,
                "checks": [
                    {
                        "name": "config.load",
                        "capability": "config.load",
                        "status": "fail",
                        "detail": str(exc),
                        "fix": "检查 --config 指向的配置文件是否存在且为有效 JSON",
                    }
                ],
                "capabilities": {},
            }
        _emit(result, args.json)
        return 0 if result["ok"] else 3

    if args.command == "run":
        operation = f"session_{args.run_command}"
        try:
            config = load_config(args.config or _default_config_path(), require_group=False)
            raw = (
                sys.stdin.read()
                if args.paper_input == "-"
                else Path(args.paper_input).read_text(encoding="utf-8-sig")
            )
            record = json.loads(raw)
            built = build_session_pipeline(config)
            options = {
                "converter": built.converter,
                "store": built.store,
                "runner": built.runner,
                "run_dir": Path(args.run_dir),
                "output_root": args.output_root,
                "options": built.options,
            }
            if args.run_command == "prepare":
                result = prepare_session_run(config, record, **options)
            else:
                result = finalize_session_run(config, record, **options)
        except json.JSONDecodeError:
            result = {
                "schema_version": 1,
                "operation": operation,
                "ok": False,
                "error": {
                    "code": "CARD_DRAFT_INPUT_INVALID",
                    "message": "无法读取单篇论文输入 JSON",
                },
            }
        except (ConfigError, OSError, ValueError, RuntimeError) as exc:
            result = {
                "schema_version": 1,
                "operation": operation,
                "ok": False,
                "error": {
                    "code": "CARD_DRAFT_CONFIG_OR_INPUT_INVALID",
                    "message": str(exc),
                },
            }
        _emit(result, args.json)
        return 0 if result["ok"] else 3

    try:
        config_loader = load_paper_input_config if args.command == "paper-input" else load_config
        app_config = config_loader(
            args.config if args.command == "paper-input" else (args.config or _default_config_path()),
            base_url=getattr(args, "base_url", None),
            group_id=getattr(args, "group_id", None),
            timeout_seconds=getattr(args, "timeout", None),
            require_group=(
                # 只有需要群组库的命令才强制要求 group 配置；
                # paper-input 走个人库（--user-library / --demo）时不强制。
                args.command in {"evidence-generate", "themes-run"}
                or (
                    args.command == "paper-input"
                    and not getattr(args, "user_library", False)
                    and not getattr(args, "demo", False)
                )
            ),
        )
    except ConfigError as exc:
        result = {
            "schema_version": 1,
            "ok": False,
            "error": {"code": "CONFIG_ERROR", "message": str(exc)},
        }
        _emit(result, args.json)
        return 2

    if args.command == "paper-input":
        try:
            if args.demo:
                result = prepare_demo_paper(app_config.zotero, app_config.pdf_gate)
            elif args.item_key and len(args.item_key) > 1:
                result = prepare_paper_batch(
                    app_config.zotero,
                    app_config.pdf_gate,
                    args.item_key,
                    library_type="user" if args.user_library else "group",
                )
            else:
                result = prepare_paper_input(
                    app_config.zotero,
                    app_config.pdf_gate,
                    query=args.query,
                    item_key=args.item_key[0] if args.item_key else None,
                    library_type="user" if args.user_library else "group",
                    limit=args.limit,
                )
        except (PdfGateError, ZoteroApiError, ValueError) as exc:
            result = {
                "schema_version": 1,
                "ok": False,
                "operation": "paper_input",
                "error": {
                    "code": getattr(exc, "code", "INVALID_INPUT"),
                    "message": str(exc),
                },
            }
    elif args.command == "themes-run":
        try:
            extra = {"migration_only": args.migrate_only}
            if args.dry_run or args.migrate_only:
                # A dry run or a migration-only run must not require a working
                # runner (nor parse the AI selection): it only reports what the
                # next change would need.
                result = run_themes(app_config, dry_run=args.dry_run, **extra)
            else:
                # Same selection contract as the single-paper path; without it
                # the theme run would stay on the adapter baked into
                # config.json and ignore --ai-provider / configs/ai.toml.
                selection = resolve_ai_config(
                    args.ai_config, provider=args.ai_provider, model=args.ai_model,
                    executable=args.ai_executable, timeout_seconds=args.ai_timeout,
                )
                app_config = apply_ai_selection(app_config, selection)
                pipeline = build_theme_pipeline(app_config)
                with ConsoleProgress(enabled=app_config.card_generator.progress.enabled and not args.no_progress,
                    heartbeat_interval_seconds=app_config.card_generator.progress.heartbeat_interval_seconds) as progress:
                    result = run_themes(app_config, progress=progress, pipeline=pipeline, **extra)
                    progress.finish(result)
        except AIConfigError as exc:
            # A bad provider id must name the choices, not become a generic
            # local-error message.
            result = {"schema_version": 1, "ok": False, "error": {
                "code": "CARD_AI_CONFIG_INVALID", "message": str(exc)}}
        except (TaskStoreError, OSError, ValueError) as exc:
            result = {"schema_version": 1, "ok": False, "error": {
                "code": getattr(exc, "code", "PIPELINE_LOCAL_ERROR"), "message": "无法读取本地粗卡输入或运行配置"}}
        if result.get("status") == "CANCELLED":
            _emit(result, args.json)
            return 130
    elif args.command == "evidence-generate":
        progress_config = app_config.card_generator.progress
        with ConsoleProgress(
            enabled=progress_config.enabled and not args.no_progress,
            heartbeat_interval_seconds=progress_config.heartbeat_interval_seconds,
        ) as progress:
            try:
                readiness = preflight(app_config.zotero)
                if not readiness["ok"]:
                    result = readiness
                else:
                    adapter = build_card_generator_adapter(
                        app_config.card_generator, progress=progress,
                    )
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
