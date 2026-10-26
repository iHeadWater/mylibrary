"""Card runners that read a prepared Markdown workspace, not a PDF.

Two local CLI runners and one test double implement ``ports.runner.CardRunner``:

* ``ClaudeMarkdownRunner`` gives the model one read-only tool, rooted at the
  workspace, and a JSON schema for the answer;
* ``CodexMarkdownRunner`` runs a plain ``exec`` in a read-only sandbox with the
  prompt on stdin;
* ``ScriptedRunner`` replays a fixed answer so the workflow can be tested
  without invoking a model.

All three share the same contract: the workspace's ``paper.md`` digest must
equal the prepared paper's digest before the call, and again afterwards. A
runner never receives a PDF path, and the local CLIs are constrained so they
cannot reach one.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from hydrolitagent.cards.adapters.runners.codex.events import (
    _classify_exec_failure,
    _combined_output,
    _last_agent_message,
    _parse_jsonl,
    _terminal_failure_events,
    _usage,
)
from hydrolitagent.cards.adapters.runners.diagnostics import (
    safe_exec_diagnostic,
    sanitize_diagnostic_text,
)
from hydrolitagent.cards.adapters.runners.workspace import (
    RESPONSE_FILENAME,
    SCHEMA_FILENAME,
    RunnerFailure,
    ensure_workspace_unchanged,
    read_workspace_markdown,
    record_output,
    write_schema,
)
from hydrolitagent.cards.card_generators.streaming import (
    ExecutionStopped,
    run_streaming_prompt,
)
from hydrolitagent.cards.config import ConnectionGuardConfig
from hydrolitagent.cards.infrastructure.toml import toml_string
from hydrolitagent.cards.ports.runner import (
    CardRunError,
    CardRunRequest,
    CardRunResult,
    RunnerDoctor,
)
from hydrolitagent.cards.progress import report_progress

# Kept as module-level aliases so the runner code below reads the same as
# before the helpers moved to ``workspace.py`` (shared with the HTTP runner).
_RunnerFailure = RunnerFailure
_workspace_markdown = read_workspace_markdown
_write_schema = write_schema
_record_output = record_output

# Item types that mean the runner left the prepared workspace: MCP servers,
# web search and sub-agent collaboration are all forbidden here.
FORBIDDEN_ITEM_TYPES = frozenset(
    {"mcp_tool_call", "web_search", "web_search_call", "collab_tool_call"}
)
_ALLOWED_CLAUDE_TOOLS = frozenset({"Read", "StructuredOutput"})


def _failure(
    runner_id: str,
    code: str,
    message: str,
    *,
    model_invoked: bool,
    started: float,
    detail: Mapping[str, Any] | None = None,
    warnings: Sequence[str] = (),
) -> CardRunResult:
    return CardRunResult(
        runner_id=runner_id,
        ok=False,
        error=CardRunError(code=code, message=message, detail=detail),
        model_invoked=model_invoked,
        duration_seconds=round(time.monotonic() - started, 2),
        warnings=tuple(warnings),
    )


def _read_outside_workspace(path: str, workspace: Path) -> bool:
    """True when ``path`` resolves outside the staged run directory."""

    try:
        return not Path(path).resolve().is_relative_to(workspace.resolve())
    except (OSError, ValueError):
        return True


def _claude_read_activity(
    events: Sequence[Any], workspace: Path
) -> tuple[int, list[str]]:
    """Validate tool activity; return the read count and any PDF-touch warnings.

    Any tool other than the read-only file reader is a protocol failure. Any
    read outside the workspace is a protocol failure. Reading a ``.pdf`` is
    recorded as a warning because the file should not exist in the workspace,
    but a model that reaches for one is telling us the prompt or the staging
    is wrong.
    """

    reads = 0
    warnings: list[str] = []
    for event in events:
        if not isinstance(event, Mapping) or event.get("type") not in {"assistant", "user"}:
            continue
        message = event.get("message")
        if not isinstance(message, Mapping):
            continue
        blocks = message.get("content", [])
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, Mapping) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            if name not in _ALLOWED_CLAUDE_TOOLS:
                raise _RunnerFailure(
                    "MARKDOWN_RUNNER_UNEXPECTED_ACTIVITY",
                    f"runner 调用了只读读取之外的工具：{name}",
                )
            if name != "Read":
                continue
            data = block.get("input")
            target = data.get("file_path") if isinstance(data, Mapping) else None
            if not isinstance(target, str) or not target.strip():
                raise _RunnerFailure(
                    "MARKDOWN_RUNNER_UNEXPECTED_ACTIVITY", "读取工具缺少文件路径"
                )
            if _read_outside_workspace(target, workspace):
                raise _RunnerFailure(
                    "MARKDOWN_RUNNER_UNEXPECTED_ACTIVITY",
                    "runner 读取了运行目录之外的文件",
                )
            if Path(target).suffix.lower() == ".pdf":
                warnings.append("RUNNER_TOUCHED_PDF_PATH")
            reads += 1
    return reads, warnings


class ClaudeMarkdownRunner:
    """Read-only file reader rooted at the run directory, with a JSON schema."""

    runner_id = "claude_markdown"

    def __init__(
        self,
        executable: str,
        *,
        environment: Mapping[str, str] | None = None,
        connection_guard: ConnectionGuardConfig | None = None,
        finder=shutil.which,
        prompt_runner=run_streaming_prompt,
    ) -> None:
        self.executable = executable
        self.environment = dict(environment or {})
        self.connection_guard = connection_guard
        self._finder = finder
        self._prompt_runner = prompt_runner

    def doctor(self) -> RunnerDoctor:
        found = self._finder(self.executable)
        return RunnerDoctor(
            runner_id=self.runner_id,
            available=bool(found),
            detail=f"resolved={found}" if found else "找不到可执行的本地命令行",
            fix=None if found else "安装该命令行，或在配置中指定绝对路径",
        )

    def run(self, request: CardRunRequest) -> CardRunResult:
        started = time.monotonic()
        invoked = False
        warnings: list[str] = []
        try:
            markdown = _workspace_markdown(request)
            schema_path = _write_schema(request)
            workspace = Path(request.workspace).resolve()
            if not self._finder(self.executable):
                raise _RunnerFailure("MARKDOWN_RUNNER_NOT_FOUND", "找不到配置的本地命令行")
            command = [
                self.executable,
                "--print",
                "--safe-mode",
                "--restricted",
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers":{}}',
                "--tools",
                "Read",
                "--allowedTools",
                "Read",
                "--add-dir",
                str(workspace),
                "--no-session-persistence",
                "--output-format",
                "stream-json",
                "--verbose",
                "--json-schema",
                json.dumps(request.output_schema, ensure_ascii=False, separators=(",", ":")),
            ]
            if request.model:
                command += ["--model", request.model]
            if request.reasoning_effort:
                command += ["--effort", request.reasoning_effort]
            report_progress(
                request.progress,
                "phase",
                message="模型正在只读运行目录中的 paper.md 与 figures/",
            )
            invoked = True
            completed = self._prompt_runner(
                command,
                request.prompt,
                request.timeout_seconds,
                self.environment,
                progress=request.progress,
                server="",
                connection_guard=self.connection_guard,
                cwd=str(workspace),
                provider_label="模型 CLI",
            )
            try:
                events = [
                    json.loads(line)
                    for line in (completed.stdout or "").splitlines()
                    if line.strip()
                ]
            except ValueError as exc:
                raise _RunnerFailure(
                    "MARKDOWN_RUNNER_PROTOCOL_ERROR", "runner 输出不是有效 JSON 事件"
                ) from exc
            if any(not isinstance(event, dict) for event in events):
                raise _RunnerFailure(
                    "MARKDOWN_RUNNER_PROTOCOL_ERROR", "runner 返回了非对象事件"
                )
            reads, activity_warnings = _claude_read_activity(events, workspace)
            warnings.extend(activity_warnings)
            terminal = [event for event in events if event.get("type") == "result"]
            if (
                completed.returncode
                or len(terminal) != 1
                or terminal[0].get("is_error") is True
                or terminal[0].get("subtype") != "success"
            ):
                raise _RunnerFailure(
                    "MARKDOWN_RUNNER_FAILED",
                    "runner 未成功完成；请检查本机登录、模型选择与服务可用性",
                    detail={"exit_code": completed.returncode},
                )
            output = terminal[0].get("structured_output")
            if not isinstance(output, Mapping):
                raise _RunnerFailure(
                    "MARKDOWN_RUNNER_OUTPUT_INVALID", "runner 没有返回所需结构化输出"
                )
            if reads == 0 and request.paper is not None:
                # A model that never opened a file cannot have quoted it; the
                # grounding checks will reject it, but say so plainly here.
                warnings.append("NO_FILE_READ_EVENTS")
            ensure_workspace_unchanged(request, markdown)
            saved = _record_output(request, output)
            return CardRunResult(
                runner_id=self.runner_id,
                ok=True,
                output=dict(output),
                model_invoked=True,
                model=request.model,
                reasoning_effort=request.reasoning_effort,
                usage=terminal[0].get("usage") if isinstance(terminal[0].get("usage"), Mapping) else None,
                duration_seconds=round(time.monotonic() - started, 2),
                warnings=tuple(warnings),
                unvalidated_output_path=saved,
            )
        except _RunnerFailure as exc:
            return _failure(
                self.runner_id,
                exc.code,
                str(exc),
                model_invoked=invoked,
                started=started,
                detail=exc.detail,
                warnings=warnings,
            )
        except subprocess.TimeoutExpired:
            return _failure(
                self.runner_id,
                "MARKDOWN_RUNNER_TIMEOUT",
                "runner 调用超时；本次不重试",
                model_invoked=invoked,
                started=started,
                warnings=warnings,
            )
        except ExecutionStopped as exc:
            return _failure(
                self.runner_id,
                exc.code,
                sanitize_diagnostic_text(str(exc)),
                model_invoked=invoked,
                started=started,
                detail=exc.diagnostic,
                warnings=warnings,
            )
        except (OSError, ValueError, TypeError) as exc:
            return _failure(
                self.runner_id,
                "MARKDOWN_RUNNER_IO_ERROR",
                f"runner 调用失败（{type(exc).__name__}）",
                model_invoked=invoked,
                started=started,
                warnings=warnings,
            )


def _pdf_commands(events: Sequence[Any]) -> list[str]:
    """Commands that mention a PDF: the one thing this pipeline must not touch."""

    found: list[str] = []
    for event in events:
        if not isinstance(event, Mapping) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, Mapping) or item.get("type") != "command_execution":
            continue
        rendered = " ".join(
            str(item.get(key)) for key in ("command", "aggregated_output") if item.get(key)
        )
        if re.search(r"\.pdf\b", rendered, re.IGNORECASE):
            found.append(sanitize_diagnostic_text(rendered))
    return found


class CodexMarkdownRunner:
    """Plain ``exec`` in a read-only sandbox with the prompt on stdin."""

    runner_id = "codex_markdown"

    def __init__(
        self,
        executable: str,
        *,
        environment: Mapping[str, str] | None = None,
        connection_guard: ConnectionGuardConfig | None = None,
        finder=shutil.which,
        prompt_runner=run_streaming_prompt,
    ) -> None:
        self.executable = executable
        self.environment = dict(environment or {})
        self.connection_guard = connection_guard
        self._finder = finder
        self._prompt_runner = prompt_runner

    def doctor(self) -> RunnerDoctor:
        found = self._finder(self.executable)
        return RunnerDoctor(
            runner_id=self.runner_id,
            available=bool(found),
            detail=f"resolved={found}" if found else "找不到可执行的本地命令行",
            fix=None if found else "安装该命令行，或在配置中指定绝对路径",
        )

    def run(self, request: CardRunRequest) -> CardRunResult:
        started = time.monotonic()
        invoked = False
        try:
            markdown = _workspace_markdown(request)
            schema_path = _write_schema(request)
            workspace = Path(request.workspace).resolve()
            if not self._finder(self.executable):
                raise _RunnerFailure("MARKDOWN_RUNNER_NOT_FOUND", "找不到配置的本地命令行")
            command = [
                self.executable,
                "exec",
                "--json",
                "--ephemeral",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--cd",
                str(workspace),
                "--color",
                "never",
                "--output-schema",
                str(schema_path),
                "--config",
                'approval_policy="never"',
                "--config",
                'web_search="disabled"',
                # No flag can drop the user's config file on every CLI version,
                # so empty the MCP table explicitly. The event check below is
                # what actually refuses a tool call: a flag is a request, an
                # observed ``mcp_tool_call`` is evidence.
                "--config",
                "mcp_servers={}",
                "--disable",
                "apps",
                "--disable",
                "plugins",
                "--disable",
                "multi_agent",
            ]
            if request.model:
                command += ["--model", request.model]
            if request.reasoning_effort:
                command += ["--config", "model_reasoning_effort=" + toml_string(request.reasoning_effort)]
            command.append("-")
            report_progress(
                request.progress,
                "phase",
                message="模型正在只读运行目录中的 paper.md 与 figures/",
            )
            invoked = True
            completed = self._prompt_runner(
                command,
                request.prompt,
                request.timeout_seconds,
                self.environment,
                progress=request.progress,
                server="",
                connection_guard=self.connection_guard,
                cwd=str(workspace),
                provider_label="模型 CLI",
            )
            try:
                events = _parse_jsonl(completed.stdout or "")
            except ValueError:
                if completed.returncode:
                    code, message = _classify_exec_failure(_combined_output(completed))
                    raise _RunnerFailure(code, message)
                raise _RunnerFailure(
                    "MARKDOWN_RUNNER_PROTOCOL_ERROR", "runner 未返回有效 JSONL 事件"
                )
            if completed.returncode or _terminal_failure_events(events):
                code, message = _classify_exec_failure(_combined_output(completed))
                raise _RunnerFailure(
                    code,
                    message,
                    detail=safe_exec_diagnostic(completed, code, stage="markdown_exec"),
                )
            if not any(event.get("type") == "turn.completed" for event in events):
                raise _RunnerFailure(
                    "MARKDOWN_RUNNER_PROTOCOL_ERROR", "模型回合未正常结束"
                )
            items = [
                event["item"]
                for event in events
                if event.get("type") == "item.completed" and isinstance(event.get("item"), dict)
            ]
            if any(
                item.get("type") in FORBIDDEN_ITEM_TYPES
                or str(item.get("type", "")).startswith("collab_")
                for item in items
            ):
                raise _RunnerFailure(
                    "MARKDOWN_RUNNER_UNEXPECTED_ACTIVITY",
                    "runner 调用了 MCP、联网搜索或其它 Agent",
                )
            warnings: list[str] = []
            pdf_commands = _pdf_commands(events)
            if pdf_commands:
                raise _RunnerFailure(
                    "MARKDOWN_RUNNER_UNEXPECTED_ACTIVITY",
                    "runner 试图读取 PDF；本流程只允许读取已转换的 Markdown",
                    detail={"command_summary": pdf_commands[0][:400]},
                )
            if any(item.get("type") == "command_execution" for item in items):
                warnings.append("SHELL_COMMAND_EXECUTED")
            try:
                output = json.loads(_last_agent_message(events) or "")
            except (ValueError, TypeError) as exc:
                raise _RunnerFailure(
                    "MARKDOWN_RUNNER_OUTPUT_INVALID", "runner 未返回有效 JSON 对象"
                ) from exc
            if not isinstance(output, Mapping):
                raise _RunnerFailure(
                    "MARKDOWN_RUNNER_OUTPUT_INVALID", "runner 输出必须是 JSON 对象"
                )
            ensure_workspace_unchanged(request, markdown)
            saved = _record_output(request, output)
            return CardRunResult(
                runner_id=self.runner_id,
                ok=True,
                output=dict(output),
                model_invoked=True,
                model=request.model,
                reasoning_effort=request.reasoning_effort,
                usage=_usage(events),
                duration_seconds=round(time.monotonic() - started, 2),
                warnings=tuple(warnings),
                unvalidated_output_path=saved,
            )
        except _RunnerFailure as exc:
            return _failure(
                self.runner_id,
                exc.code,
                str(exc),
                model_invoked=invoked,
                started=started,
                detail=exc.detail,
            )
        except subprocess.TimeoutExpired:
            return _failure(
                self.runner_id,
                "MARKDOWN_RUNNER_TIMEOUT",
                "runner 调用超时；本次不重试",
                model_invoked=invoked,
                started=started,
            )
        except ExecutionStopped as exc:
            return _failure(
                self.runner_id,
                exc.code,
                sanitize_diagnostic_text(str(exc)),
                model_invoked=invoked,
                started=started,
                detail=exc.diagnostic,
            )
        except (OSError, ValueError, TypeError) as exc:
            return _failure(
                self.runner_id,
                "MARKDOWN_RUNNER_IO_ERROR",
                f"runner 调用失败（{type(exc).__name__}）",
                model_invoked=invoked,
                started=started,
            )


class ScriptedRunner:
    """Deterministic runner for tests: replays one preset answer."""

    runner_id = "scripted"

    def __init__(
        self,
        output: Mapping[str, Any] | None = None,
        *,
        ok: bool = True,
        error: CardRunError | None = None,
        model_invoked: bool = True,
    ) -> None:
        self.output = deepcopy(dict(output)) if output is not None else None
        self.ok = ok
        self.error = error
        self.model_invoked = model_invoked
        self.requests: list[CardRunRequest] = []

    def doctor(self) -> RunnerDoctor:
        return RunnerDoctor(
            runner_id=self.runner_id, available=True, detail="测试替身，不需要外部程序"
        )

    def run(self, request: CardRunRequest) -> CardRunResult:
        self.requests.append(request)
        if not self.ok:
            return CardRunResult(
                runner_id=self.runner_id,
                ok=False,
                error=self.error
                or CardRunError("SCRIPTED_RUNNER_FAILED", "测试替身被要求返回失败"),
                model_invoked=self.model_invoked,
            )
        if self.output is None:
            return CardRunResult(
                runner_id=self.runner_id,
                ok=False,
                error=CardRunError(
                    "SCRIPTED_RUNNER_OUTPUT_MISSING", "测试替身没有预置输出"
                ),
                model_invoked=self.model_invoked,
            )
        return CardRunResult(
            runner_id=self.runner_id,
            ok=True,
            output=deepcopy(self.output),
            model_invoked=True,
        )


__all__ = [
    "FORBIDDEN_ITEM_TYPES",
    "RESPONSE_FILENAME",
    "SCHEMA_FILENAME",
    "ClaudeMarkdownRunner",
    "CodexMarkdownRunner",
    "ScriptedRunner",
]
