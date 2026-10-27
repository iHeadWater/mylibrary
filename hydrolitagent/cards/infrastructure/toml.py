"""TOML encoding helpers used for CLI ``-c key=value`` overrides.

JSON strings are valid TOML basic strings for the scalar values we encode, so
``json.dumps`` is intentional rather than a shortcut.
"""
from __future__ import annotations

import json
from typing import Mapping


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def toml_literal(value: str) -> str:
    """TOML literal string (single quotes) for values that stay double-quote free.

    An argv that is rendered through ``cmd.exe`` on Windows cannot carry
    backslash-escaped quotes: cmd.exe has no backslash escape, so ``\\"``
    reaches the child verbatim. A literal string needs no escaping at all,
    which makes it the safe spelling for simple values such as a reasoning
    effort. Reject values a literal string cannot represent.
    """

    if not value or "'" in value or "\n" in value or "\x00" in value:
        raise ValueError("TOML 字面量字符串只接受不含单引号、换行的非空值")
    return f"'{value}'"


def toml_string_map(values: Mapping[str, str]) -> str:
    entries = (
        f"{key}={toml_string(value)}" for key, value in sorted(values.items())
    )
    return "{" + ",".join(entries) + "}"


__all__ = ["toml_literal", "toml_string", "toml_string_map"]
