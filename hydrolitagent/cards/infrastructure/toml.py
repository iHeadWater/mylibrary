"""TOML encoding helpers used for CLI ``-c key=value`` overrides.

JSON strings are valid TOML basic strings for the scalar values we encode, so
``json.dumps`` is intentional rather than a shortcut.
"""
from __future__ import annotations

import json
from typing import Mapping


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def toml_string_map(values: Mapping[str, str]) -> str:
    entries = (
        f"{key}={toml_string(value)}" for key, value in sorted(values.items())
    )
    return "{" + ",".join(entries) + "}"


__all__ = ["toml_string", "toml_string_map"]
