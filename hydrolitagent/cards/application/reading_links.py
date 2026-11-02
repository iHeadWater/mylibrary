"""Relative links for the generated reading layer.

The product tree moves, so every link the reading layer writes is relative to the
page that carries it. Two callers need the same rule -- the page generator and the
citation rewriter -- so it lives here rather than in either of them.
"""
from __future__ import annotations

import os
from pathlib import Path


def relative_path(target: Path, from_dir: Path) -> str:
    try:
        return Path(os.path.relpath(target, from_dir)).as_posix()
    except ValueError:
        # Windows paths on separate drives: fall back to an absolute path. The
        # link checker skips absolute targets, and so does this fallback.
        return target.as_posix()


def file_link(text: str, target: Path, from_dir: Path) -> str:
    return f"[{text}](<{relative_path(target, from_dir)}>)"
