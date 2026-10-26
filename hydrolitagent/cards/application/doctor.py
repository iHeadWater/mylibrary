"""Assemble capability checks into one report.

This module owns the *shape* of ``cards doctor``: statuses, aggregation and the
machine-readable envelope. It does not perform process discovery, import a PDF
library or touch the network -- those probes arrive as data from adapters, so a
new runner or converter needs no edit here.

``model_invoked`` is always false: a doctor may report that a model *could* be
called, but it never calls one.
"""
from __future__ import annotations

import platform as platform_module
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from hydrolitagent.cards.ports.doctor import DoctorCheck
from hydrolitagent.cards.ports.paper import ConverterDoctor
from hydrolitagent.cards.ports.runner import RunnerDoctor

# Statuses that make the whole report fail. ``warn`` keeps the platform usable:
# one missing optional runner must not hide a working local converter.
_FAILING = "fail"

_FIX_CONVERTER = "安装或修复 PDF 转换依赖（uv add pymupdf），再运行 cards doctor"


def converter_checks(converter: ConverterDoctor) -> tuple[DoctorCheck, ...]:
    """One check per converter probe, with an actionable fix when unavailable."""

    if converter.available:
        capabilities = "、".join(converter.capabilities) or "无声明能力"
        detail = f"可用；版本={converter.version or '未知'}；能力={capabilities}"
        return (
            DoctorCheck(
                name=f"converter.{converter.converter_id}",
                capability="pdf.convert",
                status="pass",
                detail=detail,
            ),
        )
    return (
        DoctorCheck(
            name=f"converter.{converter.converter_id}",
            capability="pdf.convert",
            status="fail",
            detail=converter.error or "转换器不可用",
            fix=converter.fix or _FIX_CONVERTER,
        ),
    )


def runner_checks(runners: Sequence[RunnerDoctor]) -> tuple[DoctorCheck, ...]:
    """Missing optional runners warn; a report with no usable runner fails."""

    if not runners:
        return (
            DoctorCheck(
                name="runner.registry",
                capability="runner.select",
                status="fail",
                detail="注册表里没有可诊断的运行器",
                fix="检查 hydrolitagent.cards.adapters.runners.registry 的注册",
            ),
        )
    any_available = any(runner.available for runner in runners)
    checks: list[DoctorCheck] = []
    for runner in runners:
        if runner.available:
            status = "pass"
            fix = runner.fix
        else:
            status = "warn" if any_available else "fail"
            fix = runner.fix
        checks.append(
            DoctorCheck(
                name=f"runner.{runner.runner_id}",
                capability=f"runner.{runner.runner_id}",
                status=status,
                detail=runner.detail,
                fix=fix,
            )
        )
    return tuple(checks)


def build_report(
    checks: Sequence[DoctorCheck],
    *,
    capabilities: Mapping[str, Any] | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """Return the ``cards doctor --json`` payload (never invokes a model)."""

    ordered = tuple(checks)
    has_failure = any(check.status == _FAILING for check in ordered)
    return {
        "schema_version": 1,
        "operation": "doctor",
        "ok": bool(ordered) and not has_failure,
        "model_invoked": False,
        "platform": platform or platform_module.platform() or sys.platform,
        "checks": [
            {
                "name": check.name,
                "capability": check.capability,
                "status": check.status,
                "detail": check.detail,
                "fix": check.fix,
            }
            for check in ordered
        ],
        "capabilities": dict(capabilities or {}),
    }


def summarize_capabilities(
    checks: Sequence[DoctorCheck],
    *,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Group passing capability names, so callers do not re-parse check text."""

    passing = [check.capability for check in checks if check.status == "pass"]
    summary: dict[str, Any] = {
        "converters": sorted(
            check.name.split(".", 1)[1]
            for check in checks
            if check.capability == "pdf.convert" and check.status == "pass"
        ),
        "runners": sorted(
            check.name.split(".", 1)[1]
            for check in checks
            if check.capability.startswith("runner.") and check.status == "pass"
        ),
        "storage": sorted(
            check.name.split(".", 1)[1]
            for check in checks
            if check.capability.startswith("storage.") and check.status == "pass"
        ),
        "passing": passing,
    }
    if extra:
        summary.update(extra)
    return summary


__all__ = [
    "build_report",
    "converter_checks",
    "runner_checks",
    "summarize_capabilities",
]
