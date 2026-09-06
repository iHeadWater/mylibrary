from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from hydro_platform.card_generators import build_card_generator_adapter
from hydro_platform.config import ConfigError, load_config
from hydro_platform.evidence_packages import EvidencePackageError, sync_evidence_packages
from hydro_platform.pdf_delivery import PdfDeliveryError, prepare_pdf_delivery
from hydro_platform.pdf_gate import PdfGateError, evaluate_pdf_gate
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
        ("scan", "建立基线或检测目标群组中的文献变化"),
        ("pdf-gate", "检查一个父条目的 PDF 全文是否可进入后续处理"),
        ("pdf-delivery", "复核并交付一个任务对应的 Zotero 原始 PDF"),
        ("tasks-sync", "根据 Zotero 和 PDF 门禁同步本地任务清单"),
        ("tasks-list", "查看本地任务清单，不访问 Zotero"),
        ("packages-sync", "为已通过 PDF 门禁的任务创建证据包骨架"),
        ("generator-preflight", "检查 Codex CLI 和 ChatGPT 账号登录状态"),
        ("generator-smoke-test", "执行一次无论文、只读的 Codex 最小模型调用"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument(
            "--config",
            default=_default_config_path(),
            help="总配置文件路径；默认读取项目 config/config.json",
        )
        command.add_argument("--json", action="store_true", help="输出机器可读取 JSON")
        if name not in {"generator-preflight", "generator-smoke-test"}:
            command.add_argument("--base-url", help="覆盖本机 Zotero API 地址")
            command.add_argument("--timeout", type=float, help="请求超时秒数")
        if name in {
            "preflight",
            "scan",
            "pdf-gate",
            "pdf-delivery",
            "tasks-sync",
            "tasks-list",
            "packages-sync",
        }:
            command.add_argument("--group-id", help="覆盖目标 Zotero 群组 ID")
        if name == "scan":
            command.add_argument(
                "--state",
                help="覆盖总配置中的本地快照路径",
            )
        if name in {"pdf-gate", "pdf-delivery"}:
            command.add_argument(
                "--item-key",
                required=True,
                help="需要检查的 Zotero 父条目 Key",
            )

    return parser


def _render_human(result: dict[str, Any]) -> str:
    if result.get("ok"):
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
    try:
        app_config = load_config(
            args.config,
            base_url=getattr(args, "base_url", None),
            group_id=getattr(args, "group_id", None),
            timeout_seconds=getattr(args, "timeout", None),
            require_group=args.command
            in {
                "preflight",
                "scan",
                "pdf-gate",
                "pdf-delivery",
                "tasks-sync",
                "tasks-list",
                "packages-sync",
            },
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
    else:
        raise AssertionError(f"未处理的命令：{args.command}")
    _emit(result, args.json)
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
