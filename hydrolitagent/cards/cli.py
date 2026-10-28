from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from hydrolitagent.cards.application.card_workflow import (
    finalize_session_run,
    generate_markdown_card_draft,
    prepare_session_run,
)
from hydrolitagent.cards.application.reading_layer import build_reading_layer
from hydrolitagent.cards.card_validation import ValidationAssets, validate_subject_card_file
from hydrolitagent.cards.ai_config import (
    AIConfigError,
    apply_ai_selection,
    describe_ai,
    resolve_ai_config,
    subject_card_config,
)
from hydrolitagent.cards.composition import (
    build_doctor_report,
    build_markdown_pipeline,
    build_session_pipeline,
    build_theme_pipeline,
)
from hydrolitagent.cards.config import ConfigError, load_config
from hydrolitagent.cards.paper_input_config import load_paper_input_config
from hydrolitagent.cards.pdf_gate import PdfGateError
from hydrolitagent.cards.paper_input import (
    prepare_demo_paper,
    prepare_paper_batch,
    prepare_paper_input,
)
from hydrolitagent.cards.progress import ConsoleProgress
from hydrolitagent.cards.themes import run_themes
from hydrolitagent.cards.theme_session import (
    finalize_theme_session,
    prepare_theme_session,
    theme_session_run_dir,
)
from hydrolitagent.cards.tasks import TaskStoreError
from hydrolitagent.cards.zotero import ZoteroApiError
from hydrolitagent.cards._paths import DEFAULT_CONFIG_PATH, REPO_ROOT
from hydrolitagent._config import PathConfigError, resolve_literature_root





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
        ("evidence-generate", "读取单篇论文输入记录并生成待校验主体卡草稿"),
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
        if name in {"paper-input", "themes-run"}:
            command.add_argument("--base-url", help="覆盖本机 Zotero API 地址")
            command.add_argument("--timeout", type=float, help="请求超时秒数")
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
            command.add_argument(
                "--run-dir",
                help=(
                    "in_session 分步协议的运行目录；默认 <runtime_dir>/theme-session。"
                    "重跑同一目录会接着未完成的步骤"
                ),
            )
            # The same selection the single-paper path accepts: a theme run
            # makes model calls too, so it must not be stuck on the adapter
            # baked into config.json.
            command.add_argument("--ai-config", help="模型选择 TOML；默认 configs/ai.toml")
            command.add_argument(
                "--ai-provider", metavar="RUNNER",
                help="制卡运行器 id：direct（直连 API）或 in_session；可用值见 ai-config --json 的 runners",
            )
            command.add_argument("--ai-model", help="所选服务可用的模型名")
            command.add_argument("--ai-timeout", type=float)
        if name == "evidence-generate":
            command.add_argument("--ai-config", help="模型选择 TOML；默认 configs/ai.toml")
            # The registry, not argparse, owns the list of runner ids: a new
            # adapter must not require editing this parser.
            command.add_argument(
                "--ai-provider", metavar="RUNNER",
                help="制卡运行器 id：direct（直连 API）或 in_session；可用值见 ai-config --json 的 runners",
            )
            command.add_argument("--ai-model", help="所选服务可用的模型名")
            command.add_argument("--ai-timeout", type=float)
            command.add_argument("--output-root", help="本次产物根；不传则用默认解析（configs/paths.toml → outputs/）")
            command.add_argument(
                "--paper-input", required=True,
                help="单篇 READY JSON（输入记录）文件，或 - 从 stdin 读取；仅生成待校验草稿",
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
            "--theme",
            action="store_true",
            help=(
                "主题池分步协议：发现 → 每篇精读 → 回填 → 提交；"
                "每步写入 request.json，agent 写 response.json 后再 finalize"
            ),
        )
        run_command.add_argument(
            "--paper-input",
            help="单篇 READY JSON（输入记录）文件，或 - 从 stdin 读取；--theme 模式下不要传",
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
        help="制卡运行器 id：direct 或 in_session；可用值见本命令输出的 runners",
    )
    ai.add_argument("--ai-model")
    ai.add_argument("--ai-timeout", type=float)
    ai.add_argument("--output-root")
    ai.add_argument("--json", action="store_true")

    index = subparsers.add_parser(
        "index",
        help="生成可读的产物阅读层：HOME、卡片索引、阅读版卡片与主题阅读页；不改机器产物",
    )
    index.add_argument("--root", help="产物根；默认按 configs/paths.toml 解析（默认 outputs/）")
    index.add_argument(
        "--runtime-dir",
        help="转换缓存根（papers/<pdf_sha256>/...）；默认仓库根 .runtime",
    )
    index.add_argument("--json", action="store_true", help="输出机器可读取 JSON")
    return parser


def _render_human(result: dict[str, Any]) -> str:
    if result.get("operation") == "cards_index":
        broken = result.get("broken_links") or []
        if result.get("error"):
            error = result["error"]
            return f"阅读层生成失败 [{error.get('code')}]：{error.get('message')}"
        lines = [
            f"阅读层{'存在断链' if broken else '已生成'}：产物根 {result.get('root')}",
            f"- 写入 {len(result.get('written') or [])} 个文件；"
            f"未变 {len(result.get('unchanged') or [])} 个",
            f"- 卡片 {result.get('card_count', 0)} 张；主题 {result.get('theme_count', 0)} 个",
            f"- 链接自检：{result.get('links_checked', 0)} 条，断链 {len(broken)} 条",
        ]
        for link in broken:
            lines.append(f"  - {link['file']} -> {link['target']}")
        if result.get("warnings"):
            lines.append("- 警告：" + "；".join(result["warnings"]))
        if not broken:
            lines.append(f"- 从 {Path(result.get('root', '')) / 'HOME.md'} 开始读")
        return "\n".join(lines)
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
    if result.get("operation") in {"theme_session_prepare", "theme_session_finalize"}:
        if not result.get("ok"):
            error = result.get("error", {})
            return (
                f"主题池分步失败 [{error.get('code', 'UNKNOWN')}]："
                f"{error.get('message', '未知错误')}"
            )
        if result.get("replayed"):
            return (
                f"同一份 response.json 已收口过，未重复推进；当前步骤：{result.get('step')}"
            )
        if result.get("status") == "UNCHANGED":
            return "\n".join([
                "主题池已包含这批来源的最新结果；没有待处理的步骤",
                f"- 候选主题：{result.get('candidate_count', 0)}；"
                f"已回填：{result.get('refined_count', 0)}",
                f"- 统一主题入口：{result.get('index_path', '尚未创建')}",
                "- 没有调用模型",
            ])
        if result.get("status") == "NO_ROUGH_CARDS":
            return "没有可用的来源草稿或证据包；未写运行目录、未调用模型"
        if result.get("operation") == "theme_session_prepare":
            return "\n".join([
                "已准备主题池当前步骤；平台未调用模型",
                f"- 运行目录：{result.get('run_dir')}",
                f"- 步骤：{result.get('step_kind')} · {result.get('step')}"
                f"（第 {int(result.get('step_index', 0)) + 1} 步；"
                f"后续 {len(result.get('remaining_steps') or [])} 个）",
                f"- 材料：request.json / output.schema.json；答案：{result.get('response_file')}",
                f"- 下一步：{result.get('next_action')}",
                f"- 写完后运行：cards run finalize --theme --run-dir {result.get('run_dir')}",
            ])
        if result.get("status") == "COMPLETED":
            return "\n".join([
                "主题池分步已完成；全部步骤通过校验并已提交",
                f"- 候选主题：{result.get('candidate_count', 0)}；已回填：{result.get('refined_count', 0)}",
                f"- 动作：{result.get('action')}；复用精读：{result.get('reused_reading_count', 0)}",
                f"- 运行目录：{result.get('run_dir')}",
                "- 修订结果仍为候选，不会自动成为正式主题",
            ])
        return "\n".join([
            f"已保存步骤 {result.get('step')}；下一步已写入同一运行目录",
            f"- 下一步骤：{result.get('next_step_kind')} · {result.get('next_step')}"
            f"（后续 {len(result.get('remaining_steps') or [])} 个）",
            f"- 下一步：{result.get('next_action')}",
            f"- 答案文件：{result.get('response_file')}（运行目录 {result.get('run_dir')}）",
        ])
    if result.get("operation") == "themes_run":
        kinds = result.get("sources_by_kind") or {}
        detail = (f"（证据包 {kinds.get('evidence_pack', 0)} · 已验证草稿 {kinds.get('draft', 0)}）"
                  if kinds else "")
        lines = [f"主题流程：{result['status']}",
                 f"- 文献来源：{result.get('source_count', 0)}{detail}；"
                 f"候选：{result.get('candidate_count', 0)}；已回填：{result.get('refined_count', 0)}",
                 f"- 本轮模型调用：{result.get('model_call_count', 0)}；"
                 f"复用步骤：{result.get('reused_step_count', 0)}",
                 f"- 统一主题入口：{result.get('index_path', '尚未创建')}",
                 "- 修订结果仍为候选，不会自动成为正式主题"]
        if result.get("step"):
            lines.append(f"- 当前步骤：{result.get('step_kind')} · {result.get('step')}"
                         f"（运行目录 {result.get('run_dir')}）")
        if result.get("next_action"):
            lines.append(f"- 下一步：{result['next_action']}")
        if result.get("error"):
            lines.append(f"- 错误：{result['error'].get('message')}")
        return "\n".join(lines)
    error = result.get("error", {})
    return f"失败 [{error.get('code', 'UNKNOWN')}]: {error.get('message', '未知错误')}"


def _emit(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_render_human(result))


def _themes_run_session(app_config, run_dir) -> dict[str, Any]:
    """``themes-run --ai-provider in_session``: stage one step, never call a model.

    The report keeps the ``themes_run`` shape existing consumers read; the new
    fields say which step is waiting and where its answer file goes.
    """

    # ``in_session`` runs inside the current agent: there is no configured model,
    # so naming one would put a false field into the pool's input fingerprint and
    # into every reading record.
    session_config = replace(app_config, card_generator=replace(
        app_config.card_generator, model=None, reasoning_effort=None))
    prepared = prepare_theme_session(
        session_config,
        run_dir=Path(run_dir) if run_dir else theme_session_run_dir(session_config),
        pipeline=build_session_pipeline(session_config),
    )
    view = {
        "schema_version": 1,
        "operation": "themes_run",
        "ok": prepared.get("ok", False),
        "status": prepared.get("status"),
        "protocol_version": prepared.get("protocol_version"),
        "run_id": prepared.get("run_id"),
        "model_call_count": 0,
        "model_invoked": False,
        "saved_step_count": 0,
        "reused_step_count": prepared.get("reused_step_count", 0),
        "candidate_count": prepared.get("candidate_count", 0),
        "refined_count": prepared.get("refined_count", 0),
        "themes": prepared.get("themes", []),
        "dry_run": False,
        "migration_only": False,
        "git_modified": False,
        **prepared,
    }
    # The platform did not call a model in this mode, whatever the staging did.
    view.update(operation="themes_run", model_invoked=False, model_call_count=0)
    return view


def _run_index(args) -> dict[str, Any]:
    """Resolve where the product root is, then generate the reading layer."""

    try:
        root = resolve_literature_root(root=args.root)
    except (PathConfigError, OSError, ValueError) as exc:
        return {
            "schema_version": 1,
            "operation": "cards_index",
            "ok": False,
            "error": {"code": "READING_ROOT_INVALID", "message": str(exc)},
        }
    runtime_dir = Path(args.runtime_dir) if args.runtime_dir else REPO_ROOT / ".runtime"
    try:
        return build_reading_layer(root, runtime_dir=runtime_dir)
    except OSError as exc:
        return {
            "schema_version": 1,
            "operation": "cards_index",
            "ok": False,
            "root": str(root),
            "error": {"code": "READING_LAYER_WRITE_FAILED", "message": str(exc)},
        }


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdio()
    args = _parser().parse_args(argv)
    if args.command == "index":
        result = _run_index(args)
        _emit(result, args.json)
        return 0 if result["ok"] else 3
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
    if args.command in {"ai-config", "evidence-generate"}:
        try:
            selection = resolve_ai_config(args.ai_config, provider=args.ai_provider, model=args.ai_model,
                         timeout_seconds=args.ai_timeout)
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
                built = build_markdown_pipeline(config)
                result = generate_markdown_card_draft(
                    config, record, converter=built.converter, store=built.store,
                    runner=built.runner, options=built.options,
                    progress=progress, output_root=args.output_root,
                )
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
        theme = getattr(args, "theme", False)
        operation = (f"theme_session_{args.run_command}" if theme
                     else f"session_{args.run_command}")
        try:
            if theme and args.paper_input:
                raise ValueError("--theme 与 --paper-input 不能同时使用")
            if not theme and not args.paper_input:
                raise ValueError("单篇两阶段协议需要 --paper-input；主题池用 --theme")
            if theme:
                config = load_config(args.config or _default_config_path(), require_group=True)
                built = build_session_pipeline(config)
                runner = (prepare_theme_session if args.run_command == "prepare"
                          else finalize_theme_session)
                result = runner(config, run_dir=Path(args.run_dir), pipeline=built)
            else:
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
                args.command == "themes-run"
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
                    timeout_seconds=args.ai_timeout,
                )
                app_config = apply_ai_selection(app_config, selection)
                if selection["provider"] == "in_session":
                    # Nothing here may call a model: stage one step at a time and
                    # let the current agent write response.json.
                    result = _themes_run_session(app_config, args.run_dir)
                else:
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
    else:
        raise AssertionError(f"未处理的命令：{args.command}")
    _emit(result, args.json)
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
