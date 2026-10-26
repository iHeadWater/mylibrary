"""Subprocess plumbing for the Codex CLI runner.

Environment handling stays here: callers pass an explicit override map and this
module never mutates ``os.environ`` for the parent process.
"""
from __future__ import annotations

import os
import subprocess
from typing import Callable, Mapping, Sequence

from hydrolitagent.cards.infrastructure.decoding import (
    DecodedText,
    decode_process_output,
    normalize_newlines,
)


CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]
PromptRunner = Callable[
    [Sequence[str], str, float, Mapping[str, str] | None],
    subprocess.CompletedProcess[str],
]
ExecutableFinder = Callable[[str], str | None]


def _decode_completed(
    command: Sequence[str], completed: subprocess.CompletedProcess[bytes]
) -> subprocess.CompletedProcess[str]:
    """Decode both pipes with the ladder and keep the stderr metadata."""

    stdout = decode_process_output(completed.stdout)
    decoded_stderr = decode_process_output(completed.stderr)
    stderr = DecodedText(
        normalize_newlines(decoded_stderr.text),
        decoded_stderr.encoding,
        decoded_stderr.replacement_count,
    )
    result = subprocess.CompletedProcess(
        list(command),
        completed.returncode,
        normalize_newlines(stdout.text),
        stderr.text,
    )
    setattr(result, "stderr_meta", stderr)
    return result


def _run_command(
    command: Sequence[str],
    timeout_seconds: float,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_environment = os.environ.copy()
    process_environment.update(environment or {})
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        timeout=timeout_seconds,
        env=process_environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return _decode_completed(command, completed)


def _run_prompt_command(
    command: Sequence[str],
    prompt: str,
    timeout_seconds: float,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_environment = os.environ.copy()
    if environment is not None:
        process_environment.update(environment)
    completed = subprocess.run(
        list(command),
        input=prompt.encode("utf-8"),
        check=False,
        capture_output=True,
        timeout=timeout_seconds,
        env=process_environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return _decode_completed(command, completed)


__all__ = [
    "CommandRunner",
    "ExecutableFinder",
    "PromptRunner",
    "_run_command",
    "_run_prompt_command",
]
