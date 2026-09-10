"""Tests for scripts/chunk_fulltext.py.

This script sits between two producers that emit the full text under different
keys:

  * ``scripts/fetch_collection_fulltext.py`` emits ``result``
  * the Zotero MCP tool ``zotero_get_fulltext`` emits ``content``
    (it re-serialises the Local API payload, which uses ``content``)

It only understood ``result``, so the MCP path -- which is what
``skills/weekly-review/SKILL.md`` tells the agent to use -- died with exit 3.

Exercised through the real CLI (subprocess) because the exit code is part of
the contract the skill relies on.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "chunk_fulltext.py"

SAMPLE_TEXT = "Abstract\n" + ("hydrology modelling sentence. " * 200) + "\nConclusion\n"


def _write_json(tmp_path: Path, payload: dict, name: str = "fulltext.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _run(tmp_path: Path, source: Path, *, chunk_size: int = 5000):
    out_dir = tmp_path / "chunks"
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(source),
            "--output-dir",
            str(out_dir),
            "--chunk-size",
            str(chunk_size),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_accepts_result_field(tmp_path):
    """Regression guard: the field emitted by fetch_collection_fulltext.py."""
    source = _write_json(tmp_path, {"result": SAMPLE_TEXT})

    proc = _run(tmp_path, source)

    assert proc.returncode == 0, proc.stderr
    assert list((tmp_path / "chunks").glob("chunk_*.txt"))


def test_accepts_content_field(tmp_path):
    """The shape the Zotero MCP tool returns must also work.

    Before the fix this exited 3 with "JSON has no 'result' field".
    """
    source = _write_json(
        tmp_path,
        {"content": SAMPLE_TEXT, "indexedPages": 12, "totalPages": 15},
    )

    proc = _run(tmp_path, source)

    assert proc.returncode == 0, proc.stderr
    assert list((tmp_path / "chunks").glob("chunk_*.txt"))


def test_content_field_text_is_preserved(tmp_path):
    """The chunks must contain the source text, not an empty string."""
    source = _write_json(tmp_path, {"content": SAMPLE_TEXT})

    assert _run(tmp_path, source).returncode == 0

    joined = "".join(
        p.read_text(encoding="utf-8")
        for p in sorted((tmp_path / "chunks").glob("chunk_*.txt"))
    )
    assert "hydrology modelling sentence" in joined


def test_chunk_count_follows_chunk_size(tmp_path):
    """Splitting still respects --chunk-size."""
    source = _write_json(tmp_path, {"content": SAMPLE_TEXT})

    assert _run(tmp_path, source, chunk_size=1000).returncode == 0

    chunks = sorted((tmp_path / "chunks").glob("chunk_*.txt"))
    assert len(chunks) > 1
    assert all(len(p.read_text(encoding="utf-8")) <= 1000 for p in chunks)


def test_empty_text_still_fails(tmp_path):
    """Neither key present -> exit 3, and say which keys were tried."""
    source = _write_json(tmp_path, {"unrelated": "x"})

    proc = _run(tmp_path, source)

    assert proc.returncode == 3
    assert "result" in proc.stderr
    assert "content" in proc.stderr


def test_blank_result_falls_back_to_content(tmp_path):
    """An empty `result` must not shadow a populated `content`."""
    source = _write_json(tmp_path, {"result": "", "content": SAMPLE_TEXT})

    proc = _run(tmp_path, source)

    assert proc.returncode == 0, proc.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
