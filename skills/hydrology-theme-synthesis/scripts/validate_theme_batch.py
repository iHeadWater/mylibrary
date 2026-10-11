#!/usr/bin/env python3
"""Check deep theme dossiers for cross-theme prose duplication."""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

from validate_theme import narrative_region, normalize_prose, parse_frontmatter, strip_markdown_for_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("theme_dir")
    args = parser.parse_args()

    root = Path(args.theme_dir)
    paths = sorted(p for p in root.glob("*.md") if p.name.lower() != "readme.md")
    if not paths:
        raise SystemExit("No theme Markdown files found")

    errors: list[str] = []
    paragraphs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    sentences: dict[str, list[tuple[str, int]]] = defaultdict(list)
    counts: list[tuple[str, int, str]] = []

    for path in paths:
        text = path.read_text(encoding="utf-8-sig")
        meta = parse_frontmatter(text)
        region, marker_errors = narrative_region(text)
        if marker_errors:
            errors.extend(f"{path.name}: {item}" for item in marker_errors)
            continue
        clean, paras, sents = strip_markdown_for_count(region)
        count = len(re.sub(r"\s+", "", clean))
        counts.append((path.name, count, str(meta.get("narrative_status") or "")))
        for idx, paragraph in enumerate(paras, 1):
            token = normalize_prose(paragraph)
            if len(token) >= 120:
                paragraphs[token].append((path.name, idx))
        for idx, sentence in enumerate(sents, 1):
            token = normalize_prose(sentence)
            if len(token) >= 100:
                sentences[token].append((path.name, idx))

    duplicate_paragraphs = [places for places in paragraphs.values() if len({p[0] for p in places}) > 1]
    duplicate_sentences = [places for places in sentences.values() if len({p[0] for p in places}) > 1]
    for places in duplicate_paragraphs:
        errors.append("TG14 cross-theme duplicate paragraph: " + ", ".join(f"{name}#{idx}" for name, idx in places))
    for places in duplicate_sentences:
        errors.append("TG14 cross-theme duplicate long sentence: " + ", ".join(f"{name}#{idx}" for name, idx in places))

    for name, count, status in counts:
        print(f"{name}\tvisible_scientific_chars={count}\tstatus={status}")
    print(f"themes={len(paths)} duplicate_paragraphs={len(duplicate_paragraphs)} duplicate_long_sentences={len(duplicate_sentences)}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        raise SystemExit(1)
    print("PASS: TG14 cross-theme visible prose duplication check completed")


if __name__ == "__main__":
    main()
