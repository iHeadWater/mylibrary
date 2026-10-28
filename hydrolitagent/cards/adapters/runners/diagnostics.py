"""Provider-neutral diagnostic text sanitizing.

Runner failures may quote an upstream error body, a path or a token. Everything
that leaves a runner must pass through :func:`sanitize_diagnostic_text` first, so
a diagnostic never becomes the leak. Nothing here decides which provider ran.
"""
from __future__ import annotations

import re

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


__all__ = [
    "MAX_DIAGNOSTIC_SUMMARY_LENGTH",
    "SECRET_PATTERNS",
    "USER_PROFILE_PATTERN",
    "sanitize_diagnostic_text",
]
