"""Sentence identifiers: the program owns the quoted text, the model picks it.

Hand-copying原文 is the dominant failure of a card run. In 2155 checked quotes,
11% did not appear in ``paper.md`` verbatim — the model retyped a word, merged
two sentences, marked the wrong page, or copied a reference entry — and a single
bad quote rejects the whole answer (82% of real answers were rejected). #65.

The fix is structural: every prose sentence and table row of the converted paper
gets an identifier, the model answers with identifiers only, and the program
fills in the text. A quote can then no longer differ from the document, and the
page comes from the identifier rather than from the model's claim.

This module owns the numbering, the identifier grammar and the expansion. It
never calls a model and never rewrites the conversion.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# ``P3-S004``: page 3, prose sentence 4. ``P7-T012``: page 7, table row 12.
SENTENCE_ID = re.compile(r"P(\d+)-(S|T)(\d{3})\Z")
_ANNOTATED = re.compile(r"⟨(P\d+-[ST]\d{3})⟩\s*")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_CAPTION = re.compile(r"^\s*(?:\*\*)?\s*(?:Fig(?:ure)?\.?|Table|图|表)\s*\d", re.IGNORECASE)
_REFERENCES = re.compile(r"^\s*#*\s*(?:References|Bibliography|参考文献)\s*$", re.MULTILINE | re.IGNORECASE)
_PAGE_MARKER = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
_SENTENCE = re.compile(r"[^.!?。！？]+[.!?。！？]")
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEPARATOR = re.compile(r"^\|?[\s:|-]+\|?$")

KIND_PROSE = "prose"
KIND_TABLE = "table"
MIN_PROSE_CHARS = 40
MIN_TABLE_CHARS = 12


def strip_ids(text: str) -> str:
    """Remove ``⟨P1-S002⟩`` markers from a string that may still carry them."""

    return _ANNOTATED.sub("", text) if isinstance(text, str) else text


def _add(index: dict[str, Any], counters: dict[tuple[int, str], int], page: int, kind: str, text: str) -> str:
    key = (page, kind)
    counters[key] = counters.get(key, 0) + 1
    token = "S" if kind == KIND_PROSE else "T"
    identifier = f"P{page}-{token}{counters[key]:03d}"
    index[identifier] = {"id": identifier, "page": page, "kind": kind, "text": text}
    return identifier


def annotate(markdown: str) -> tuple[str, dict[str, Any]]:
    """Return ``(annotated markdown, index)``.

    Prose sentences and table rows are numbered; headings, figure captions,
    image embeds and the reference section are neither numbered nor kept in the
    annotated text, because they cannot be quoted as prose evidence and they
    interrupt a quote that crosses them.
    """

    references = _REFERENCES.search(markdown)
    body = markdown[: references.start()] if references else markdown
    index: dict[str, Any] = {}
    counters: dict[tuple[int, str], int] = {}
    out: list[str] = []
    page = 1
    lines = body.splitlines(keepends=True)
    for position, line in enumerate(lines):
        marker = _PAGE_MARKER.search(line)
        if marker:
            page = int(marker.group(1))
            out.append(line)
            continue
        stripped = line.strip()
        if not stripped or _HEADING.match(line) or _CAPTION.match(stripped):
            out.append(line if stripped else "\n")
            continue
        row = _TABLE_ROW.match(stripped)
        if row:
            # A header and the separator under it are table furniture, not
            # evidence: numbering them hands the model a "quote" that says
            # nothing, and the citation looks real.
            following = lines[position + 1].strip() if position + 1 < len(lines) else ""
            if _TABLE_SEPARATOR.match(stripped) or _TABLE_SEPARATOR.match(following):
                continue
            cells = " · ".join(cell.strip() for cell in row.group(1).split("|") if cell.strip())
            if len(cells) >= MIN_TABLE_CHARS and not set(cells) <= set("-: "):
                identifier = _add(index, counters, page, KIND_TABLE, cells)
                out.append(f"⟨{identifier}⟩ {cells}\n")
            continue
        cleaned = _IMAGE.sub(" ", line)
        rebuilt: list[str] = []
        for sentence in _SENTENCE.findall(cleaned):
            text = sentence.strip()
            if len(text) < MIN_PROSE_CHARS:
                rebuilt.append(sentence)
                continue
            identifier = _add(index, counters, page, KIND_PROSE, text)
            rebuilt.append(f"⟨{identifier}⟩ {text} ")
        out.append("".join(rebuilt) if rebuilt else cleaned)
    return "".join(out), index


def expand(locations: Any, index: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Fill ``quote``/``anchor``/``pdf_page`` from identifiers.

    Returns ``(locations, problems)``. A location without identifiers is returned
    untouched, so an older answer that still quotes text keeps working; a location
    whose identifiers do not exist is reported, never guessed.
    """

    if not isinstance(locations, list):
        return locations, []
    expanded: list[dict] = []
    problems: list[dict] = []
    for position, location in enumerate(locations):
        if not isinstance(location, dict):
            expanded.append(location)
            continue
        identifiers = location.get("sentence_ids")
        if not identifiers:
            expanded.append({key: value for key, value in location.items() if key != "sentence_ids"})
            continue
        if not isinstance(identifiers, list) or not identifiers or not all(
                isinstance(item, str) for item in identifiers):
            problems.append({"code": "CARD_SENTENCE_IDS_INVALID", "path": f"source_locations[{position}].sentence_ids",
                             "message": "句子编号必须是非空字符串数组",
                             "expected": "形如 P3-S004", "actual": str(identifiers)[:80]})
            continue
        unknown = [item for item in identifiers if item not in index]
        if unknown:
            problems.append({"code": "CARD_SENTENCE_ID_UNKNOWN", "path": f"source_locations[{position}].sentence_ids",
                             "message": "引用了正文中不存在的句子编号",
                             "expected": "、".join(sorted(index)[:3]) + " 这类真实编号",
                             "actual": "、".join(unknown[:4])})
            continue
        pages = sorted({index[item]["page"] for item in identifiers})
        if len(pages) > 1:
            problems.append({"code": "CARD_SENTENCE_IDS_CROSS_PAGE",
                             "path": f"source_locations[{position}].sentence_ids",
                             "message": "同一处证据的句子编号跨了页；请拆成两条",
                             "expected": "同一页的编号", "actual": "、".join(identifiers[:4])})
            continue
        quote = " ".join(index[item]["text"] for item in identifiers)
        kinds = {index[item]["kind"] for item in identifiers}
        merged = {**location, "quote": quote, "anchor": f"P{pages[0]}", "pdf_page": pages[0],
                  "section": location.get("section") if location.get("section") else None}
        if "table" in kinds and not merged.get("table"):
            merged["table"] = f"P{pages[0]} 表格行"
        merged.pop("sentence_ids", None)
        expanded.append(merged)
    return expanded, problems


def identifiers_of(location: Any) -> list[str]:
    """The identifiers an answer used, for provenance."""

    if isinstance(location, dict) and isinstance(location.get("sentence_ids"), Iterable):
        return [item for item in location["sentence_ids"] if isinstance(item, str)]
    return []


def citable_pages(markdown: str) -> frozenset[int]:
    """Pages that hold at least one citable sentence or table row.

    A page of equations or a full-page figure carries text but nothing that can
    be quoted as evidence, so it must not count towards coverage either: a card
    cannot reach a target it has no means to hit (#65).
    """

    _, index = annotate(markdown)
    return frozenset(meta["page"] for meta in index.values())


def inventory(index: dict[str, Any], page_count: int) -> str:
    """The identifiers that actually exist, page by page, for the prompt.

    A model that has to guess invents ``P3-S001`` on a page that is one full-page
    figure, and the run dies on a mistake the program could have prevented by
    saying which pages can be cited at all (#65).
    """

    by_page: dict[int, dict[str, int]] = {}
    for meta in index.values():
        counts = by_page.setdefault(meta["page"], {KIND_PROSE: 0, KIND_TABLE: 0})
        counts[meta["kind"]] += 1
    lines: list[str] = []
    for page in range(1, max(page_count, 1) + 1):
        counts = by_page.get(page)
        if not counts or not any(counts.values()):
            lines.append(
                f"- 第 {page} 页：没有可引用的句子（整页图或无正文）；提到这里的图请写（图 N）"
            )
            continue
        parts: list[str] = []
        for kind, token, noun in ((KIND_PROSE, "S", "句"), (KIND_TABLE, "T", "行表格")):
            count = counts.get(kind, 0)
            if not count:
                continue
            first = f"P{page}-{token}001"
            last = f"P{page}-{token}{count:03d}"
            where = first if first == last else f"{first}–{last}"
            parts.append(f"{where}（共 {count} {noun}）")
        lines.append(f"- 第 {page} 页：" + "；".join(parts))
    return "\n".join(lines)
