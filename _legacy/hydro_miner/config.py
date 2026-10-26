from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None


@dataclass
class TimeRule:
    start_date: date
    date_policy: str
    status_terms: list[str]
    status_can_bypass_date_terms: list[str]
    status_from_sheet: bool = True
    keep_year_only_if_year_at_least: int | None = None


@dataclass
class RecordTypeConfig:
    kind: str
    enabled: bool
    sheet_keywords: list[str]
    exclude_sheet_keywords: list[str]
    title_columns: list[int]
    summary_columns: list[int]
    people_columns: list[int]
    venue_columns: list[int]
    identifier_columns: list[int]
    time: TimeRule


@dataclass
class TrackConfig:
    name: str
    keywords: list[str]
    prompt: str


@dataclass
class AppConfig:
    repo_root: Path
    config_path: Path
    input_files: list[Path]
    output_dir: Path
    manual_records_path: Path
    platform_name: str
    platform_keywords: list[str]
    people_allowlist: dict[str, list[str]]
    record_types: dict[str, RecordTypeConfig]
    tracks: dict[str, TrackConfig]


def _as_str_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings")
    return value


def _as_int_list(value: Any, field_name: str) -> list[int]:
    if not isinstance(value, list) or not all(isinstance(item, int) for item in value):
        raise ValueError(f"{field_name} must be a list of integers")
    return value


def _parse_date(value: Any, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"{field_name} must be an ISO date string")


def _repo_root_for(config_path: Path) -> Path:
    return config_path.parent.parent if config_path.parent.name == "configs" else config_path.parent


def _resolve_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _split_table_name(name: str) -> list[str]:
    parts: list[str] = []
    current = []
    in_quote = False
    for ch in name:
        if ch == '"':
            in_quote = not in_quote
            continue
        if ch == "." and not in_quote:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return [part for part in parts if part]


def _parse_value(value: str) -> Any:
    value = value.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    if re_match := re.fullmatch(r"-?\d+", value):
        return int(re_match.group(0))
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value.strip('"')


def _minimal_toml_loads(text: str) -> dict[str, Any]:
    """Parse the small TOML subset used by this repository's config file."""
    root: dict[str, Any] = {}
    current = root
    pending_key = ""
    pending_value_lines: list[str] = []
    bracket_balance = 0

    def assign(key: str, raw_value: str) -> None:
        current[key.strip().strip('"')] = _parse_value(raw_value)

    for original in text.splitlines():
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if pending_key:
            pending_value_lines.append(line)
            bracket_balance += line.count("[") - line.count("]")
            if bracket_balance <= 0:
                assign(pending_key, "\n".join(pending_value_lines))
                pending_key = ""
                pending_value_lines = []
            continue
        if line.startswith("[") and line.endswith("]"):
            current = root
            for part in _split_table_name(line[1:-1]):
                current = current.setdefault(part, {})
            continue
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        raw_value = raw_value.strip()
        if raw_value.startswith("[") and raw_value.count("[") > raw_value.count("]"):
            pending_key = key
            pending_value_lines = [raw_value]
            bracket_balance = raw_value.count("[") - raw_value.count("]")
            continue
        assign(key, raw_value)
    return root


def _load_toml(path: Path) -> dict[str, Any]:
    if tomllib is not None:
        with path.open("rb") as f:
            return tomllib.load(f)
    return _minimal_toml_loads(path.read_text(encoding="utf-8"))


def _record_type(kind: str, raw: dict[str, Any]) -> RecordTypeConfig:
    time_raw = raw.get("time", {})
    if not isinstance(time_raw, dict):
        raise ValueError(f"record_types.{kind}.time must be a table")
    return RecordTypeConfig(
        kind=kind,
        enabled=bool(raw.get("enabled", True)),
        sheet_keywords=_as_str_list(raw.get("sheet_keywords", []), f"record_types.{kind}.sheet_keywords"),
        exclude_sheet_keywords=_as_str_list(
            raw.get("exclude_sheet_keywords", []), f"record_types.{kind}.exclude_sheet_keywords"
        ),
        title_columns=_as_int_list(raw.get("title_columns", []), f"record_types.{kind}.title_columns"),
        summary_columns=_as_int_list(raw.get("summary_columns", []), f"record_types.{kind}.summary_columns"),
        people_columns=_as_int_list(raw.get("people_columns", []), f"record_types.{kind}.people_columns"),
        venue_columns=_as_int_list(raw.get("venue_columns", []), f"record_types.{kind}.venue_columns"),
        identifier_columns=_as_int_list(raw.get("identifier_columns", []), f"record_types.{kind}.identifier_columns"),
        time=TimeRule(
            start_date=_parse_date(time_raw.get("start_date"), f"record_types.{kind}.time.start_date"),
            date_policy=str(time_raw.get("date_policy", "record_or_status")),
            status_terms=_as_str_list(time_raw.get("status_terms", []), f"record_types.{kind}.time.status_terms"),
            status_can_bypass_date_terms=_as_str_list(
                time_raw.get("status_can_bypass_date_terms", []),
                f"record_types.{kind}.time.status_can_bypass_date_terms",
            ),
            status_from_sheet=bool(time_raw.get("status_from_sheet", True)),
            keep_year_only_if_year_at_least=time_raw.get("keep_year_only_if_year_at_least"),
        ),
    )


def load_config(path: str | Path = "configs/platform.toml") -> AppConfig:
    config_path = Path(path).resolve()
    raw = _load_toml(config_path)
    repo_root = _repo_root_for(config_path)

    input_files = [
        _resolve_path(repo_root, item)
        for item in _as_str_list(raw.get("input", {}).get("files", []), "input.files")
    ]
    output_dir = _resolve_path(repo_root, str(raw.get("output", {}).get("dir", "outputs")))
    manual_raw = raw.get("manual", {})
    if not isinstance(manual_raw, dict):
        raise ValueError("manual must be a table")
    manual_default = str(config_path.parent / "manual_records.toml")
    manual_records_path = _resolve_path(repo_root, str(manual_raw.get("records_file", manual_default)))

    platform = raw.get("platform", {})
    people = raw.get("people", {}).get("allowlist", {})
    if not isinstance(people, dict):
        raise ValueError("people.allowlist must be a table")
    people_allowlist = {str(name): _as_str_list(aliases, f"people.allowlist.{name}") for name, aliases in people.items()}

    record_types_raw = raw.get("record_types", {})
    if not isinstance(record_types_raw, dict):
        raise ValueError("record_types must be a table")
    record_types = {
        kind: _record_type(kind, value)
        for kind, value in record_types_raw.items()
        if isinstance(value, dict)
    }

    tracks_raw = raw.get("tracks", {})
    if not isinstance(tracks_raw, dict):
        raise ValueError("tracks must be a table")
    tracks = {
        str(name): TrackConfig(
            name=str(name),
            keywords=_as_str_list(value.get("keywords", []), f"tracks.{name}.keywords"),
            prompt=str(value.get("prompt", "")),
        )
        for name, value in tracks_raw.items()
        if isinstance(value, dict)
    }

    return AppConfig(
        repo_root=repo_root,
        config_path=config_path,
        input_files=input_files,
        output_dir=output_dir,
        manual_records_path=manual_records_path,
        platform_name=str(platform.get("name", "")),
        platform_keywords=_as_str_list(platform.get("keywords", []), "platform.keywords"),
        people_allowlist=people_allowlist,
        record_types=record_types,
        tracks=tracks,
    )
