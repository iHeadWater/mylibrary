"""Zotero paper input using Python standard library only."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "hydro-platform/automation/src")]
from hydro_platform.paper_input_config import load_paper_input_config, describe_config
from hydro_platform.paper_input import prepare_paper_input, prepare_paper_batch, prepare_demo_paper
from hydro_platform.pdf_gate import PdfGateError
from hydro_platform.zotero import ZoteroApiError
from hydro_platform.config import ConfigError


def main(argv=None):
    parser = argparse.ArgumentParser(description="取得单篇 Zotero 本地 PDF 输入；无 AI 依赖")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--query")
    source.add_argument("--item-key", action="append")
    source.add_argument("--demo", action="store_true")
    source.add_argument("--show-config", action="store_true")
    parser.add_argument("--user-library", action="store_true")
    parser.add_argument("--group-id")
    parser.add_argument("--base-url")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--config", help="可选输入 TOML 或现有 JSON；仅读取 Zotero/PDF 门禁字段")
    parser.add_argument("--output", help="将结果保存为 UTF-8 JSON，避免终端重定向的编码差异")
    args = parser.parse_args(argv)
    try:
        config = load_paper_input_config(args.config, base_url=args.base_url, group_id=args.group_id,
                  timeout_seconds=args.timeout, require_group=not (args.user_library or args.demo or args.show_config))
        if args.show_config:
            result = describe_config(config)
        elif args.demo:
            result = prepare_demo_paper(config.zotero, config.pdf_gate)
        elif args.item_key and len(args.item_key) > 1:
            result = prepare_paper_batch(config.zotero, config.pdf_gate, args.item_key, library_type="user" if args.user_library else "group")
        else:
            result = prepare_paper_input(config.zotero, config.pdf_gate, query=args.query,
                         item_key=args.item_key[0] if args.item_key else None,
                         library_type="user" if args.user_library else "group", limit=args.limit)
        if args.output:
            Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    except (ConfigError, PdfGateError, ZoteroApiError, ValueError, OSError) as exc:
        result = {"ok": False, "operation": "paper_input", "error": {"code": getattr(exc, "code", "INPUT_ERROR"), "message": str(exc)}}
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
