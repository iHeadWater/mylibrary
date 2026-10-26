"""Ports for self-diagnosis.

A doctor reports *capabilities*, not provider choices: whether a converter can
be imported, whether a runner executable exists, whether the artifact root is
writable. It never invokes a model and never reads a user's paper, so it is safe
to run before the first card.

``fix`` is part of the contract: a failing check that does not say what to do
next is a dead end for the operator. Checks are data, so the shared layers can
assemble a report without naming any concrete implementation.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

DoctorStatus = Literal["pass", "warn", "fail", "skip"]


@dataclass(frozen=True)
class DoctorCheck:
    """One capability probe and, on failure, an actionable next step."""

    name: str
    capability: str
    status: DoctorStatus
    detail: str
    fix: str | None = None


@dataclass(frozen=True)
class DoctorReport:
    """Aggregated capability report; ``model_invoked`` is always false."""

    ok: bool
    checks: tuple[DoctorCheck, ...]
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    model_invoked: bool = False


class Doctor(Protocol):
    """Anything that can report its own capability checks."""

    def check(self) -> Sequence[DoctorCheck]: ...


__all__ = ["Doctor", "DoctorCheck", "DoctorReport", "DoctorStatus"]
