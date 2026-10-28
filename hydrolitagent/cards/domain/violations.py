"""Machine-actionable problems, so a gate never reports only "something is wrong".

Every card gate used to raise on its first problem. For a human re-reading the
answer that is enough; for a repair step a vague message is useless -- a model
told "字段与制卡协议不一致" cannot know which field to touch. A gate therefore
returns ``Violation`` objects:

* ``code`` -- the stable machine reason the CLI and the tests assert on;
* ``path`` -- where in the answer, e.g. ``machine_fields.findings[2].finding_id``;
* ``message`` -- what is wrong, in the reader's language;
* ``expected`` / ``actual`` -- the comparison, when a comparison is the point.

Collecting is the default: a gate that can find eight problems reports eight, so
one repair round can fix them together instead of eight rounds of one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MISSING: Any = object()
"""Sentinel for "the answer did not carry this key at all"."""


def describe_value(value: Any, *, limit: int = 60) -> str:
    """A short, safe description of what the answer actually carried."""

    if value is MISSING:
        return "未提供"
    if isinstance(value, bool):
        return f"布尔值 {value}"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return f"数值 {value}"
    if isinstance(value, str):
        compact = " ".join(value.split())
        if len(compact) > limit:
            compact = compact[:limit] + "…"
        return f"字符串 {compact!r}"
    if isinstance(value, dict):
        keys = ", ".join(sorted(value)) or "无"
        return f"对象（键：{keys}）"
    if isinstance(value, (list, tuple)):
        return f"数组（{len(value)} 项）"
    return type(value).__name__


@dataclass(frozen=True)
class Violation:
    """One place where an answer does not satisfy a gate."""

    code: str
    path: str
    message: str
    expected: str | None = None
    actual: str | None = None

    def as_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "path": self.path, "message": self.message}
        if self.expected is not None:
            payload["expected"] = self.expected
        if self.actual is not None:
            payload["actual"] = self.actual
        return payload

    def render(self) -> str:
        parts = []
        if self.expected is not None:
            parts.append(f"期望 {self.expected}")
        if self.actual is not None:
            parts.append(f"实际 {self.actual}")
        detail = f"（{'；'.join(parts)}）" if parts else ""
        return f"[{self.code}] {self.path}：{self.message}{detail}"


def violation_dicts(violations: list[Violation]) -> list[dict[str, str]]:
    return [violation.as_dict() for violation in violations]


__all__ = ["MISSING", "Violation", "describe_value", "violation_dicts"]
