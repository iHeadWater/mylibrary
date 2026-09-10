#!/usr/bin/env python3
"""Read Zotero Desktop's local API without mutating the library."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE_URL = os.environ.get("ZOTERO_LOCAL_BASE_URL", "http://127.0.0.1:23119").rstrip("/")
USER_ROOT = "/api/users/0"


def fail(message: str, code: int = 2) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def request_json(path: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(
        BASE_URL + path,
        headers={"Zotero-API-Version": "3", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                if path == "/api/":
                    return {"message": raw.strip()}
                fail(f"Zotero local API returned non-JSON content for {path}")
    except urllib.error.HTTPError as exc:
        fail(f"Zotero local API returned HTTP {exc.code} for {path}")
    except urllib.error.URLError as exc:
        fail(f"Cannot reach Zotero local API at {BASE_URL}: {exc.reason}")


def dump(value: Any, path: str | None = None) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if path:
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(str(target))
    else:
        print(text)


def data_of(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("data", item)


def cmd_status(_: argparse.Namespace) -> None:
    root = request_json("/api/")
    dump({"base_url": BASE_URL, "api_running": True, "root": root})


def cmd_search(args: argparse.Namespace) -> None:
    params = urllib.parse.urlencode({"q": args.query, "limit": args.limit, "sort": "title"})
    dump(request_json(f"{USER_ROOT}/items/top?{params}"), args.out)


def cmd_item(args: argparse.Namespace) -> None:
    key = urllib.parse.quote(args.item_key)
    dump(request_json(f"{USER_ROOT}/items/{key}"), args.out)


def cmd_children(args: argparse.Namespace) -> None:
    key = urllib.parse.quote(args.item_key)
    dump(request_json(f"{USER_ROOT}/items/{key}/children"), args.out)


def cmd_fulltext(args: argparse.Namespace) -> None:
    key = urllib.parse.quote(args.attachment_key)
    payload = request_json(f"{USER_ROOT}/items/{key}/fulltext")
    content = payload.get("content", "") if isinstance(payload, dict) else ""
    if not args.out:
        print(content)
        return
    target = Path(args.out).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    dump(
        {
            "path": str(target),
            "chars": len(content),
            "indexedPages": payload.get("indexedPages"),
            "totalPages": payload.get("totalPages"),
        }
    )


def cmd_packet(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    key = urllib.parse.quote(args.item_key)
    item = request_json(f"{USER_ROOT}/items/{key}")
    children = request_json(f"{USER_ROOT}/items/{key}/children")
    (out_dir / "item.json").write_text(
        json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "children.json").write_text(
        json.dumps(children, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    attachments: list[dict[str, Any]] = []
    for child in children:
        child_data = data_of(child)
        if child_data.get("itemType") != "attachment":
            continue
        attachment_key = child.get("key") or child_data.get("key")
        row = {
            "key": attachment_key,
            "title": child_data.get("title"),
            "contentType": child_data.get("contentType"),
            "linkMode": child_data.get("linkMode"),
            "fulltext": None,
        }
        if attachment_key and child_data.get("contentType") == "application/pdf":
            try:
                fulltext = request_json(
                    f"{USER_ROOT}/items/{urllib.parse.quote(str(attachment_key))}/fulltext"
                )
                fulltext_text = fulltext.get("content", "") if isinstance(fulltext, dict) else ""
                if fulltext_text:
                    target = out_dir / f"fulltext_{attachment_key}.txt"
                    target.write_text(fulltext_text, encoding="utf-8")
                    row["fulltext"] = {
                        "path": target.name,
                        "chars": len(fulltext_text),
                        "indexedPages": fulltext.get("indexedPages"),
                        "totalPages": fulltext.get("totalPages"),
                    }
            except SystemExit:
                row["fulltext"] = {"error": "indexed full text unavailable"}
        attachments.append(row)
    manifest = {
        "item_key": args.item_key,
        "title": data_of(item).get("title"),
        "attachments": attachments,
        "notice": "Temporary reading packet. Do not commit full text to Git.",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    dump(manifest)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=25)
    search.add_argument("--out")
    search.set_defaults(func=cmd_search)
    item = sub.add_parser("item")
    item.add_argument("item_key")
    item.add_argument("--out")
    item.set_defaults(func=cmd_item)
    children = sub.add_parser("children")
    children.add_argument("item_key")
    children.add_argument("--out")
    children.set_defaults(func=cmd_children)
    fulltext = sub.add_parser("fulltext")
    fulltext.add_argument("attachment_key")
    fulltext.add_argument("--out")
    fulltext.set_defaults(func=cmd_fulltext)
    packet = sub.add_parser("packet")
    packet.add_argument("item_key")
    packet.add_argument("--out-dir", required=True)
    packet.set_defaults(func=cmd_packet)
    return p


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

