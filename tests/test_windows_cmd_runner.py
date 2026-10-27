"""Launching a local CLI on Windows: npm installs it as a ``.CMD`` shim.

``subprocess.Popen`` cannot start a batch file, and a bare name is only looked
up with a ``.exe`` extension, so the runner must (a) use the path the finder
resolved and (b) route a ``.cmd``/``.bat`` through ``cmd.exe /c``.
"""
from __future__ import annotations

import os

import pytest

from hydrolitagent.cards.adapters.runners.executable import is_batch_shim, launch_argv
from hydrolitagent.cards.adapters.runners.markdown import CodexMarkdownRunner
from test_markdown_runners import FakeProcessRunner, codex_stdout, request_for

NPM_CODEX = r"C:\Users\owen\AppData\Roaming\npm\codex.CMD"


# --------------------------------------------------------------------------------------
# pure argv construction
# --------------------------------------------------------------------------------------


def test_a_cmd_shim_is_routed_through_cmd_exe():
    argv = launch_argv(NPM_CODEX, ["exec", "--json"], platform="nt")

    assert argv[:3] == ["cmd.exe", "/c", NPM_CODEX]
    assert argv[3:] == ["exec", "--json"]


@pytest.mark.parametrize("suffix", [".cmd", ".CMD", ".bat", ".Bat"])
def test_shim_suffixes_are_case_insensitive(suffix):
    executable = "C:\\npm\\codex" + suffix

    assert is_batch_shim(executable, platform="nt") is True
    assert launch_argv(executable, [], platform="nt")[:3] == [
        "cmd.exe",
        "/c",
        executable,
    ]


def test_a_native_exe_is_started_directly_on_windows():
    executable = r"C:\Program Files\Claude\claude.EXE"

    assert launch_argv(executable, ["--print"], platform="nt") == [
        executable,
        "--print",
    ]


@pytest.mark.parametrize("executable", ["codex", "/usr/local/bin/codex", "./codex.cmd"])
def test_posix_never_wraps_the_executable(executable):
    assert launch_argv(executable, ["exec"], platform="posix") == [executable, "exec"]


def test_the_platform_defaults_to_the_host():
    # Same answer with and without an explicit platform; the default is not a
    # second, hard-coded policy.
    assert is_batch_shim(NPM_CODEX) is (os.name == "nt")


# --------------------------------------------------------------------------------------
# the codex runner uses it
# --------------------------------------------------------------------------------------


def _codex_command(tmp_path):
    request = request_for(tmp_path)
    fake = FakeProcessRunner(codex_stdout({"ok": True}))
    runner = CodexMarkdownRunner(
        "codex", finder=lambda _name: NPM_CODEX, prompt_runner=fake
    )
    result = runner.run(request)
    assert result.ok, result.error
    return fake.calls[0][0]


def test_codex_runner_uses_the_resolved_executable(tmp_path):
    command = _codex_command(tmp_path)

    if os.name == "nt":
        assert command[:3] == ["cmd.exe", "/c", NPM_CODEX]
        assert command[3:5] == ["exec", "--json"]
    else:
        assert command[0] == NPM_CODEX


def test_codex_config_overrides_need_no_backslash_escaping(tmp_path):
    """cmd.exe does not understand ``\\"``; keep the argv free of it."""

    command = _codex_command(tmp_path)

    assert "approval_policy='never'" in command
    assert "web_search='disabled'" in command
    assert not [argument for argument in command if '\\"' in argument]


def test_codex_still_refuses_a_missing_executable(tmp_path):
    request = request_for(tmp_path)
    runner = CodexMarkdownRunner("codex", finder=lambda _name: None)

    result = runner.run(request)

    assert result.ok is False
    assert result.error.code == "MARKDOWN_RUNNER_NOT_FOUND"
