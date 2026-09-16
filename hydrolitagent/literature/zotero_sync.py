#!/usr/bin/env python3
"""Sync a downloaded PDF to Zotero as a linked_file attachment.

Copies the PDF to the Google Drive papers folder (the Zotero Linked Attachment
Base Directory), enriches metadata via :func:`paper_to_zotero.build_item`
(Crossref → arXiv API → Semantic Scholar, so arXiv preprints get a correct
``preprint`` record instead of a sparse Crossref-404 fallback), and creates a
Zotero item with a linked_file attachment via pyzotero.  Zotero cloud storage
is **not** used — the PDF lives in the GDrive folder and Zotero stores only a
pointer.  Re-runs for the same DOI are skipped (idempotent).

Usage::

    python scripts/zotero_sync.py <pdf_path> <doi> [--dry-run] [--json] [--allow-duplicate]

Environment variables::

    ZOTERO_API_KEY      Zotero Web API key (https://www.zotero.org/settings/keys)
    ZOTERO_LIBRARY_ID   Numeric Zotero user library ID
    GDRIVE_PAPERS_PATH  Local path to GDrive papers folder (ZotMoov target)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from hydrolitagent.literature.download_pdf import (
    normalize_doi,
    slug_from_doi,
    verify_pdf,
)

# Load .env so users don't need to export vars manually.
# <repo>/hydrolitagent/literature/zotero_sync.py → <repo>/
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
if _ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def get_zotero_client():
    """Create a pyzotero client from environment variables.

    Returns:
        :class:`pyzotero.zotero.Zotero`

    Raises:
        ValueError: if required env vars are missing.
    """
    api_key = os.environ.get("ZOTERO_API_KEY", "")
    library_id = os.environ.get("ZOTERO_LIBRARY_ID", "")

    if not api_key or not library_id:
        raise ValueError(
            "ZOTERO_API_KEY and ZOTERO_LIBRARY_ID must be set in environment.\n"
            "Get an API key at https://www.zotero.org/settings/keys"
        )

    from pyzotero import zotero

    return zotero.Zotero(library_id, "user", api_key)


def get_gdrive_papers_path() -> Path:
    """Get the Google Drive papers folder path from env.

    Raises:
        ValueError: if ``GDRIVE_PAPERS_PATH`` is not set.
    """
    path = os.environ.get("GDRIVE_PAPERS_PATH", "")
    if not path:
        raise ValueError(
            "GDRIVE_PAPERS_PATH must be set in environment.\n"
            "This should point to the Google Drive folder where ZotMoov "
            "stores linked PDFs."
        )
    return Path(path)


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------


def _copy_to_gdrive(pdf_path: str | Path, gdrive_dir: str | Path, dest_filename: str) -> Path:
    """Copy PDF to the Google Drive papers folder.

    Args:
        pdf_path: Path to the source PDF.
        gdrive_dir: Google Drive papers directory.
        dest_filename: Destination filename (e.g. ``j.jhydrol.2024.132471.pdf``).

    Returns:
        Destination path.
    """
    src = Path(pdf_path)
    dst = Path(gdrive_dir) / dest_filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


# ---------------------------------------------------------------------------
# Zotero item creation
# ---------------------------------------------------------------------------
# Item metadata (Crossref → arXiv API → Semantic Scholar enrichment) is
# delegated to hydrolitagent.zotero.paper_to_zotero.build_item(), keeping a
# single source of truth that handles arXiv preprints correctly.

ATTACHMENT_PATH_PREFIX = "attachments:"


def _create_attachment(zot, parent_key: str, attachment_filename: str) -> str:
    """Create a linked_file attachment under ``parent_key``.

    Uses Zotero's portable ``attachments:`` scheme, which Zotero resolves against
    the user's "Linked Attachment Base Directory" preference
    (Zotero → Preferences → Advanced → Files and Folders).

    Args:
        zot: :class:`pyzotero.zotero.Zotero` client.
        parent_key: 8-character key of the parent item.
        attachment_filename: Filename within the linked attachment base directory.

    Returns:
        The attachment key, or ``""`` when the API reported no success entry.
    """
    attach_tmpl = zot.item_template("attachment", "linked_file")
    attach_tmpl["title"] = attachment_filename
    attach_tmpl["parentItem"] = parent_key
    attach_tmpl["path"] = f"{ATTACHMENT_PATH_PREFIX}{attachment_filename}"
    attach_tmpl["contentType"] = "application/pdf"

    attach_resp = zot.create_items([attach_tmpl])
    attach_created = attach_resp.get("success", {})
    return list(attach_created.values())[0] if attach_created else ""


def _existing_attachments(zot, parent_key: str) -> list[dict]:
    """Return the child attachment data dicts of ``parent_key``.

    Best-effort: a failed lookup yields ``[]`` so the caller falls back to
    creating an attachment rather than aborting the sync.
    """
    try:
        children = zot.children(parent_key)
    except Exception:
        return []
    out: list[dict] = []
    for child in children:
        data = child.get("data") or {}
        if data.get("itemType") == "attachment":
            out.append(data)
    return out


def _sha256(path: str | Path) -> str:
    """SHA-256 of a file — distinguishes 'the same PDF' from 'a different PDF'."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _create_zotero_item(
    zot,
    item_data: dict,
    extra_fields: dict,
    attachment_filename: str,
) -> tuple[str, str]:
    """Create a Zotero parent item with a linked_file attachment.

    Args:
        zot: :class:`pyzotero.zotero.Zotero` client.
        item_data: Item dict from :func:`paper_to_zotero.build_item`.
        extra_fields: Extra fields to write into the ``extra`` field.
        attachment_filename: Filename for the linked_file (e.g. ``paper.pdf``).

    Returns:
        ``(parent_key, attachment_key)`` — 8-character Zotero item keys.

    Raises:
        RuntimeError: if the Zotero API returns a failure.
    """
    # Pop itemType before template to avoid overwriting
    item_type = item_data.pop("itemType", "journalArticle")
    tmpl = zot.item_template(item_type)
    tmpl.update(item_data)

    # Format extra fields as key: value lines
    if extra_fields:
        extra_parts = [f"{k}: {v}" for k, v in extra_fields.items()]
        tmpl["extra"] = "\n".join(extra_parts)

    # Create parent item
    resp = zot.create_items([tmpl])
    created = resp.get("success", {})
    if not created:
        failed = resp.get("failed", {})
        err_msg = failed.get("0", {}).get("message", str(resp))
        raise RuntimeError(f"Failed to create Zotero item: {err_msg}")

    parent_key = list(created.values())[0]
    attach_key = _create_attachment(zot, parent_key, attachment_filename)

    return parent_key, attach_key


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

# Duplicate detection uses a local DOI→key index cached inside the GDrive papers
# folder (`.zotero-sync-index.json`).  Zotero's quick-search ``q`` does NOT index
# the DOI field (verified live), so the only way to ask "does this DOI already
# exist?" is a full top-level scan — slow on large libraries (~6k items).
# The index file is a normal file in the (Google-Drive-synced) papers folder, so
# it persists across repo re-clones and carries over to other machines sharing
# the same GDrive folder.
#
# A HIT is authoritative.  A MISS is NOT: items created outside this pipeline
# (Zotero desktop, the Beaver importer, the container pipeline) never wrote to
# the index, so absence means "not indexed", not "does not exist".  Scanning on
# a miss costs one scan per genuinely-new paper, and is what stops an existing
# record from silently becoming a duplicate one.

INDEX_FILENAME = ".zotero-sync-index.json"


def _index_path(gdrive_dir: str | Path) -> Path:
    return Path(gdrive_dir) / INDEX_FILENAME


def _load_index(gdrive_dir: str | Path) -> dict[str, str]:
    """Load {doi: zotero_key} from the cached index (best-effort)."""
    p = _index_path(gdrive_dir)
    if p.exists():
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
            items = payload.get("items")
            if isinstance(items, dict):
                return items
        except Exception:
            pass
    return {}


def _save_index(gdrive_dir: str | Path, items: dict[str, str]) -> None:
    """Persist {doi: zotero_key}. Best-effort — never fails the sync."""
    try:
        from datetime import datetime, timezone
        payload = {
            "version": 1,
            "updated": datetime.now(timezone.utc).isoformat(),
            "items": items,
        }
        _index_path(gdrive_dir).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def _scan_server_dois(zot) -> dict[str, str]:
    """Full top-level scan → {doi: key}. Expensive — only run on (re)build.

    Zotero items returned by the API carry the key at the object top level
    (``it["key"]``), with fields under ``it["data"]``.
    """
    items: dict[str, str] = {}
    for it in zot.everything(zot.top(limit=100)):
        key = it.get("key")
        d = it.get("data", {}) or {}
        if not key or d.get("itemType") == "attachment":
            continue
        doi = (d.get("DOI") or "").strip()
        if doi:
            items.setdefault(doi, key)
        extra = d.get("extra") or ""
        for line in extra.splitlines():
            line = line.strip()
            if line.startswith("DOI: "):
                items.setdefault(line[5:].strip(), key)
    return items


def _existing_key(zot, doi: str, gdrive_dir: str | Path, refresh: bool) -> str | None:
    """Return an existing Zotero key for ``doi``, or None.

    A hit in the cached index is authoritative and costs nothing.  A miss forces
    a server scan, because the index only knows about items this pipeline
    created — see the note above ``INDEX_FILENAME``.  ``refresh=True`` forces a
    scan even on a hit.
    """
    items = _load_index(gdrive_dir)
    path = _index_path(gdrive_dir)
    if refresh or not path.exists() or doi not in items:
        print("   Scanning library for existing DOI (may take a while)...", flush=True)
        items = _scan_server_dois(zot)
        _save_index(gdrive_dir, items)
    return items.get(doi)


def main():
    """Console script entry point — argparse CLI matching ``download_pdf.py`` style."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Sync a downloaded PDF to Zotero as a linked_file attachment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python scripts/zotero_sync.py paper.pdf 10.1016/j.jhydrol.2024.132471
  python scripts/zotero_sync.py paper.pdf 10.1016/j.jhydrol.2024.132471 --dry-run
  python scripts/zotero_sync.py paper.pdf 10.1016/j.jhydrol.2024.132471 --json""",
    )
    parser.add_argument("pdf_path", help="Path to the downloaded PDF file")
    parser.add_argument(
        "doi", help="DOI of the paper (e.g. 10.1016/j.jhydrol.2024.132471)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without creating Zotero item"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output result as JSON"
    )
    parser.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="Create a new item even if one with this DOI already exists",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Restore the old behaviour: exit without attaching when the DOI exists",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Overwrite the GDrive PDF when the attachment already in this slot "
        "has different content (default: report a conflict and change nothing)",
    )
    parser.add_argument(
        "--refresh-index",
        action="store_true",
        help="Rebuild the local DOI index from a full server scan before checking",
    )

    args = parser.parse_args()

    # -- Validate inputs --------------------------------------------------
    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    doi = normalize_doi(args.doi)
    slug = slug_from_doi(doi)
    dest_filename = f"{slug}.pdf"

    try:
        gdrive_dir = get_gdrive_papers_path()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    # -- Verify PDF (extracts embedded metadata for fallback) --------------
    try:
        pdf_meta = verify_pdf(pdf_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: Invalid PDF: {e}", file=sys.stderr)
        sys.exit(3)

    # -- Enrich metadata ------------------------------------------------
    # Single source of truth = paper_to_zotero.build_item() (Crossref →
    # arXiv API → Semantic Scholar). arXiv DOIs (10.48550/arXiv.*) are not
    # registered with Crossref, so the old Crossref-only builder produced
    # sparse/mangled records for preprints; delegating fixes that.
    # (Lazy import: keeps zotero_sync importable without pyzotero.)
    from hydrolitagent.zotero.paper_to_zotero import build_item

    fallback_meta = {
        "title": pdf_meta.title or "",
        "author": pdf_meta.authors[0] if pdf_meta.authors else "",
    }
    item_data, extra_fields = build_item(doi, fallback_meta)

    # -- Dry-run: preview only --------------------------------------------
    if args.dry_run:
        print("[dry-run] Would:")
        print(f"  Copy PDF to: {gdrive_dir / dest_filename}")
        print(f"  DOI:         {doi}")
        print(f"  Type:        {item_data.get('itemType', '?')}")
        print(f"  Title:       {item_data.get('title', '')[:80]}")
        print(f"  Authors:     {len(item_data.get('creators', []))}")
        print(f"  Date:        {item_data.get('date', '')}")
        print(f"  Abstract:    {'yes' if item_data.get('abstractNote') else 'no'}")
        print(f"  Extra:       {list(extra_fields.keys())}")
        print(f"  Attachment:  linked_file → attachments:{dest_filename}")
        return

    try:
        zot = get_zotero_client()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    # -- Existing item: attach the PDF to it rather than skipping -----------
    # This branch used to print SKIP and return, which left the common case
    # "the record exists but has no PDF" with no way forward short of
    # --allow-duplicate, which creates a *second* item for the same DOI.
    if not args.allow_duplicate:
        existing = None
        try:
            existing = _existing_key(zot, doi, gdrive_dir, refresh=args.refresh_index)
        except Exception as e:  # never block the sync on a check failure
            print(f"Note: duplicate check failed ({e}); continuing", file=sys.stderr)
        if existing:
            if args.skip_existing:
                print(
                    f"SKIP — item already in library (key {existing}) for DOI {doi}; "
                    "use --allow-duplicate to force"
                )
                if args.json:
                    print(json.dumps(
                        {"ok": False, "skipped": True, "zotero_key": existing, "doi": doi}
                    ))
                return

            attach_path = f"{ATTACHMENT_PATH_PREFIX}{dest_filename}"
            same_slot = None
            for att in _existing_attachments(zot, existing):
                if (att.get("path") or "") == attach_path:
                    same_slot = att
                    break

            if same_slot:
                target = Path(gdrive_dir) / dest_filename
                identical = target.exists() and _sha256(target) == _sha256(pdf_path)
                if identical:
                    print(f"OK — already attached to {existing} (identical content)")
                    if args.json:
                        print(json.dumps({
                            "ok": True, "action": "unchanged",
                            "attached_to_existing": True,
                            "zotero_key": existing, "doi": doi,
                            "attachment_key": same_slot.get("key", ""),
                        }))
                    return
                if not args.replace:
                    # Never clobber a good copy behind the user's back.
                    print(
                        f"CONFLICT — {dest_filename} is already attached to {existing} "
                        "but its content differs from the incoming PDF; nothing "
                        "changed. Re-run with --replace to overwrite it."
                    )
                    if args.json:
                        print(json.dumps({
                            "ok": False, "action": "conflict",
                            "attached_to_existing": True,
                            "zotero_key": existing, "doi": doi,
                        }))
                    return
                try:
                    gdrive_path = _copy_to_gdrive(pdf_path, gdrive_dir, dest_filename)
                except OSError as e:
                    print(f"Error: Failed to copy PDF to GDrive: {e}", file=sys.stderr)
                    sys.exit(4)
                print(f"OK — refreshed {dest_filename} in place for {existing}")
                if args.json:
                    print(json.dumps({
                        "ok": True, "action": "refreshed",
                        "attached_to_existing": True,
                        "zotero_key": existing, "doi": doi,
                        "attachment_key": same_slot.get("key", ""),
                        "gdrive_path": str(gdrive_path),
                    }))
                return

            # No attachment in this slot yet: add one to the EXISTING item.
            try:
                gdrive_path = _copy_to_gdrive(pdf_path, gdrive_dir, dest_filename)
            except OSError as e:
                print(f"Error: Failed to copy PDF to GDrive: {e}", file=sys.stderr)
                sys.exit(4)
            attach_key = _create_attachment(zot, existing, dest_filename)

            _idx = _load_index(gdrive_dir)
            _idx[doi] = existing
            _save_index(gdrive_dir, _idx)

            if args.json:
                print(json.dumps({
                    "ok": True, "action": "attached",
                    "attached_to_existing": True,
                    "zotero_key": existing, "attachment_key": attach_key,
                    "doi": doi, "gdrive_path": str(gdrive_path),
                }))
            else:
                print("OK — PDF attached to existing Zotero item")
                print(f"  Key:        {existing}")
                print(f"  Attachment: {attach_key} (linked_file -> {attach_path})")
                print(f"  PDF copied: {gdrive_path}")
            return

    # -- Copy PDF to Google Drive folder ----------------------------------
    try:
        gdrive_path = _copy_to_gdrive(pdf_path, gdrive_dir, dest_filename)
    except OSError as e:
        print(f"Error: Failed to copy PDF to GDrive: {e}", file=sys.stderr)
        sys.exit(4)

    # -- Create Zotero item + linked_file attachment ----------------------
    try:
        parent_key, attach_key = _create_zotero_item(
            zot, item_data, extra_fields, dest_filename
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(5)

    # -- Record in the local dedupe index (merge, don't clobber) ----------
    _idx = _load_index(gdrive_dir)
    _idx[doi] = parent_key
    _save_index(gdrive_dir, _idx)

    # -- Report -----------------------------------------------------------
    result = {
        "ok": True,
        "zotero_key": parent_key,
        "attachment_key": attach_key,
        "doi": doi,
        "title": item_data.get("title", ""),
        "gdrive_path": str(gdrive_path),
        "attachment_path": f"attachments:{dest_filename}",
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=True))
    else:
        print("OK — Zotero item created")
        print(f"  Key:        {parent_key}")
        print(f"  Title:      {item_data.get('title', '')}")
        print(f"  DOI:        {doi}")
        print(f"  Attachment: linked_file → attachments:{dest_filename}")
        print(f"  PDF copied: {gdrive_path}")


if __name__ == "__main__":
    main()
