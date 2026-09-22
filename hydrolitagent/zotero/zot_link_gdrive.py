#!/usr/bin/env python3
"""Create a linked_file attachment in Zotero pointing to a Google Drive file.

Credentials resolve the SAME way as ``paper_to_zotero._resolve_zotero_credentials()``:
environment variables first (``ZOTERO_LIBRARY_ID`` / ``ZOTERO_API_KEY``), then a
per-key override from the TOML config when that file exists and has the key.

This module is deliberately SELF-CONTAINED: it is copied verbatim into the hermes
container as ``/opt/hermes/scripts/zot-link-gdrive.py``, so it must not import
``hydrolitagent.*``.  That is also why ``.env`` is read with a tiny hand-rolled
parser instead of python-dotenv.

Usage:
    zot-link-gdrive <zotero_key> <filename> [--dry-run]

The attachment uses Zotero's portable ``attachments:`` scheme, which resolves
against each machine's Linked Attachment Base Directory (Zotero -> Preferences ->
Advanced -> Files and Folders).  The PDF must already be in that folder under
``filename``; this script does not copy or upload it.

Configuration (either source works; TOML wins per key when present):
    ZOTERO_LIBRARY_ID / ZOTERO_API_KEY
        Usually set in <repo>/.env — the bare-host source of truth.
    ZOTERO_CONFIG_PATH
        Path to a Zotero config TOML.  Default: ~/.config/zot/config.toml.
        Provided by the myopenclaw hermes container.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11 — TOML becomes optional, env still works
    tomllib = None

from pyzotero import zotero as zt

# Only these two keys are read from .env; everything else is left untouched.
_CREDENTIAL_KEYS = ("ZOTERO_LIBRARY_ID", "ZOTERO_API_KEY")
_DEFAULT_CONFIG_PATH = "~/.config/zot/config.toml"


def _parse_env_text(content: str) -> dict[str, str]:
    """Extract the credential keys from .env-style text.

    Ignores blanks and comments, and strips one layer of surrounding quotes.
    Everything other than ``_CREDENTIAL_KEYS`` is discarded, so this can never
    leak unrelated .env contents into the environment.
    """
    found: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name in _CREDENTIAL_KEYS:
            found[name] = value.strip().strip('"').strip("'")
    return found


def _load_dotenv_fallback() -> None:
    """Populate ZOTERO_* from <repo>/.env when they are not already set.

    A minimal parser on purpose (see module docstring).  Existing environment
    variables always win, and any failure is ignored so a missing or malformed
    .env can never break the container path, which uses the TOML instead.
    """
    env_file = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_file.exists():
        return
    try:
        content = env_file.read_text(encoding="utf-8")
    except OSError:
        return
    for name, value in _parse_env_text(content).items():
        os.environ.setdefault(name, value)


def _resolve_credentials() -> tuple[str, str]:
    """Return ``(library_id, api_key)`` — env first, then per-key TOML override.

    Mirrors ``paper_to_zotero._resolve_zotero_credentials()`` exactly: an absent
    or unparsable TOML, or a TOML missing one of the keys, silently falls back to
    the environment value for that key.
    """
    _load_dotenv_fallback()
    lib_id = os.environ.get("ZOTERO_LIBRARY_ID", "")
    api_key = os.environ.get("ZOTERO_API_KEY", "")

    config_path = os.environ.get("ZOTERO_CONFIG_PATH", os.path.expanduser(_DEFAULT_CONFIG_PATH))
    if tomllib is not None and os.path.exists(config_path):
        try:
            with open(config_path, "rb") as fh:
                cfg = tomllib.load(fh)
        except Exception:
            cfg = None
        if cfg:
            zot_cfg = cfg.get("zotero", {}) or {}
            lib_id = zot_cfg.get("library_id", "") or lib_id
            api_key = zot_cfg.get("api_key", "") or api_key

    return lib_id, api_key


def _find_existing_attachment(z, parent_key: str, attachment_path: str) -> str | None:
    """Return the key of an existing child attachment with this path, else None.

    Guards against double-clicking the command and creating two pointers to the
    same file.  A failed lookup returns None so it can never block a first link.
    """
    try:
        children = z.children(parent_key)
    except Exception:
        return None
    for child in children:
        data = child.get("data", {}) or {}
        if data.get("itemType") != "attachment":
            continue
        if (data.get("path") or "") == attachment_path:
            return child.get("key") or ""
    return None


def main():
    dry_run = False
    if len(sys.argv) > 1 and sys.argv[1] == "--dry-run":
        dry_run = True
        sys.argv.pop(1)

    if len(sys.argv) < 3:
        print("Usage: zot-link-gdrive [--dry-run] <zotero_key> <filename>",
              file=sys.stderr)
        sys.exit(2)

    key = sys.argv[1]
    filename = sys.argv[2]

    # Use Zotero's attachments: scheme — resolves relative to each
    # computer's Linked Attachment Base Directory (set in Zotero prefs).
    attachment_path = f"attachments:{filename}"

    if dry_run:
        print(f"[dry-run] Would link: {attachment_path} -> Zotero item {key} "
              f"(filename: {filename})")
        sys.exit(0)

    lib_id, api_key = _resolve_credentials()
    if not lib_id or not api_key:
        print(
            "Error: Zotero API credentials not found.\n"
            "  Set ZOTERO_API_KEY and ZOTERO_LIBRARY_ID in <repo>/.env (bare host),\n"
            "  or provide a config TOML via ZOTERO_CONFIG_PATH (container).\n"
            "  Get an API key at https://www.zotero.org/settings/keys",
            file=sys.stderr,
        )
        sys.exit(3)

    z = zt.Zotero(lib_id, "user", api_key)

    existing = _find_existing_attachment(z, key, attachment_path)
    if existing:
        print(f"Already linked: {attachment_path} -> Zotero item {key} "
              f"(attachment: {existing}); nothing to do")
        sys.exit(0)

    tmpl = z.item_template("attachment", "linked_file")
    tmpl["path"] = attachment_path
    tmpl["title"] = filename
    tmpl["parentItem"] = key
    tmpl["contentType"] = "application/pdf"
    resp = z.create_items([tmpl])
    created = resp.get("success", {})
    if created:
        attach_key = list(created.values())[0]
        print(f"Linked: {attachment_path} -> Zotero item {key} "
              f"(attachment: {attach_key})")
    else:
        failed = resp.get("failed", {})
        err_msg = failed.get("0", {}).get("message", str(resp))
        print(f"Error: {err_msg}", file=sys.stderr)
        sys.exit(5)


if __name__ == "__main__":
    main()
