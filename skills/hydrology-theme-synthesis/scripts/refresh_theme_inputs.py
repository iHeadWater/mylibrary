#!/usr/bin/env python3
"""Refresh an existing theme's evidence-card snapshot without replacing its prose."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from validate_theme import parse_frontmatter

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "build_theme.py"
REFRESH_KEYS = {
    "as_of_date", "input_card_ids", "included_claim_ids", "context_only_claim_ids",
    "excluded_claim_ids", "independence_group_ids", "version_family_ids",
    "source_snapshot_hash", "last_evidence_refresh",
}


def frontmatter_text(text: str) -> str:
    match = re.match(r"(?s)^---\s*\n(.*?)\n---\s*\n", text)
    if not match:
        raise ValueError("theme has no valid frontmatter")
    return match.group(1)


def replace_frontmatter_values(original: str, generated: str) -> str:
    old_body = frontmatter_text(original)
    new_body = frontmatter_text(generated)
    new_lines = {line.split(":", 1)[0]: line for line in new_body.splitlines() if ":" in line and not line.startswith((" ", "\t"))}
    output: list[str] = []
    seen: set[str] = set()
    for line in old_body.splitlines():
        key = line.split(":", 1)[0] if ":" in line and not line.startswith((" ", "\t")) else ""
        if key in REFRESH_KEYS and key in new_lines:
            output.append(new_lines[key])
            seen.add(key)
        else:
            output.append(line)
    for key in REFRESH_KEYS - seen:
        if key in new_lines:
            output.append(new_lines[key])
    start_end = re.match(r"(?s)^(---\s*\n).*?(\n---\s*\n)", original)
    assert start_end
    return start_end.group(1) + "\n".join(output) + start_end.group(2) + original[start_end.end():]


def source_manifest_block(text: str) -> str:
    match = re.search(r"(?ms)^~~~source-manifest-json\s*\n.*?^~~~\s*$", text)
    if not match:
        raise ValueError("source-manifest-json block missing")
    return match.group(0)


def card_index(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in root.rglob("*.md"):
        try:
            meta = parse_frontmatter(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError):
            continue
        if meta.get("card_type") != "source_evidence":
            continue
        card_id = str(meta.get("card_id") or "")
        if not re.fullmatch(r"EC-\d{8}-\d{3}", card_id):
            continue
        if card_id in result:
            raise ValueError(f"duplicate source card id: {card_id}")
        result[card_id] = path
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("theme")
    parser.add_argument("--index-root", required=True)
    parser.add_argument("--as-of-date", required=True)
    args = parser.parse_args()

    theme_path = Path(args.theme)
    original = theme_path.read_text(encoding="utf-8-sig")
    meta = parse_frontmatter(original)
    ids = meta.get("input_card_ids")
    if not isinstance(ids, list) or not ids:
        raise SystemExit("theme input_card_ids is missing or empty")
    index = card_index(Path(args.index_root))
    missing = [str(card_id) for card_id in ids if str(card_id) not in index]
    if missing:
        raise SystemExit("missing source cards: " + ", ".join(missing))

    command = [
        sys.executable, str(BUILD), "--theme-ref", str(meta.get("theme_ref") or ""),
        "--title", str(meta.get("title") or ""), "--intended-use", str(meta.get("intended_use") or ""),
        "--as-of-date", args.as_of_date, "--include-all-verified",
    ]
    for card_id in ids:
        command.extend(["--card", str(index[str(card_id)])])

    with tempfile.TemporaryDirectory() as temp_dir:
        generated_path = Path(temp_dir) / "theme.md"
        command.extend(["--output", str(generated_path)])
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
        generated = generated_path.read_text(encoding="utf-8-sig")

    refreshed = replace_frontmatter_values(original, generated)
    refreshed = re.sub(
        r"(?ms)^~~~source-manifest-json\s*\n.*?^~~~\s*$",
        lambda _match: source_manifest_block(generated),
        refreshed,
        count=1,
    )
    theme_path.write_text(refreshed.rstrip() + "\n", encoding="utf-8")
    new_meta = parse_frontmatter(refreshed)
    print(theme_path)
    print("input_cards=" + str(len(ids)))
    print("included_claims=" + str(len(new_meta.get("included_claim_ids") or [])))
    print("snapshot=" + str(new_meta.get("source_snapshot_hash") or ""))


if __name__ == "__main__":
    main()
