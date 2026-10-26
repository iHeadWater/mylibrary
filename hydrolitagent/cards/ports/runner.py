"""Ports for running a card task against a prepared paper.

A runner receives a ``PreparedPaper`` (Markdown plus page anchors and figure
assets) and a prompt, and returns structured output. It never receives a PDF
path: the conversion step already happened, and the runner has no way to read a
source that the grounding checks did not see.

``runner_id`` is data written into artifacts, not a branch condition. Any
executor that can read files and emit JSON can implement this port -- a local
CLI, an HTTP API or a human-in-the-loop session.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from hydrolitagent.cards.domain.paper import PreparedPaper
from hydrolitagent.cards.progress import ProgressCallback

ReadingMode = Literal["inline", "file", "chunked"]
RunnerRole = Literal["card_writer", "theme_discovery", "focused_reading"]


@dataclass(frozen=True)
class CardRunRequest:
    """Everything one runner invocation needs.

    ``workspace`` is a directory under the runtime area that holds ``paper.md``,
    ``figures/``, ``request.json`` and ``output.schema.json``. ``paper`` is the
    same preparation the workspace was staged from, so a runner can verify the
    digest without trusting the stage directory.
    """

    run_id: str
    paper: PreparedPaper
    prompt: str
    output_schema: Mapping[str, Any]
    workspace: Path
    timeout_seconds: float
    role: RunnerRole = "card_writer"
    model: str | None = None
    reasoning_effort: str | None = None
    reading_mode: ReadingMode = "file"
    context_budget_tokens: int | None = None
    progress: ProgressCallback | None = field(default=None, compare=False)


@dataclass(frozen=True)
class CardRunError:
    """Structured runner failure: code for machines, message and detail for humans."""

    code: str
    message: str
    detail: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class CardRunResult:
    """Outcome of one runner invocation; ``output`` is unvalidated model output."""

    runner_id: str
    ok: bool
    output: Mapping[str, Any] | None = None
    error: CardRunError | None = None
    model_invoked: bool = False
    model: str | None = None
    reasoning_effort: str | None = None
    usage: Mapping[str, Any] | None = None
    duration_seconds: float = 0.0
    warnings: tuple[str, ...] = ()
    unvalidated_output_path: str | None = None


@dataclass(frozen=True)
class RunnerDoctor:
    """Self-report used by ``cards doctor``: no model call, no user paper read."""

    runner_id: str
    available: bool
    detail: str
    fix: str | None = None


class CardRunner(Protocol):
    runner_id: str

    def doctor(self) -> RunnerDoctor: ...

    def run(self, request: CardRunRequest) -> CardRunResult: ...


__all__ = [
    "CardRunError",
    "CardRunRequest",
    "CardRunResult",
    "CardRunner",
    "ReadingMode",
    "RunnerDoctor",
    "RunnerRole",
]
