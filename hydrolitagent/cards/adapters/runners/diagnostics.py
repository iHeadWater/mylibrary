"""Provider-neutral subprocess diagnostics.

Originally lived inside ``card_generators/codex_cli.py``; moved here so that a
top-level module (``pdf_sandbox``) no longer imports a concrete provider's
private helpers.

Nothing here decides which provider ran.  The wording of the fallback summary is
kept byte-compatible with the previous output during the decoupling migration.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any


DIAGNOSTIC_EVENT_TYPES = frozenset({"error", "turn.failed"})
DIAGNOSTIC_KEYS = frozenset(
    {"type", "code", "message", "status", "param", "reason", "error"}
)
DIAGNOSTIC_LINE_PATTERN = re.compile(
    r"error|fail|denied|invalid|unsupported|unavailable|refus|limit|quota|"
    r"timeout|sandbox|permission|context|disconnect|closed|cancel",
    re.IGNORECASE,
)
USER_PROFILE_PATTERN = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s\"']+")
SECRET_PATTERNS = (
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/=]{8,}"),
    re.compile(
        r"(?i)\b(authorization|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
        r"secret|password)\b\s*[:=]\s*[^\s,;]+"
    ),
)
MAX_DIAGNOSTIC_SUMMARY_LENGTH = 1600


def sanitize_diagnostic_text(value: str) -> str:
    sanitized = value.replace("\x00", " ")
    sanitized = USER_PROFILE_PATTERN.sub("%USERPROFILE%", sanitized)
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("<redacted>", sanitized)
    sanitized = " ".join(sanitized.split())
    if len(sanitized) > MAX_DIAGNOSTIC_SUMMARY_LENGTH:
        sanitized = sanitized[: MAX_DIAGNOSTIC_SUMMARY_LENGTH - 1].rstrip() + "…"
    return sanitized


def event_diagnostic_parts(value: Any, *, key: str | None = None) -> list[str]:
    if isinstance(value, dict):
        parts: list[str] = []
        for child_key, child_value in value.items():
            parts.extend(event_diagnostic_parts(child_value, key=str(child_key)))
        return parts
    if isinstance(value, list):
        parts = []
        for child in value:
            parts.extend(event_diagnostic_parts(child, key=key))
        return parts
    if key not in DIAGNOSTIC_KEYS or not isinstance(value, (str, int, float, bool)):
        return []
    rendered = sanitize_diagnostic_text(f"{key}={value}")
    return [rendered] if rendered else []


def safe_exec_diagnostic(
    result: subprocess.CompletedProcess[str],
    category: str,
    *,
    stage: str = "codex_exec",
) -> dict[str, Any]:
    event_summaries: list[str] = []
    error_events: list[str] = []
    first_tool_error: dict[str, str] | None = None
    for line in (result.stdout or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if (
            first_tool_error is None and event.get("type") == "item.completed"
            and isinstance(item, dict) and item.get("type") == "mcp_tool_call"
            and item.get("status") == "failed"
        ):
            first_tool_error = {
                "server": sanitize_diagnostic_text(str(item.get("server", "unknown"))),
                "tool": sanitize_diagnostic_text(str(item.get("tool", "unknown"))),
                "summary": sanitize_diagnostic_text(" | ".join(
                    event_diagnostic_parts(item.get("error"), key="error")
                )) or "工具失败，CLI 未提供错误细节",
            }
        if event.get("type") in DIAGNOSTIC_EVENT_TYPES:
            parts = event_diagnostic_parts(event)
            event_summaries.extend(parts)
            error_events.append(sanitize_diagnostic_text(" | ".join(parts)))

    stderr_lines = [
        line.strip()
        for line in (result.stderr or "").splitlines()
        if line.strip() and DIAGNOSTIC_LINE_PATTERN.search(line)
    ]
    if not stderr_lines and not event_summaries:
        stderr_lines = [
            line.strip()
            for line in (result.stderr or "").splitlines()
            if line.strip()
        ][-3:]
    stderr_summaries = [
        sanitize_diagnostic_text(line) for line in stderr_lines[-6:]
    ]

    if event_summaries and stderr_summaries:
        source = "codex_error_event+stderr"
    elif event_summaries:
        source = "codex_error_event"
    elif stderr_summaries:
        source = "codex_stderr"
    else:
        source = "none"
    summaries = event_summaries + stderr_summaries

    unique_summaries = list(dict.fromkeys(part for part in summaries if part))
    summary = sanitize_diagnostic_text(" | ".join(unique_summaries))
    if not summary:
        summary = "Codex CLI 未提供可安全提取的错误摘要"
    diagnostic = {
        "stage": stage,
        "exit_code": result.returncode,
        "category": category,
        "source": source,
        "summary": summary,
    }
    if error_events:
        diagnostic["first_error"] = error_events[0]
        diagnostic["last_error"] = error_events[-1]
        diagnostic["error_event_count"] = len(error_events)
    if first_tool_error is not None:
        diagnostic["first_tool_error"] = first_tool_error
    return diagnostic


def timeout_text(value: str | bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""


__all__ = [
    "DIAGNOSTIC_EVENT_TYPES",
    "DIAGNOSTIC_KEYS",
    "DIAGNOSTIC_LINE_PATTERN",
    "MAX_DIAGNOSTIC_SUMMARY_LENGTH",
    "SECRET_PATTERNS",
    "USER_PROFILE_PATTERN",
    "event_diagnostic_parts",
    "safe_exec_diagnostic",
    "sanitize_diagnostic_text",
    "timeout_text",
]
