from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


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


def _split_table_name(name: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
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


def _minimal_toml_loads(text: str) -> dict[str, Any]:
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


def load_toml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if tomllib is not None:
        with path.open("rb") as f:
            return tomllib.load(f)
    return _minimal_toml_loads(path.read_text(encoding="utf-8"))
