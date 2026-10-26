"""Subprocess plumbing for the Codex CLI runner.

Environment handling stays here: callers pass an explicit override map and this
module never mutates ``os.environ`` for the parent process.
"""
from __future__ import annotations

import os
import subprocess
from typing import Callable, Mapping, Sequence


CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]
PromptRunner = Callable[
    [Sequence[str], str, float, Mapping[str, str] | None],
    subprocess.CompletedProcess[str],
]
ExecutableFinder = Callable[[str], str | None]


def _run_command(
    command: Sequence[str],
    timeout_seconds: float,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_environment = os.environ.copy()
    process_environment.update(environment or {})
    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        env=process_environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _run_prompt_command(
    command: Sequence[str],
    prompt: str,
    timeout_seconds: float,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_environment = os.environ.copy()
    if environment is not None:
        process_environment.update(environment)
    return subprocess.run(
        list(command),
        input=prompt,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        env=process_environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


__all__ = [
    "CommandRunner",
    "ExecutableFinder",
    "PromptRunner",
    "_run_command",
    "_run_prompt_command",
]
