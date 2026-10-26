"""Ports for the two-phase, file-based runner protocol.

Some executors cannot be called by the platform: the model runs inside a chat
session the operator already has open. For those, the contract is a directory
instead of a subprocess call:

    prepare(request)  -> write paper.md, figures/, request.json, output.schema.json
    <any agent reads them and writes response.json>
    finalize(run_dir) -> read response.json and return the same CardRunResult

The platform never invokes a model in this mode and never trusts the response
file: ``finalize`` checks the Markdown digest, the canary echo and the JSON
shape before returning. Everything after that is the ordinary grounding and
draft path shared with the CLI and HTTP runners.

This module depends on ``domain`` only. It must not import ``adapters`` and must
not name any model provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from hydrolitagent.cards.domain.paper import FigureAsset, PreparedPaper
from hydrolitagent.cards.ports.runner import CardRunRequest, CardRunResult, CardRunner


@dataclass(frozen=True)
class PreparedRun:
    """On-disk material one session agent needs, plus where the answer goes."""

    run_dir: Path
    markdown_path: Path
    markdown_sha256: str
    request_path: Path
    schema_path: Path
    instructions_path: Path
    response_path: Path
    page_count: int
    canaries: tuple[str, ...]
    figures: tuple[FigureAsset, ...]


class SessionRunner(CardRunner, Protocol):
    """A runner that stages files for an external agent instead of calling one."""

    def prepare(self, request: CardRunRequest) -> PreparedRun: ...

    def finalize(self, run_dir: Path, *, paper: PreparedPaper) -> CardRunResult: ...


__all__ = ["PreparedRun", "SessionRunner"]
