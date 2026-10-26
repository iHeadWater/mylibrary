"""Workspace helpers shared by every card runner.

A runner is handed a staged directory that holds ``paper.md``, ``figures/``,
``request.json`` and ``output.schema.json``. These helpers let a runner:

* read ``paper.md`` and prove it is the preparation it was told about;
* write the answer schema next to the paper;
* keep the raw answer for post-mortem inspection.

Nothing here names a provider or starts a process, so both a local CLI runner
and an HTTP runner can share exactly the same staging contract. The failure type
carries a machine-readable code so each runner maps it onto its own result
without string matching.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydrolitagent.cards.domain.paper import MARKDOWN_FILENAME
from hydrolitagent.cards.ports.runner import CardRunRequest

SCHEMA_FILENAME = "output.schema.json"
RESPONSE_FILENAME = "response.json"


class RunnerFailure(RuntimeError):
    """Internal control-flow exception carrying a structured code."""

    def __init__(
        self, code: str, message: str, *, detail: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.detail = dict(detail or {})


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_workspace_markdown(request: CardRunRequest) -> str:
    """Read the staged Markdown and prove it is the paper we prepared.

    A synthesis request (``paper is None``) has no source paper, so there is
    nothing to read and nothing to verify: the text arrives in the prompt.
    """

    if request.paper is None:
        return ""
    target = Path(request.workspace) / MARKDOWN_FILENAME
    if not target.is_file():
        raise RunnerFailure(
            "MARKDOWN_WORKSPACE_INVALID", f"运行目录缺少 {MARKDOWN_FILENAME}"
        )
    markdown = target.read_text(encoding="utf-8")
    if sha256_text(markdown) != request.paper.markdown_sha256:
        raise RunnerFailure(
            "MARKDOWN_WORKSPACE_INVALID",
            "运行目录中的 paper.md 与已转换论文摘要不一致",
            detail={"expected": request.paper.markdown_sha256},
        )
    return markdown


def ensure_workspace_unchanged(request: CardRunRequest, markdown: str) -> None:
    """Refuse an answer if the staged paper changed while the runner was working."""

    if request.paper is None:
        return
    target = Path(request.workspace) / MARKDOWN_FILENAME
    if sha256_text(target.read_text(encoding="utf-8")) != sha256_text(markdown):
        raise RunnerFailure(
            "MARKDOWN_CHANGED", "运行期间 paper.md 已改变，拒绝接受输出"
        )


def write_schema(request: CardRunRequest) -> Path:
    target = Path(request.workspace) / SCHEMA_FILENAME
    payload = json.dumps(request.output_schema, ensure_ascii=False, indent=2) + "\n"
    target.write_text(payload, encoding="utf-8", newline="\n")
    return target


def record_output(request: CardRunRequest, output: Mapping[str, Any]) -> str:
    """Keep the raw model answer next to the paper for post-mortem inspection."""

    target = Path(request.workspace) / RESPONSE_FILENAME
    target.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return str(target)


__all__ = [
    "RESPONSE_FILENAME",
    "RunnerFailure",
    "SCHEMA_FILENAME",
    "ensure_workspace_unchanged",
    "read_workspace_markdown",
    "record_output",
    "sha256_text",
    "write_schema",
]
