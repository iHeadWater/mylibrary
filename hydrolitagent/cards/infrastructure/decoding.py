"""Decoding ladder for child-process output.

Windows consoles and CLIs emit bytes in the active ANSI code page (for example
CP936 on a Chinese Windows install), while the tool protocols we speak
(JSONL events, Markdown) are UTF-8.  Decoding everything as ``utf-8`` with
``errors="replace"`` turns those bytes into U+FFFD and loses the original
error message forever.

The ladder, in order:

1. no data            -> ``""`` / ``"empty"`` / 0 replacements
2. strict UTF-8       -> ``"utf-8"``
3. strict locale      -> ``"locale:<name>"`` (skipped when it *is* UTF-8)
4. UTF-8 with replace -> ``"replace"`` plus a U+FFFD count

Decoding never raises for malformed input; the reported ``encoding`` and
``replacement_count`` keep the loss visible instead of silently hiding it.
"""
from __future__ import annotations

import codecs
import locale
from dataclasses import dataclass

REPLACEMENT_CHARACTER = "�"


@dataclass(frozen=True)
class DecodedText:
    """Decoded text plus how it was obtained."""

    text: str
    encoding: str
    replacement_count: int


def _locale_name(preferred: str | None) -> str | None:
    if preferred is not None:
        return preferred
    try:
        return locale.getpreferredencoding(False)
    except (LookupError, ValueError):
        # A broken locale must not abort diagnostics; fall through to replace.
        return None


def _canonical_encoding(name: str) -> str | None:
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


def decode_process_output(
    data: bytes | None, *, preferred: str | None = None
) -> DecodedText:
    """Decode child-process bytes using the ladder described above."""

    if not data:
        return DecodedText("", "empty", 0)

    try:
        return DecodedText(data.decode("utf-8"), "utf-8", 0)
    except UnicodeDecodeError:
        pass

    locale_name = _locale_name(preferred)
    if locale_name:
        canonical = _canonical_encoding(locale_name)
        if canonical is not None and canonical != "utf-8":
            try:
                return DecodedText(
                    data.decode(locale_name), f"locale:{locale_name}", 0
                )
            except UnicodeDecodeError:
                pass

    text = data.decode("utf-8", errors="replace")
    return DecodedText(text, "replace", text.count(REPLACEMENT_CHARACTER))


def decode_text(value: str | bytes | None) -> str:
    """Lenient helper for values that may already be text (timeout payloads)."""

    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return decode_process_output(value).text
    return ""


def normalize_newlines(text: str) -> str:
    """Apply the universal-newline translation ``text=True`` used to perform.

    A process pipe is bytes, so switching to binary capture would otherwise let
    a Windows child's CRLF reach callers that previously saw ``\\n``.
    """

    return text.replace("\r\n", "\n").replace("\r", "\n")


__all__ = [
    "DecodedText",
    "REPLACEMENT_CHARACTER",
    "decode_process_output",
    "decode_text",
    "normalize_newlines",
]
