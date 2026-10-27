"""How a local CLI is turned into an argv the OS can actually start.

This lives in the adapters layer because it is a property of the deployment
platform, not of the card protocol: shared layers hand a runner an executable
name or path and never learn how it is launched.

Windows specifics: npm installs a CLI as a ``.CMD`` shim next to ``node.exe``.
``CreateProcess`` (what ``subprocess.Popen`` calls) cannot start a batch file —
it raises ``WinError 193`` ("not a valid Win32 application") or, when the name
is bare, ``FileNotFoundError`` because the implicit extension search only tries
``.exe``. ``cmd.exe /c`` is the supported way to run those shims.
"""
from __future__ import annotations

import os
from collections.abc import Sequence

# Suffixes that cmd.exe must interpret, case-insensitively (npm writes both).
BATCH_SUFFIXES = (".cmd", ".bat")
CMD_EXE = "cmd.exe"


def is_batch_shim(executable: str, *, platform: str | None = None) -> bool:
    """True when ``executable`` needs ``cmd.exe /c`` on this platform."""

    host = os.name if platform is None else platform
    return host == "nt" and executable.lower().endswith(BATCH_SUFFIXES)


def launch_argv(
    executable: str,
    arguments: Sequence[str],
    *,
    platform: str | None = None,
) -> list[str]:
    """Return the full argv that starts ``executable`` with ``arguments``.

    On Windows a ``.cmd``/``.bat`` shim is run through ``cmd.exe /c``; every
    other executable (including a native ``.exe``) is started directly.

    ``cmd.exe /c`` limits the command line to 8191 characters. The Markdown
    card commands are a few hundred characters (prompt and paper go through
    stdin/files), so they are far below it; if an argument list ever grows to
    thousands of characters it must be moved off argv rather than truncated.
    Arguments here deliberately avoid embedded double quotes, because cmd.exe
    does not understand the backslash escaping Python applies when it renders
    an argv list.
    """

    host = os.name if platform is None else platform
    if is_batch_shim(executable, platform=host):
        return [CMD_EXE, "/c", executable, *arguments]
    return [executable, *arguments]


__all__ = ["BATCH_SUFFIXES", "CMD_EXE", "is_batch_shim", "launch_argv"]
