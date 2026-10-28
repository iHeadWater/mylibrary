"""Executable discovery policy for configuration values.

Bare names are resolved through ``PATH``; anything with a separator or a leading
``~`` is anchored at the project root (or kept absolute) so relative tool paths
in the config file mean the same thing on every platform.
"""
from __future__ import annotations

import os
from pathlib import Path


def _resolve_executable(value, root):
    if value is None:
        return None
    expanded = os.path.expandvars(value)
    if "/" in expanded or "\\" in expanded or expanded.startswith("~"):
        path = Path(expanded).expanduser()
        # Keep existing absolute spellings compatible; anchor only relative tools.
        return expanded if path.is_absolute() and not expanded.startswith("~") else str((root / path).resolve())
    return expanded  # Bare executable names are resolved via PATH, not the current directory.


__all__ = ["_resolve_executable"]
