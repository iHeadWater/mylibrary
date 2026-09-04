from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from hydro_platform.config import ConfigError, load_config
from hydro_platform.snapshot import SnapshotError, scan_group
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
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument(
            "--config",
            default=_default_config_path(),
            help="总配置文件路径；默认读取项目 config/config.json",
        )
        command.add_argument("--base-url", help="覆盖本机 Zotero API 地址")
        command.add_argument("--timeout", type=float, help="请求超时秒数")
        command.add_argument("--json", action="store_true", help="输出机器可读取 JSON")
        if name in {"preflight", "scan"}:
            command.add_argument("--group-id", help="覆盖目标 Zotero 群组 ID")
        if name == "scan":
            command.add_argument(
                "--state",
                help="覆盖总配置中的本地快照路径",
            )

    return parser


def _render_human(result: dict[str, Any]) -> str:
    if result.get("ok"):
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
            base_url=args.base_url,
            group_id=getattr(args, "group_id", None),
            timeout_seconds=args.timeout,
            require_group=args.command in {"preflight", "scan"},
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
    else:
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
    _emit(result, args.json)
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
