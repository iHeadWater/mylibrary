"""人员名单读取。

支持 CSV（UTF-8-sig / GB18030 兜底）与 TOML；表头允许中英文别名。
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import normalize_author_id
from .errors import RosterError

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
ALIAS_SPLIT_RE = re.compile(r"[|;；,，、]+")

HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("姓名", "name", "中文名"),
    "institute": ("所属机构", "机构", "所属研究所", "研究所", "institute", "部门", "单位"),
    "aliases": ("英文名/别名", "英文名", "别名", "aliases", "alias", "name_en"),
    "orcid": ("orcid", "orcid id", "orcidid"),
    "openalex_ids": ("openalexid", "openalex_id", "openalex id", "openalex"),
    "self_check": ("自查结论", "自查是否存在问题", "self_check"),
    "self_check_note": ("补充说明", "如自查涉及问题请补充", "note"),
}


@dataclass(frozen=True)
class Roster:
    people: tuple["RosterPerson", ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RosterPerson:
    index: int
    name: str
    institute: str = ""
    aliases: tuple[str, ...] = ()
    orcid: str = ""
    openalex_ids: tuple[str, ...] = ()
    self_check: str = ""
    self_check_note: str = ""


def normalize_orcid(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    text = text.replace("https://orcid.org/", "").replace("http://orcid.org/", "").strip()
    text = text.rstrip("/")
    if re.fullmatch(r"\d{16}", text):
        text = "-".join(text[i : i + 4] for i in range(0, 16, 4))
    if not ORCID_RE.match(text):
        raise RosterError(f"ORCID 非法：{value!r}（应形如 0000-0002-1825-0097）")
    return text


def _split_values(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in ALIAS_SPLIT_RE.split(value or "") if part.strip())


def _normalize_header(value: str) -> str:
    text = value.replace("﻿", "").strip().casefold()
    return re.sub(r"\s+", " ", text)


def _header_map(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise RosterError("名单为空：缺少表头")
    normalized = {_normalize_header(name): name for name in fieldnames if name}
    mapping: dict[str, str] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            key = _normalize_header(alias)
            if key in normalized:
                mapping[canonical] = normalized[key]
                break
    if "name" not in mapping:
        expected = "、".join(HEADER_ALIASES["name"])
        raise RosterError(f"名单缺少姓名列（可用表头：{expected}）")
    return mapping


def _text(row: dict[str, str], mapping: dict[str, str], key: str) -> str:
    header = mapping.get(key)
    return (row.get(header, "") if header else "").strip()


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RosterError(f"无法识别名单编码（试过 UTF-8/GB18030）：{path}")


def load_roster(path: str | Path) -> Roster:
    roster_path = Path(path)
    if not roster_path.is_file():
        raise RosterError(f"名单文件不存在：{roster_path}")
    suffix = roster_path.suffix.lower()
    if suffix == ".csv":
        return _load_csv(roster_path)
    if suffix == ".toml":
        return _load_toml(roster_path)
    raise RosterError(f"不支持的名单格式：{suffix}（只支持 .csv / .toml）")


def _load_csv(path: Path) -> Roster:
    text = _read_text(path)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    mapping = _header_map(reader.fieldnames)
    people: list[RosterPerson] = []
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    for row in reader:
        line_no = reader.line_num
        name = _text(row, mapping, "name")
        if not name and not any((value or "").strip() for value in row.values()):
            continue
        if not name:
            raise RosterError(f"第 {line_no} 行缺少姓名")
        institute = _text(row, mapping, "institute")
        aliases = _split_values(_text(row, mapping, "aliases"))
        orcid = normalize_orcid(_text(row, mapping, "orcid"))
        openalex_ids = tuple(
            normalize_author_id(item) for item in _split_values(_text(row, mapping, "openalex_ids"))
        )
        key = (name, institute)
        if key in seen:
            warnings.append(f"第 {line_no} 行与前面重复：{name} / {institute}")
        seen.add(key)
        people.append(
            RosterPerson(
                index=len(people) + 1,
                name=name,
                institute=institute,
                aliases=aliases,
                orcid=orcid,
                openalex_ids=openalex_ids,
                self_check=_text(row, mapping, "self_check"),
                self_check_note=_text(row, mapping, "self_check_note"),
            )
        )
    if not people:
        raise RosterError(f"名单没有有效人员：{path}")
    return Roster(people=tuple(people), warnings=tuple(warnings))


def _load_toml(path: Path) -> Roster:
    from hydrolitagent._config import load_toml

    raw = load_toml(path)
    rows = raw.get("people") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RosterError("TOML 名单需要至少一个 [[people]] 条目")
    people: list[RosterPerson] = []
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise RosterError(f"第 {position} 个 [[people]] 不是表")
        name = str(row.get("name", "")).strip()
        if not name:
            raise RosterError(f"第 {position} 个 [[people]] 缺少 name")
        institute = str(row.get("institute", "")).strip()
        aliases_raw = row.get("aliases", [])
        if isinstance(aliases_raw, str):
            aliases = _split_values(aliases_raw)
        elif isinstance(aliases_raw, list):
            aliases = tuple(str(item).strip() for item in aliases_raw if str(item).strip())
        else:
            raise RosterError(f"{name} 的 aliases 必须是列表或字符串")
        orcid = normalize_orcid(str(row.get("orcid", "")))
        ids_raw = row.get("openalex_ids", row.get("openalex_id", []))
        if isinstance(ids_raw, str):
            ids = _split_values(ids_raw)
        elif isinstance(ids_raw, list):
            ids = tuple(str(item).strip() for item in ids_raw if str(item).strip())
        else:
            raise RosterError(f"{name} 的 openalex_ids 必须是列表或字符串")
        openalex_ids = tuple(normalize_author_id(item) for item in ids)
        key = (name, institute)
        if key in seen:
            warnings.append(f"第 {position} 个 [[people]] 与前面重复：{name} / {institute}")
        seen.add(key)
        people.append(
            RosterPerson(
                index=position,
                name=name,
                institute=institute,
                aliases=aliases,
                orcid=orcid,
                openalex_ids=openalex_ids,
                self_check=str(row.get("self_check", "")).strip(),
                self_check_note=str(row.get("self_check_note", row.get("note", ""))).strip(),
            )
        )
    return Roster(people=tuple(people), warnings=tuple(warnings))


def roster_person_to_query(person: RosterPerson):
    from .models import PersonQuery

    return PersonQuery(
        name=person.name,
        institute=person.institute,
        aliases=person.aliases,
        orcid=person.orcid,
        openalex_ids=person.openalex_ids,
        self_check=person.self_check,
        self_check_note=person.self_check_note,
        index=person.index,
    )
