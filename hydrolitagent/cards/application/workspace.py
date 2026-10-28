"""Stage the directory a runner reads.

A runner only ever sees a copy of the prepared material: ``paper.md``, the
figure images, a short ``request.json`` and ``output.schema.json``. Copying
instead of referencing makes the runner's view exactly the preparation that
grounding will verify against, and guarantees no source PDF is reachable from
that directory.

This module depends on ``domain`` and ``ports`` only. It never converts a PDF
and never picks a runner.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydrolitagent.cards.domain.paper import FIGURES_DIRNAME, MARKDOWN_FILENAME, PreparedPaper

REQUEST_FILENAME = "request.json"
SCHEMA_FILENAME = "output.schema.json"


def runtime_dir(app_config: Any) -> Path:
    """Where staged run directories live; the OS temp directory as a fallback."""

    configured = getattr(app_config.card_generator, "runtime_dir", None) or getattr(
        app_config.paths, "runtime_dir", None
    )
    return Path(configured) if configured else Path(tempfile.gettempdir())


def stage_text_workspace(
    *,
    run_id: str,
    root: Path,
    context: Mapping[str, Any] | None = None,
    schema_text: str,
) -> Path:
    """Create a run directory for a synthesis task that has no source paper."""

    root.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=f"text-{run_id[:8]}-", dir=str(root)))
    (workspace / REQUEST_FILENAME).write_text(
        json.dumps(dict(context or {}), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (workspace / SCHEMA_FILENAME).write_text(schema_text, encoding="utf-8", newline="\n")
    return workspace


def stage_paper_workspace(
    prepared: PreparedPaper,
    *,
    run_id: str,
    root: Path,
    context: Mapping[str, Any] | None = None,
    schema_text: str,
) -> Path:
    """Create a temporary run directory holding only the prepared material."""

    root.mkdir(parents=True, exist_ok=True)
    workspace = Path(
        tempfile.mkdtemp(prefix=f"markdown-{run_id[:8]}-", dir=str(root))
    )
    shutil.copyfile(prepared.markdown_path, workspace / MARKDOWN_FILENAME)
    for figure in prepared.figures:
        target = workspace / FIGURES_DIRNAME / figure.path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(figure.path, target)
    (workspace / REQUEST_FILENAME).write_text(
        json.dumps(dict(context or {}), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (workspace / SCHEMA_FILENAME).write_text(schema_text, encoding="utf-8", newline="\n")
    return workspace


__all__ = [
    "REQUEST_FILENAME",
    "SCHEMA_FILENAME",
    "runtime_dir",
    "stage_paper_workspace",
    "stage_text_workspace",
]
