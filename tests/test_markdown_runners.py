"""Behaviour of the Markdown-first runners without invoking a model.

Each test drives a real runner with a fake process runner, so the assertions
cover the actual command line, the actual workspace check and the actual event
decoding. Nothing here reaches a CLI, a login or the network.

The command assertions exist because an unsupported flag is invisible until a
real call fails: ``codex-cli 0.121.0`` rejects ``--ignore-user-config`` with exit
code 2, and only a test that reads the built command can catch that early.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hydrolitagent.cards.adapters.runners.markdown import (
    ClaudeMarkdownRunner,
    CodexMarkdownRunner,
)
from hydrolitagent.cards.domain.paper import (
    MARKDOWN_FILENAME,
    PageAnchor,
    PreparedPaper,
    SourceIdentity,
)
from hydrolitagent.cards.ports.runner import CardRunRequest

MARKDOWN = (
    "<!-- page: 1 -->\n"
    "<!-- reading-canary: c-00000001 -->\n"
    "# A study of runoff\n\n"
    "We find that the proposed model reduces peak error by 18 percent overall.\n"
)


def prepared(tmp_path: Path) -> PreparedPaper:
    markdown_path = tmp_path / "store" / MARKDOWN_FILENAME
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(MARKDOWN, encoding="utf-8")
    import hashlib

    digest = hashlib.sha256(MARKDOWN.encode("utf-8")).hexdigest()
    return PreparedPaper(
        source=SourceIdentity(
            pdf_sha256="a" * 64, size_bytes=10, page_count=1, parent_key="PARENT01"
        ),
        markdown_path=markdown_path,
        markdown_sha256=digest,
        manifest_path=markdown_path.parent / "manifest.json",
        page_anchors=(
            PageAnchor(
                page=1,
                char_start=0,
                char_end=len(MARKDOWN),
                heading="A study of runoff",
                role="body",
                canary="c-00000001",
            ),
        ),
        figures=(),
        converter_id="pymupdf",
        converter_version="test",
        text_coverage=1.0,
        warnings=(),
    )


def request_for(tmp_path: Path) -> CardRunRequest:
    paper = prepared(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / MARKDOWN_FILENAME).write_text(MARKDOWN, encoding="utf-8")
    return CardRunRequest(
        run_id="run-1",
        paper=paper,
        prompt="read paper.md and answer",
        output_schema={"type": "object"},
        workspace=workspace,
        timeout_seconds=5,
        model=None,
        reasoning_effort=None,
    )


class FakeProcessRunner:
    """Records the command and returns a canned completed process."""

    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.calls: list[tuple[list[str], str, Path]] = []

    def __call__(self, command, prompt, timeout, environment=None, **kwargs):
        self.calls.append((list(command), prompt, Path(kwargs["cwd"])))
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, "")


def codex_stdout(payload: dict) -> str:
    events = [
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(payload)}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}},
    ]
    return "\n".join(json.dumps(event) for event in events) + "\n"


def claude_stdout(payload: dict, workspace: Path, *, read_target: str | None = None) -> str:
    target = read_target if read_target is not None else str(workspace / MARKDOWN_FILENAME)
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Read", "id": "t1", "input": {"file_path": target}}
                ]
            },
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "structured_output": payload,
            "usage": {"input_tokens": 5},
        },
    ]
    return "\n".join(json.dumps(event) for event in events) + "\n"


# --------------------------------------------------------------------------------------
# command construction
# --------------------------------------------------------------------------------------


def test_codex_command_is_read_only_and_uses_supported_flags(tmp_path):
    request = request_for(tmp_path)
    fake = FakeProcessRunner(codex_stdout({"ok": True}))
    runner = CodexMarkdownRunner("codex", finder=lambda _: "codex", prompt_runner=fake)

    result = runner.run(request)

    assert result.ok, result.error
    command, prompt, cwd = fake.calls[0]
    assert prompt == "read paper.md and answer"
    assert cwd == request.workspace.resolve()
    assert command[1:3] == ["exec", "--json"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--cd") + 1] == str(request.workspace.resolve())
    assert command[-1] == "-"  # prompt over stdin
    assert "--output-schema" in command
    # The flag that codex-cli 0.121.0 rejects must not come back.
    assert "--ignore-user-config" not in command
    assert "mcp_servers={}" in command
    assert result.usage == {"input_tokens": 10, "output_tokens": 20}
    assert result.output == {"ok": True}


def test_claude_command_grants_only_the_read_tool(tmp_path):
    request = request_for(tmp_path)
    fake = FakeProcessRunner(claude_stdout({"ok": True}, request.workspace))
    runner = ClaudeMarkdownRunner("claude", finder=lambda _: "claude", prompt_runner=fake)

    result = runner.run(request)

    assert result.ok, result.error
    command, _prompt, cwd = fake.calls[0]
    assert "--safe-mode" in command and "--restricted" in command
    assert command[command.index("--tools") + 1] == "Read"
    assert command[command.index("--allowedTools") + 1] == "Read"
    assert command[command.index("--add-dir") + 1] == str(request.workspace.resolve())
    assert "--json-schema" in command
    assert cwd == request.workspace.resolve()
    assert result.output == {"ok": True}


# --------------------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------------------


def test_claude_rejects_a_read_outside_the_workspace(tmp_path):
    request = request_for(tmp_path)
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("secret", encoding="utf-8")
    fake = FakeProcessRunner(claude_stdout({"ok": True}, request.workspace, read_target=str(outside)))
    runner = ClaudeMarkdownRunner("claude", finder=lambda _: "claude", prompt_runner=fake)

    result = runner.run(request)

    assert result.ok is False
    assert result.error.code == "MARKDOWN_RUNNER_UNEXPECTED_ACTIVITY"


def test_claude_rejects_a_tool_other_than_read(tmp_path):
    request = request_for(tmp_path)
    stdout = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"command": "ls"}}
                ]
            },
        }
    )
    runner = ClaudeMarkdownRunner(
        "claude", finder=lambda _: "claude", prompt_runner=FakeProcessRunner(stdout + "\n")
    )

    result = runner.run(request)

    assert result.ok is False
    assert result.error.code == "MARKDOWN_RUNNER_UNEXPECTED_ACTIVITY"


def test_codex_rejects_an_mcp_call(tmp_path):
    request = request_for(tmp_path)
    events = [
        {"type": "item.completed", "item": {"type": "mcp_tool_call", "status": "completed"}},
        {"type": "turn.completed"},
    ]
    runner = CodexMarkdownRunner(
        "codex",
        finder=lambda _: "codex",
        prompt_runner=FakeProcessRunner("\n".join(json.dumps(e) for e in events) + "\n"),
    )

    result = runner.run(request)

    assert result.ok is False
    assert result.error.code == "MARKDOWN_RUNNER_UNEXPECTED_ACTIVITY"


def test_codex_refuses_a_command_that_mentions_a_pdf(tmp_path):
    request = request_for(tmp_path)
    events = [
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": "cat paper.pdf -"},
        },
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps({"ok": True})},
        },
        {"type": "turn.completed"},
    ]
    runner = CodexMarkdownRunner(
        "codex",
        finder=lambda _: "codex",
        prompt_runner=FakeProcessRunner("\n".join(json.dumps(e) for e in events) + "\n"),
    )

    result = runner.run(request)

    assert result.ok is False
    assert result.error.code == "MARKDOWN_RUNNER_UNEXPECTED_ACTIVITY"
    assert ".pdf" in result.error.detail["command_summary"]


def test_a_staged_paper_that_differs_from_the_preparation_is_refused(tmp_path):
    request = request_for(tmp_path)
    (request.workspace / MARKDOWN_FILENAME).write_text("tampered", encoding="utf-8")
    runner = CodexMarkdownRunner(
        "codex", finder=lambda _: "codex", prompt_runner=FakeProcessRunner("")
    )

    result = runner.run(request)

    assert result.ok is False
    assert result.error.code == "MARKDOWN_WORKSPACE_INVALID"


def test_missing_executable_is_reported_without_running_anything(tmp_path):
    request = request_for(tmp_path)
    runner = CodexMarkdownRunner("nope", finder=lambda _: None)

    result = runner.run(request)

    assert result.ok is False
    assert result.error.code == "MARKDOWN_RUNNER_NOT_FOUND"
    assert runner.doctor().available is False


@pytest.mark.parametrize(
    "runner_factory",
    [
        lambda: ClaudeMarkdownRunner("claude", finder=lambda _: "claude"),
        lambda: CodexMarkdownRunner("codex", finder=lambda _: "codex"),
    ],
)
def test_doctor_needs_no_model_call(runner_factory) -> None:
    assert runner_factory().doctor().available is True
