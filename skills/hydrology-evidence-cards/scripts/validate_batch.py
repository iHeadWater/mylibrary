#!/usr/bin/env python3
"""Validate a batch of source cards and reject cross-card template repetition."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import re

from validate_card import parse_frontmatter, validate_text, visible_body


def normalized_units(body: str) -> tuple[list[str], list[str]]:
    paragraphs: list[str] = []
    sentences: list[str] = []
    for raw in re.split(r"\n\s*\n", body):
        value = re.sub(r"\s+", "", raw)
        if len(value) >= 100 and not value.startswith(("|", "-**", "- **")):
            paragraphs.append(value)
    for raw in re.split(r"[。！？\n]+", body):
        value = re.sub(r"\s+", "", raw)
        if len(value) >= 45:
            sentences.append(value)
    return paragraphs, sentences


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="Directory containing evidence-card Markdown files")
    parser.add_argument("--mode", choices=["draft", "final"], default="draft")
    args = parser.parse_args()

    root = Path(args.root)
    cards: list[tuple[Path, str]] = []
    failures: list[tuple[Path, list[str]]] = []
    paragraph_owners: dict[str, list[Path]] = defaultdict(list)
    sentence_owners: dict[str, list[Path]] = defaultdict(list)

    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8-sig")
        meta = parse_frontmatter(text)
        if meta.get("card_schema") != "evidence-card-v1.2" or meta.get("card_type") != "source_evidence":
            continue
        cards.append((path, text))
        errors, _, _ = validate_text(text, args.mode)
        if errors:
            failures.append((path, errors))
        paragraphs, sentences = normalized_units(visible_body(text))
        for value in paragraphs:
            paragraph_owners[value].append(path)
        for value in sentences:
            sentence_owners[value].append(path)

    paragraph_duplicates = {
        value: owners for value, owners in paragraph_owners.items()
        if len({str(path) for path in owners}) > 1
    }
    sentence_duplicates = {
        value: owners for value, owners in sentence_owners.items()
        if len({str(path) for path in owners}) > 1
    }

    for path, errors in failures:
        print(path)
        for error in errors:
            print(f"  ERROR: {error}")
    for label, groups in (("paragraph", paragraph_duplicates), ("long sentence", sentence_duplicates)):
        for value, owners in groups.items():
            print(f"DUPLICATE {label}: {value}")
            print("  " + ", ".join(sorted({str(path) for path in owners})))

    print(
        f"cards={len(cards)} failures={len(failures)} "
        f"duplicate_paragraphs={len(paragraph_duplicates)} "
        f"duplicate_long_sentences={len(sentence_duplicates)}"
    )
    if failures or paragraph_duplicates or sentence_duplicates:
        raise SystemExit(1)
    print("PASS: batch cards satisfy individual rules and cross-card repetition checks")


if __name__ == "__main__":
    main()
