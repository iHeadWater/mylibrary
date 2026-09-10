#!/usr/bin/env python3
"""Fetch fulltext for every paper in a Zotero collection, straight to disk.

Built for the survey workflow: the collection's combined fulltext is far larger
than an orchestrator's context window, so it is materialised on disk once and
sub-agents read their own paper from there.  Nothing is returned inline.

Two sub-commands::

    # Deduplicated inventory of a collection
    uv run python scripts/fetch_collection_fulltext.py list --collection MLYBU9RM

    # Fetch metadata + fulltext for specific items into {slug}.json
    uv run python scripts/fetch_collection_fulltext.py fetch --collection MLYBU9RM \\
        --keys 9ZWHES3Q,XWWX7JD4 --out-dir outputs/survey-ai-scientist/2026-09-10/fulltext

Output JSON shape (per paper)::

    {
      "result": "<full text>",       # key name chunk_fulltext.py reads
      "itemKey": "...", "attachmentKey": "...",
      "title": "...", "creators": [...], "year": "...", "venue": "...",
      "doi": "...", "slug": "...", "dateAdded": "...",
      "totalPages": 42, "source": "zotero-local-api",
      "attachmentCandidates": [{"key": "...", "chars": 12345}],
      "gdriveFallback": "G:/.../x.pdf"       # only when fulltext failed
    }

The ``result`` key is deliberate: ``scripts/chunk_fulltext.py`` reads
``data["result"]``, so emitting that name lets the existing chunker consume
this output with no changes.

Metadata comes from the Zotero Web API (pyzotero, credentials from ``.env``);
fulltext comes from the Zotero Desktop Local API on ``127.0.0.1:23119`` — the
same conventions as ``hydrolitagent/literature/zotero_notebooklm.py``, which
needs Zotero Desktop running with "Allow other applications to communicate
with Zotero" enabled.  See CLAUDE.md.

Exit codes: 0 ok, 1 bad input / missing credentials, 2 collection not found,
3 no items fetched.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import requests

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# Zotero Desktop Local API — mirrors hydrolitagent/literature/zotero_notebooklm.py.
# ZOTERO_LOCAL_API_URL is the same setting under its older name; container
# compose files set that one, so keep honouring it.
ZOTERO_BASE_URL = (
    os.environ.get("ZOTERO_LOCAL_BASE_URL")
    or os.environ.get("ZOTERO_LOCAL_API_URL")
    or "http://127.0.0.1:23119"
)
ZOTERO_LOCAL_USER = "/api/users/0"
ZOTERO_HEADERS = {"Zotero-API-Version": "3"}

NON_PAPER_TYPES = {"attachment", "note", "annotation"}
PDF_CONTENT_TYPE = "application/pdf"
FULLTEXT_TIMEOUT = 120

# Words too generic to help identify a paper in a filename.
STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "for", "to", "and", "or", "with",
    "from", "at", "by", "as", "is", "are", "via", "towards", "toward",
}


def _load_env() -> None:
    """Load Zotero Web API credentials from the repo .env, like paper_to_zotero."""
    if not _ENV_FILE.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(_ENV_FILE)


def _ascii(text: str) -> str:
    """Fold accents to ASCII (Guimerà -> Guimera) so slugs stay ASCII-safe."""
    folded = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def _first_author_surname(creators: list[dict]) -> str:
    if not creators:
        return "unknown"
    first = creators[0]
    name = first.get("lastName") or first.get("name") or ""
    if not name:
        return "unknown"
    # Institutional authors ("InternAgent Team") -> first usable token.
    token = _ascii(name).split()[0]
    return re.sub(r"[^a-z0-9]", "", token.lower()) or "unknown"


def _make_slug(item: dict) -> str:
    """``{first_author_surname}_{2-3 title keywords}``, lowercase ASCII."""
    data = item.get("data", item)
    surname = _first_author_surname(data.get("creators") or [])
    words = re.findall(r"[A-Za-z0-9]+", _ascii(data.get("title") or "").lower())
    keywords = [w for w in words if w not in STOPWORDS][:3]
    if not keywords:
        keywords = words[:3] or ["untitled"]
    return "_".join([surname, *keywords])


def _creator_names(creators: list[dict]) -> list[str]:
    names: list[str] = []
    for creator in creators or []:
        display = " ".join(
            part for part in (creator.get("firstName"), creator.get("lastName")) if part
        ) or creator.get("name")
        if display:
            names.append(display)
    return names


def _item_year(data: dict) -> str:
    match = re.search(r"(\d{4})", str(data.get("date") or ""))
    return match.group(1) if match else ""


def _venue(data: dict) -> str:
    for field in ("publicationTitle", "proceedingsTitle", "repository", "publisher"):
        if data.get(field):
            return str(data[field])
    return str(data.get("itemType") or "")


def _zotero_local(path: str, *, timeout: int = FULLTEXT_TIMEOUT) -> dict:
    resp = requests.get(f"{ZOTERO_BASE_URL}{path}", headers=ZOTERO_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _fetch_fulltext(attachment_key: str) -> tuple[str, int]:
    """Return ``(text, total_pages)`` from the Local API, or ``("", 0)``."""
    payload = _zotero_local(f"{ZOTERO_LOCAL_USER}/items/{attachment_key}/fulltext")
    return str(payload.get("content") or ""), int(payload.get("totalPages") or 0)


def _is_bare_filename(name: str) -> bool:
    """Whether ``name`` is a plain filename and not a path.

    Zotero's own attachment names are filenames, but the value reaches us from
    a library record and is later joined onto a base directory, so a separator,
    drive letter or UNC prefix is rejected rather than allowed to escape.
    """
    if not name or name in (".", ".."):
        return False
    if any(sep in name for sep in ("/", "\\", "\x00")):
        return False
    if re.match(r"^[A-Za-z]:", name) or name.startswith("~"):
        return False
    return True


def _gdrive_fallback(attachment: dict) -> str | None:
    """Resolve a linked-file attachment to its path under GDRIVE_PAPERS_PATH.

    Returned to the caller instead of being read here: the path goes into the
    JSON so a sub-agent can open the PDF directly with the Read tool, which
    avoids adding a PDF-parsing dependency to this script.
    """
    base = os.environ.get("GDRIVE_PAPERS_PATH")
    raw_path = str(attachment.get("path") or "")
    if not base or not raw_path.startswith("attachments:"):
        return None
    filename = raw_path.split("attachments:", 1)[1]
    if not _is_bare_filename(filename):
        return None
    base_dir = Path(base).resolve()
    candidate = (base_dir / filename).resolve()
    # Belt and braces: the join must stay inside the configured directory.
    if base_dir not in candidate.parents:
        return None
    return str(candidate) if candidate.exists() else None


def _pdf_attachments(zot, item_key: str) -> list[dict]:
    return [
        child["data"]
        for child in zot.children(item_key)
        if child["data"].get("itemType") == "attachment"
        and child["data"].get("contentType") == PDF_CONTENT_TYPE
    ]


def _dedupe(items: list[dict], report) -> list[dict]:
    """Drop duplicate titles, keeping the copy with the most attachments.

    Ties break on the later ``dateAdded`` — the copy most likely to be the one
    a human just fixed up.
    """
    groups: dict[str, list[dict]] = {}
    for item in items:
        key = re.sub(r"\s+", " ", str(item["data"].get("title") or "").strip().lower())
        groups.setdefault(key, []).append(item)

    kept: list[dict] = []
    for key, group in groups.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        scored = sorted(
            group,
            key=lambda i: (len(_pdf_attachments_safe(i)), str(i["data"].get("dateAdded") or "")),
            reverse=True,
        )
        winner, *losers = scored
        report(
            f"  duplicate: {winner['data'].get('title', '')[:70]}\n"
            f"    keep {winner['key']} (dateAdded {winner['data'].get('dateAdded', '')[:19]})\n"
            + "".join(
                f"    drop {l['key']} (dateAdded {l['data'].get('dateAdded', '')[:19]})\n"
                for l in losers
            )
        )
        kept.append(winner)
    return kept


def _pdf_attachments_safe(item: dict) -> list:
    """Attachment count already present on the item, if the caller hydrated it."""
    return item.get("_pdfs") or []


def cmd_list(args, report) -> int:
    zot = args._zot
    items = [
        i
        for i in zot.everything(zot.collection_items(args.collection))
        if i["data"].get("itemType") not in NON_PAPER_TYPES
    ]
    items.sort(key=lambda i: str(i["data"].get("dateAdded") or ""))
    for item in items:
        item["_pdfs"] = _pdf_attachments(zot, item["key"])

    report(f"collection {args.collection}: {len(items)} raw items")
    deduped = _dedupe(items, report)
    deduped.sort(key=lambda i: str(i["data"].get("dateAdded") or ""))

    report(f"after dedup: {len(deduped)} papers\n")
    print(f"{'#':>3} | {'key':<9} | {'dateAdded':<10} | {'author':<14} | {'year':<4} | title")
    for n, item in enumerate(deduped, 1):
        data = item["data"]
        print(
            f"{n:>3} | {item['key']:<9} | {str(data.get('dateAdded') or '')[:10]:<10} | "
            f"{_first_author_surname(data.get('creators') or [])[:14]:<14} | "
            f"{_item_year(data):<4} | {str(data.get('title') or '')[:80]}"
        )
    return 0


def cmd_fetch(args, report) -> int:
    zot = args._zot
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Slugs become filenames, so reject anything that is not a bare name --
    # --slug K=../../etc/x would otherwise write outside --out-dir.
    overrides: dict[str, str] = {}
    for pair in args.slug or []:
        key, _, value = pair.partition("=")
        if not _is_bare_filename(value):
            print(
                f"ERROR: --slug {pair!r} must map to a plain filename "
                "(no separators, drive letters or ~)",
                file=sys.stderr,
            )
            return 1
        overrides[key] = value

    written = 0
    skipped = 0
    failures = 0
    for item_key in [k.strip() for k in args.keys.split(",") if k.strip()]:
        item = zot.item(item_key)
        data = item["data"]
        slug = overrides.get(item_key) or _make_slug(item)
        out_path = out_dir / f"{slug}.json"

        if out_path.exists() and not args.force:
            report(f"[skip] {item_key} -> {out_path.name} exists (use --force)")
            skipped += 1
            continue

        attachments = _pdf_attachments(zot, item_key)
        if not attachments:
            report(f"[warn] {item_key} has no PDF attachment")

        candidates: list[dict] = []
        best_text, best_att, best_pages = "", None, 0
        for attachment in attachments:
            # Default to the first attachment so gdriveFallback still resolves
            # when every fulltext fetch fails -- which is exactly the case it
            # exists for.  Without this, best_att stays None and the fallback
            # is unreachable for the GDrive-only PDFs it was written for.
            if best_att is None:
                best_att = attachment
            try:
                text, pages = _fetch_fulltext(attachment["key"])
            except Exception as exc:  # noqa: BLE001 - report and try the next one
                report(f"[warn] {item_key}/{attachment['key']} fulltext failed: {exc}")
                text, pages = "", 0
            candidates.append({"key": attachment["key"], "chars": len(text)})
            if len(text) > len(best_text):
                best_text, best_att, best_pages = text, attachment, pages

        # A paper can carry news coverage as extra PDFs; show what was picked
        # and what lost, so a polluted attachment is visible immediately.
        for candidate in candidates:
            marker = " <-- used" if best_att and candidate["key"] == best_att["key"] else ""
            report(f"  pdf {candidate['key']}: {candidate['chars']:>7} chars{marker}")
        if best_text:
            report(f"  head: {' '.join(best_text[:110].split())}")

        payload = {
            "result": best_text,
            "itemKey": item_key,
            "attachmentKey": best_att["key"] if best_att else None,
            "title": data.get("title") or "",
            "creators": _creator_names(data.get("creators") or []),
            "year": _item_year(data),
            "venue": _venue(data),
            "doi": data.get("DOI") or "",
            "slug": slug,
            "dateAdded": data.get("dateAdded") or "",
            "totalPages": best_pages,
            "source": "zotero-local-api" if best_text else "unavailable",
            "attachmentCandidates": candidates,
        }
        if not best_text and best_att:
            fallback = _gdrive_fallback(best_att)
            if fallback:
                # Omitted rather than written as null, so the key's presence
                # means "a local PDF is available" and nothing else.
                payload["gdriveFallback"] = fallback

        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # The JSON keeps the text on a single escaped line, which the Read tool
        # cannot page through.  A plain-text twin lets a reader consume it with
        # offset/limit; it is also what gets chunked.
        if best_text:
            out_path.with_suffix(".txt").write_text(best_text, encoding="utf-8")
            report(f"[ok] {item_key} -> {out_path.name} ({len(best_text)} chars)")
            written += 1
        else:
            report(
                f"[FAIL] {item_key} -> {out_path.name}: no fulltext "
                f"(wrote metadata only; source={payload['source']})"
            )
            failures += 1

    total = written + skipped + failures
    if failures and not (written or skipped):
        report("every item failed to yield fulltext")
        return 3
    if skipped:
        report(f"{skipped} of {total} items already present (kept)")
    if failures:
        report(f"{failures} of {total} items yielded no fulltext")
    if not total:
        report("no items requested")
        return 3
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch Zotero collection fulltext to disk (for survey workflows)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("--collection", default="MLYBU9RM", help="Zotero collection key")
        p.add_argument("--quiet", action="store_true", help="Suppress progress output")

    list_p = sub.add_parser("list", help="Print the deduplicated collection inventory")
    add_common(list_p)
    list_p.set_defaults(func=cmd_list)

    fetch_p = sub.add_parser("fetch", help="Fetch metadata + fulltext for given items")
    add_common(fetch_p)
    fetch_p.add_argument("--keys", required=True, help="Comma-separated Zotero item keys")
    fetch_p.add_argument("--out-dir", required=True, help="Directory for {slug}.json files")
    fetch_p.add_argument(
        "--slug",
        action="append",
        metavar="KEY=SLUG",
        help="Override an auto-generated slug (repeatable)",
    )
    fetch_p.add_argument("--force", action="store_true", help="Overwrite existing files")
    fetch_p.set_defaults(func=cmd_fetch)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy codepage; titles here are not ASCII.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    args = build_parser().parse_args(argv)
    _load_env()

    def report(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    api_key = os.environ.get("ZOTERO_API_KEY")
    library_id = os.environ.get("ZOTERO_LIBRARY_ID")
    if not api_key or not library_id:
        print(
            "ERROR: ZOTERO_API_KEY / ZOTERO_LIBRARY_ID missing "
            f"(looked in {_ENV_FILE} and the environment)",
            file=sys.stderr,
        )
        return 1

    from pyzotero import zotero as zotero_module

    args._zot = zotero_module.Zotero(
        library_id, os.environ.get("ZOTERO_LIBRARY_TYPE", "user"), api_key
    )

    try:
        return args.func(args, report)
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary
        message = str(exc)
        hint = ""
        if "404" in message or "Not Found" in message:
            hint = (
                f"\n  Collection key {args.collection!r} not found. "
                "Check it with the `list` sub-command on another key."
            )
        print(f"ERROR: {type(exc).__name__}: {message}{hint}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
