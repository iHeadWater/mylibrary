from __future__ import annotations

import re
from datetime import date, timedelta

from .config import AppConfig, RecordTypeConfig
from .models import Record, SheetData, SourceRef


def joined(row: list[str]) -> str:
    return " ".join(str(x).strip() for x in row if str(x).strip())


def cell(row: list[str], index: int) -> str:
    return row[index].strip() if 0 <= index < len(row) and row[index] else ""


def first_cell(row: list[str], indexes: list[int], min_len: int = 1) -> str:
    for index in indexes:
        value = cell(row, index)
        if len(value) >= min_len:
            return value
    return ""


def collect_cells(row: list[str], indexes: list[int]) -> list[str]:
    values: list[str] = []
    for index in indexes:
        value = cell(row, index)
        if value and value not in values:
            values.append(value)
    return values


def excel_serial_to_date(value: int) -> date | None:
    if 30000 <= value <= 60000:
        return date(1899, 12, 30) + timedelta(days=value)
    return None


def dates_in_text(text: str) -> list[date]:
    dates: list[date] = []
    for match in re.finditer(r"(20\d{2})[-./年](\d{1,2})(?:[-./月](\d{1,2}))?", text):
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3) or 1)
        try:
            dates.append(date(year, month, day))
        except ValueError:
            pass
    for match in re.finditer(r"\b(20\d{2})\b", text):
        year = int(match.group(1))
        try:
            dates.append(date(year, 1, 1))
        except ValueError:
            pass
    for match in re.finditer(r"\b(4[3-7]\d{3})\b", text):
        converted = excel_serial_to_date(int(match.group(1)))
        if converted:
            dates.append(converted)
    return sorted(set(dates))


def urls_in_text(text: str) -> list[str]:
    return re.findall(r"https?://[^\s，,；;]+", text)


DOI_PATTERN = r"10\.\d{4,9}/[-._;()/:A-Z0-9]+"
PATENT_PATTERNS = [
    r"ZL\s?\d{4}\s?\d?\s?\d{6,}\.?\w*",
    r"CN\d{9,}(?:\.\d+)?[A-Z]?",
]
PROJECT_PATTERNS = [
    r"20\d{2}[A-Z]{2,}\d{4,}(?:[-\w]+)?",
    r"DUT\d{2}[A-Z]+\d+",
    r"[A-Z]\d{7,}",
    r"\d{4}-[A-Z]{1,4}-\d{3,}",
    r"\b[1-9]\d{6,7}\b",
]


def clean_identifier(value: str) -> str:
    return value.strip().strip(".,;；，。")


def identifier_patterns(kind: str) -> list[str]:
    if kind == "paper":
        return [DOI_PATTERN]
    if kind == "patent":
        return PATENT_PATTERNS
    if kind == "project":
        return PROJECT_PATTERNS
    return [DOI_PATTERN, *PATENT_PATTERNS, *PROJECT_PATTERNS]


def identifier_from_text(text: str, configured: list[str], kind: str) -> str:
    patterns = identifier_patterns(kind)
    for value in configured:
        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if match:
                return clean_identifier(match.group(0))
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_identifier(match.group(0))
    return ""


def is_headerish(text: str) -> bool:
    header_terms = ["序号", "论文名称", "项目名称", "专利名称", "发表时间", "完成人", "作者"]
    if not text:
        return True
    return sum(1 for term in header_terms if term in text) >= 2


def record_type_for_sheet(sheet_name: str, config: AppConfig) -> RecordTypeConfig | None:
    for rule in config.record_types.values():
        if not rule.enabled:
            continue
        if any(keyword in sheet_name for keyword in rule.exclude_sheet_keywords):
            continue
        if any(keyword in sheet_name for keyword in rule.sheet_keywords):
            return rule
    return None


def status_for(text: str, sheet_name: str, rule: RecordTypeConfig) -> str:
    haystack = f"{sheet_name} {text}" if rule.time.status_from_sheet else text
    hits = [term for term in rule.time.status_terms if term in haystack]
    if rule.kind == "paper" and "已发表" in sheet_name and "已发表" not in hits:
        hits.insert(0, "已发表")
    if rule.kind == "paper" and "在审" in sheet_name and "在审" not in hits:
        hits.insert(0, "在审")
    if rule.kind == "patent" and "授权" in sheet_name and "授权" not in hits:
        hits.insert(0, "授权")
    if rule.kind == "patent" and "受理" in sheet_name and "受理" not in hits:
        hits.insert(0, "受理")
    return "、".join(dict.fromkeys(hits))


def person_aliases(config: AppConfig) -> set[str]:
    aliases: set[str] = set()
    for canonical, values in config.people_allowlist.items():
        aliases.add(canonical)
        aliases.update(values)
    return {alias.strip() for alias in aliases if alias.strip()}


def title_for(row: list[str], text: str, rule: RecordTypeConfig, config: AppConfig) -> str:
    reject = person_aliases(config)
    for index in rule.title_columns:
        configured = cell(row, index)
        if looks_like_title(configured, reject):
            return configured
    candidates = [
        value.strip()
        for value in row
        if looks_like_title(value, reject)
    ]
    return max(candidates, key=len) if candidates else text[:80]


def looks_like_title(value: str, reject_values: set[str] | None = None) -> bool:
    value = value.strip()
    if len(value) < 4:
        return False
    if reject_values and value in reject_values:
        return False
    if value in {"在研", "结题", "已结题", "执行", "学校", "国家自然科学基金"}:
        return False
    if re.fullmatch(r"[\d\s./:-]+", value):
        return False
    if re.fullmatch(r"[A-Z]?\d{6,}", value):
        return False
    if re.fullmatch(r"20\d{2}[A-Z]{2,}\d+(?:-\d+)?", value):
        return False
    return True


def normalize_records(sheets: list[SheetData], config: AppConfig) -> list[Record]:
    records: list[Record] = []
    for sheet in sheets:
        rule = record_type_for_sheet(sheet.sheet, config)
        if rule is None:
            continue
        for idx, row in enumerate(sheet.rows, start=1):
            text = joined(row)
            if idx <= 1 or len(text) < 8 or is_headerish(text):
                continue
            title = title_for(row, text, rule, config)
            summary = first_cell(row, rule.summary_columns, min_len=8)
            people = collect_cells(row, rule.people_columns)
            venue = " / ".join(collect_cells(row, rule.venue_columns))
            identifier = identifier_from_text(text, collect_cells(row, rule.identifier_columns), rule.kind)
            dates = dates_in_text(text)
            records.append(
                Record(
                    kind=rule.kind,
                    title=title,
                    people=people,
                    matched_people=[],
                    dates=dates,
                    date=dates[-1] if dates else None,
                    status=status_for(text, sheet.sheet, rule),
                    venue_or_type=venue,
                    identifier=identifier,
                    summary=summary,
                    track="待判断",
                    source=SourceRef(sheet.workbook, sheet.sheet, idx),
                    evidence_links=urls_in_text(text),
                    raw_text=text,
                )
            )
    return records
