"""Development tool: measure one PDF→Markdown conversion.

This is not a test. It runs the real converter on a real file and prints the
numbers the hardening work is judged by:

* page / figure / table counts and the detected ``Figure N`` / ``Table N``
  labels;
* word-gap violations (runs of more than 30 Latin letters, i.e. words that lost
  their spaces);
* whitespace coverage per page against ``page.get_text("text")``, both against
  the raw reference and against a reference with running headers, running
  footers and publisher download stamps removed (those are meant to disappear);
* running-matter repeats found in the source PDF;
* the Markdown hash, and optionally a second conversion to prove determinism.

Usage::

    uv run python scripts/eval_conversion.py <pdf> [--out DIR] [--repeat]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

import pymupdf

from hydrolitagent.cards.adapters.pdf.anchors import (
    Box,
    is_download_stamp,
    normalize_margin_text,
    repeated_margin_texts,
)
from hydrolitagent.cards.adapters.pdf.pymupdf_converter import PymupdfConverter
from hydrolitagent.cards.ports.paper import ConversionOptions, ConversionRequest

LONG_TOKEN = re.compile(r"[A-Za-z]{31,}")
FIGURE_LABEL = re.compile(r"(?:^|\n)\s*Figure\s+(\d+)\s*[.:]", re.IGNORECASE)
TABLE_LABEL = re.compile(r"(?:^|\n)\s*Table\s+(\d+)\s*[.:]", re.IGNORECASE)
TABLE_SEPARATOR = re.compile(r"^\|(?: --- \|)+$")
TABLE_IMAGE = re.compile(r"!\[Table\s+(\d+)\]")
COVERAGE_TARGET = 0.85


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _whitespace(text: str) -> int:
    return sum(1 for character in text if character.isspace())


def _collapsed_whitespace(text: str) -> int:
    return len(re.findall(r"\s+", text))


def _page_lines(document: pymupdf.Document) -> list[list[tuple[str, Any]]]:
    lines: list[list[tuple[str, Any]]] = []
    for index in range(document.page_count):
        data = document.load_page(index).get_text("dict")
        page: list[tuple[str, Any]] = []
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = "".join(span.get("text", "") for span in line.get("spans", []))
                if not text.strip():
                    continue
                page.append((text, line["bbox"]))
        lines.append(page)
    return lines


def _body_reference(document: pymupdf.Document) -> list[str]:
    """Reference text with the matter the converter is required to remove."""

    raw = _page_lines(document)
    heights = [document.load_page(i).rect.height for i in range(document.page_count)]
    typed = [[(text, Box(*bbox)) for text, bbox in page] for page in raw]
    running = set(repeated_margin_texts(typed, heights))
    body: list[str] = []
    for page in raw:
        kept = [
            text
            for text, _bbox in page
            if normalize_margin_text(text) not in running and not is_download_stamp(text)
        ]
        body.append("\n".join(kept))
    return body


def _coverage(markdown: str, anchors: Iterable[Any], reference: list[str], counter) -> dict[str, Any]:
    per_page: dict[str, float | None] = {}
    for anchor in anchors:
        slice_text = markdown[anchor.char_start : anchor.char_end]
        expected = counter(reference[anchor.page - 1])
        per_page[str(anchor.page)] = round(counter(slice_text) / expected, 3) if expected else None
    values = [value for value in per_page.values() if value is not None]
    below = sorted(page for page, value in per_page.items() if value is not None and value < COVERAGE_TARGET)
    return {
        "per_page": per_page,
        "min": min(values) if values else None,
        "overall": round(
            counter(markdown) / counter("\n".join(reference)), 3
        )
        if counter("\n".join(reference))
        else None,
        "pages_below_target": below,
    }


def evaluate(pdf: Path, output_dir: Path, *, repeat: bool = False) -> dict[str, Any]:
    options = ConversionOptions()
    converter = PymupdfConverter()
    request = ConversionRequest(
        pdf_path=pdf,
        pdf_sha256=_sha256(pdf),
        size_bytes=pdf.stat().st_size,
        output_dir=output_dir,
        options=options,
    )
    prepared, error = converter.convert(request)
    if error is not None or prepared is None:
        payload = {"pdf": pdf.name, "error": error.code if error else "UNKNOWN"}
        if error is not None:
            payload["message"] = error.message
        return payload

    markdown = prepared.markdown_path.read_text(encoding="utf-8")
    document = pymupdf.open(str(pdf))
    try:
        raw_reference = [
            document.load_page(index).get_text("text")
            for index in range(document.page_count)
        ]
        body_reference = _body_reference(document)
        margin_lines = _page_lines(document)
        heights = [document.load_page(i).rect.height for i in range(document.page_count)]
        typed = [[(text, Box(*bbox)) for text, bbox in page] for page in margin_lines]
        running = repeated_margin_texts(typed, heights)
        repeat_counts: dict[str, int] = {}
        for key in running:
            repeat_counts[key] = sum(
                1
                for page in typed
                if any(normalize_margin_text(text) == key for text, _box in page)
            )
    finally:
        document.close()

    long_tokens = LONG_TOKEN.findall(markdown)
    tables_markdown = sum(1 for line in markdown.splitlines() if TABLE_SEPARATOR.match(line))
    table_images = sorted({int(number) for number in TABLE_IMAGE.findall(markdown)})
    table_numbers = sorted({int(number) for number in TABLE_LABEL.findall(markdown)})
    figure_numbers = sorted({int(number) for number in FIGURE_LABEL.findall(markdown)})

    result: dict[str, Any] = {
        "pdf": pdf.name,
        "output_dir": str(output_dir),
        "converter": {
            "id": prepared.converter_id,
            "version": prepared.converter_version,
        },
        "pages": prepared.source.page_count,
        "figures": len(prepared.figures),
        "figure_ids": [figure.figure_id for figure in prepared.figures],
        "figure_numbers": figure_numbers,
        "tables": {
            "markdown": tables_markdown,
            "images": table_images,
            "captions": table_numbers,
        },
        "canaries": markdown.count("<!-- reading-canary: "),
        "warnings": list(prepared.warnings),
        "word_gap_violations": {
            "count": len(long_tokens),
            "samples": sorted(set(long_tokens))[:10],
        },
        "whitespace": {
            "raw": _coverage(markdown, prepared.page_anchors, raw_reference, _whitespace),
            "body": _coverage(markdown, prepared.page_anchors, body_reference, _whitespace),
            "collapsed_body": _coverage(
                markdown, prepared.page_anchors, body_reference, _collapsed_whitespace
            ),
        },
        "running_matter": {
            "texts": list(running),
            "max_repeat_pages": max(repeat_counts.values()) if repeat_counts else 0,
        },
        "markdown_sha256": prepared.markdown_sha256,
        "markdown_bytes": len(markdown.encode("utf-8")),
        "water_resources_research_occurrences": markdown.count("Water Resources Research"),
    }

    if repeat:
        second_dir = Path(tempfile.mkdtemp(prefix="conversion-eval-repeat-"))
        second, second_error = converter.convert(
            ConversionRequest(
                pdf_path=pdf,
                pdf_sha256=request.pdf_sha256,
                size_bytes=request.size_bytes,
                output_dir=second_dir,
                options=options,
            )
        )
        result["repeat"] = {
            "sha256": second.markdown_sha256 if second else None,
            "error": second_error.code if second_error else None,
            "identical": bool(second and second.markdown_sha256 == prepared.markdown_sha256),
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="PDF file to convert")
    parser.add_argument("--out", type=Path, default=None, help="output directory")
    parser.add_argument(
        "--repeat",
        action="store_true",
        help="convert a second time and compare the Markdown hash",
    )
    args = parser.parse_args(argv)

    if not args.pdf.is_file():
        print(f"找不到 PDF：{args.pdf}", file=sys.stderr)
        return 2
    output_dir = args.out or Path(tempfile.mkdtemp(prefix="conversion-eval-"))
    output_dir.mkdir(parents=True, exist_ok=True)

    report = evaluate(args.pdf, output_dir, repeat=args.repeat)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if "error" not in report else 1


if __name__ == "__main__":
    raise SystemExit(main())
