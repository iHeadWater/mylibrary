from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from hydro_platform.config import CardGeneratorConfig
from hydro_platform.card_generators.streaming import ExecutionStopped, run_streaming_prompt
from hydro_platform.card_generators.connection_guard import is_reconnect_event
from hydro_platform.card_generators.proxy import codex_proxy_environment, proxy_summary
from hydro_platform.progress import ProgressCallback


CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]
PromptRunner = Callable[
    [Sequence[str], str, float, Mapping[str, str] | None],
    subprocess.CompletedProcess[str],
]
ExecutableFinder = Callable[[str], str | None]

SMOKE_TEST_VERSION = "codex-cli-smoke-v1"
SMOKE_TEST_EXPECTED_TEXT = "HYDRO_GENERATOR_OK"
SMOKE_TEST_PROMPT = (
    "这是水利科研知识平台的运行环境连通性测试。"
    "不要调用任何工具，不要读取或修改任何文件，不要联网搜索。"
    f"只输出字符串 {SMOKE_TEST_EXPECTED_TEXT}，不要添加标点、代码块或解释。"
)
DISALLOWED_SMOKE_ITEM_TYPES = frozenset(
    {"command_execution", "file_change", "mcp_tool_call", "web_search"}
)
DISALLOWED_GENERATION_ITEM_TYPES = frozenset(
    {"command_execution", "file_change", "web_search"}
)
GENERATION_PROTOCOL_VERSION = "evidence-card-generation-v3"
USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


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


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(
        part.strip()
        for part in (result.stdout or "", result.stderr or "")
        if part and part.strip()
    )


def _sanitize_diagnostic_text(value: str) -> str:
    sanitized = value.replace("\x00", " ")
    sanitized = USER_PROFILE_PATTERN.sub("%USERPROFILE%", sanitized)
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("<redacted>", sanitized)
    sanitized = " ".join(sanitized.split())
    if len(sanitized) > MAX_DIAGNOSTIC_SUMMARY_LENGTH:
        sanitized = sanitized[: MAX_DIAGNOSTIC_SUMMARY_LENGTH - 1].rstrip() + "…"
    return sanitized


def _event_diagnostic_parts(value: Any, *, key: str | None = None) -> list[str]:
    if isinstance(value, dict):
        parts: list[str] = []
        for child_key, child_value in value.items():
            parts.extend(_event_diagnostic_parts(child_value, key=str(child_key)))
        return parts
    if isinstance(value, list):
        parts = []
        for child in value:
            parts.extend(_event_diagnostic_parts(child, key=key))
        return parts
    if key not in DIAGNOSTIC_KEYS or not isinstance(value, (str, int, float, bool)):
        return []
    rendered = _sanitize_diagnostic_text(f"{key}={value}")
    return [rendered] if rendered else []


def _safe_exec_diagnostic(
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
                "server": _sanitize_diagnostic_text(str(item.get("server", "unknown"))),
                "tool": _sanitize_diagnostic_text(str(item.get("tool", "unknown"))),
                "summary": _sanitize_diagnostic_text(" | ".join(
                    _event_diagnostic_parts(item.get("error"), key="error")
                )) or "工具失败，CLI 未提供错误细节",
            }
        if event.get("type") in DIAGNOSTIC_EVENT_TYPES:
            parts = _event_diagnostic_parts(event)
            event_summaries.extend(parts)
            error_events.append(_sanitize_diagnostic_text(" | ".join(parts)))

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
        _sanitize_diagnostic_text(line) for line in stderr_lines[-6:]
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
    summary = _sanitize_diagnostic_text(" | ".join(unique_summaries))
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


def _timeout_text(value: str | bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""


def _terminal_failure_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last_completion = max(
        (index for index, event in enumerate(events) if event.get("type") == "turn.completed"),
        default=-1,
    )
    return [
        event for index, event in enumerate(events)
        if event.get("type") in {"turn.failed", "error"}
        and not (is_reconnect_event(event) and index < last_completion)
    ]


def _parse_jsonl(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"第 {line_number} 行不是有效 JSON") from exc
        if not isinstance(event, dict):
            raise ValueError(f"第 {line_number} 行不是 JSON 对象")
        events.append(event)
    if not events:
        raise ValueError("Codex CLI 没有返回 JSONL 事件")
    return events


def _classify_exec_failure(raw: str) -> tuple[str, str]:
    normalized = raw.casefold()
    if any(
        marker in normalized
        for marker in (
            "required mcp servers failed to initialize",
            "hydro_pdf_reader: handshaking with mcp server failed",
            "pdf mcp startup failed",
        )
    ):
        return (
            "PDF_READER_INITIALIZATION_FAILED",
            "专用 PDF 读取器未能完成初始化",
        )
    if any(
        marker in normalized
        for marker in (
            "invalid_json_schema",
            "invalid schema",
            "response_format",
            "output schema",
            "output-schema",
        )
    ):
        return (
            "CODEX_OUTPUT_SCHEMA_INVALID",
            "Codex 拒绝了制卡输出结构；请检查 schema 是否属于当前模型支持的 JSON Schema 子集",
        )
    if any(
        marker in normalized
        for marker in (
            "context_length_exceeded",
            "maximum context length",
            "context window",
            "too many tokens",
            "input too long",
        )
    ):
        return "CODEX_CONTEXT_LIMIT", "制卡输入超过了当前 Codex 模型的上下文限制"
    if any(
        marker in normalized
        for marker in (
            "stream disconnected",
            "stream_closed",
            "connection closed",
            "connection reset",
            "transport error",
            "server_error",
            "service unavailable",
            "503",
        )
    ):
        return "CODEX_SERVICE_UNAVAILABLE", "Codex 服务或连接在制卡过程中中断"
    if any(
        marker in normalized
        for marker in (
            "approval required",
            "permission denied",
            "operation not permitted",
            "sandbox denied",
            "access is denied",
        )
    ):
        return "CODEX_EXEC_PERMISSION_DENIED", "Codex 读取论文时受到权限或沙箱限制"
    if any(marker in normalized for marker in ("rate limit", "too many requests", "429")):
        return "CODEX_RATE_LIMITED", "Codex 模型调用受到速率限制"
    if any(
        marker in normalized
        for marker in (
            "usage limit",
            "quota",
            "credit",
            "limit reached",
            "额度",
        )
    ):
        return "CODEX_USAGE_LIMIT", "Codex 账号当前没有可用调用额度"
    if any(
        marker in normalized
        for marker in (
            "not logged in",
            "unauthorized",
            "authentication",
            "login required",
            "401",
        )
    ):
        return "CODEX_NOT_LOGGED_IN", "Codex 模型调用时认证失败"
    if any(
        marker in normalized
        for marker in (
            "model_reasoning_effort",
            "reasoning_effort",
            "reasoning effort",
        )
    ):
        return (
            "CODEX_REASONING_EFFORT_UNAVAILABLE",
            "配置的推理强度不被当前 Codex 模型支持",
        )
    if any(
        marker in normalized
        for marker in (
            "model not found",
            "unsupported model",
            "unknown model",
            "does not exist",
        )
    ):
        return "CODEX_MODEL_UNAVAILABLE", "配置的 Codex 模型当前不可用"
    return "CODEX_EXEC_FAILED", "Codex 模型调用失败"


def _unexpected_item_types(
    events: list[dict[str, Any]],
    *,
    disallowed: frozenset[str] = DISALLOWED_SMOKE_ITEM_TYPES,
) -> list[str]:
    unexpected: set[str] = set()
    for event in events:
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if isinstance(item_type, str) and item_type in disallowed:
            unexpected.add(item_type)
    return sorted(unexpected)


def _pdf_access_diagnostic(
    events: list[dict[str, Any]],
    *,
    server_name: str,
    output: Any,
) -> dict[str, Any]:
    mcp_events: list[dict[str, str]] = []
    for event in events:
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "mcp_tool_call":
            continue
        observed_server = item.get("server") or item.get("server_name")
        if isinstance(observed_server, str) and observed_server != server_name:
            continue
        observed: dict[str, str] = {}
        if isinstance(observed_server, str):
            observed["server"] = observed_server
        observed_tool = item.get("tool") or item.get("tool_name") or item.get("name")
        if isinstance(observed_tool, str):
            observed["tool"] = observed_tool
        observed_status = item.get("status")
        if isinstance(observed_status, str):
            observed["status"] = observed_status
        error_parts = _event_diagnostic_parts(item.get("error"), key="error")
        if error_parts:
            observed["error_summary"] = _sanitize_diagnostic_text(
                " | ".join(error_parts)
            )
        event_type = event.get("type")
        if isinstance(event_type, str):
            observed["event"] = event_type
        mcp_events.append(observed)

    model_claim: dict[str, Any] = {}
    if isinstance(output, dict):
        for field in (
            "source_read_status",
            "source_page_count",
            "visual_content_status",
        ):
            value = output.get(field)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                model_claim[field] = value
    return {
        "stage": "pdf_access_verification",
        "mcp_event_count": len(mcp_events),
        "mcp_events": mcp_events[:20],
        "model_claim": model_claim,
    }


def _last_agent_message(events: list[dict[str, Any]]) -> str | None:
    messages: list[str] = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if isinstance(text, str):
            messages.append(text)
    return messages[-1] if messages else None


def _usage(events: list[dict[str, Any]]) -> dict[str, int] | None:
    for event in reversed(events):
        if event.get("type") != "turn.completed":
            continue
        raw_usage = event.get("usage")
        if not isinstance(raw_usage, dict):
            return None
        result = {
            field: value
            for field in USAGE_FIELDS
            if isinstance((value := raw_usage.get(field)), int)
            and not isinstance(value, bool)
        }
        return result or None
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _toml_string(value: str) -> str:
    """JSON strings are valid TOML basic strings for these scalar values."""

    return json.dumps(value, ensure_ascii=False)


def _toml_string_map(values: Mapping[str, str]) -> str:
    """Encode a string map as a TOML inline table for Codex CLI overrides."""

    entries = (
        f"{key}={_toml_string(value)}" for key, value in sorted(values.items())
    )
    return "{" + ",".join(entries) + "}"


def _source_pdf_access_from_receipt(
    receipt: Any,
    *,
    expected_sha256: str,
    server_name: str,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
        return (
            None,
            "CODEX_PDF_NOT_ACCESSED",
            "Codex 已完成调用，但专用 PDF 读取器没有留下有效回执",
        )
    if receipt.get("source_sha256") != expected_sha256:
        return (
            None,
            "CODEX_PDF_BINDING_MISMATCH",
            "PDF 读取回执与本次任务绑定的文件指纹不一致",
        )
    if receipt.get("inspected") is not True:
        return (
            None,
            "CODEX_PDF_NOT_ACCESSED",
            "Codex 没有通过专用 PDF 读取器检查本次原始 PDF",
        )
    page_count = receipt.get("page_count")
    if (
        isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or page_count < 1
    ):
        return (
            None,
            "CODEX_PDF_RECEIPT_INVALID",
            "专用 PDF 读取器没有返回有效页数",
        )
    raw_pages = receipt.get("pages")
    if not isinstance(raw_pages, dict):
        raw_pages = {}
    served_pages: set[int] = set()
    visual_pages: set[int] = set()
    for raw_page, details in raw_pages.items():
        try:
            page = int(raw_page)
        except (TypeError, ValueError):
            continue
        if not 1 <= page <= page_count or not isinstance(details, dict):
            continue
        served_pages.add(page)
        if details.get("image_delivered") is True:
            visual_pages.add(page)
    expected_pages = set(range(1, page_count + 1))
    if served_pages != expected_pages:
        return (
            None,
            "CODEX_PDF_NOT_FULLY_ACCESSED",
            f"Codex 只读取了原始 PDF 的 {len(served_pages)}/{page_count} 页",
        )
    if visual_pages != expected_pages:
        return (
            None,
            "CODEX_PDF_VISUALS_NOT_ACCESSED",
            f"Codex 只取得了原始 PDF 的 {len(visual_pages)}/{page_count} 个页面图像",
        )
    return (
        {
            "verified": True,
            "method": "bound_local_pdf_mcp",
            "server_name": server_name,
            "receipt_schema_version": 1,
            "page_count": page_count,
            "pages_served": len(served_pages),
            "visual_pages_served": len(visual_pages),
        },
        None,
        None,
    )


class CodexCliAdapter:
    """Codex CLI runtime checks and a bounded, non-domain smoke probe."""

    def __init__(
        self,
        config: CardGeneratorConfig,
        *,
        executable_finder: ExecutableFinder = shutil.which,
        runner: CommandRunner = _run_command,
        prompt_runner: PromptRunner = _run_prompt_command,
        progress: ProgressCallback | None = None,
    ):
        self.config = config
        self._executable_finder = executable_finder
        self._runner = runner
        if runner is _run_command:
            # Includes version/login-status and smoke calls; no global env assignment.
            self._runner = lambda command, timeout: runner(
                command, timeout, codex_proxy_environment(self.config.proxy),
            )
        delegate_prompt_runner = prompt_runner
        if prompt_runner is _run_prompt_command:
            delegate_prompt_runner = lambda command, prompt, timeout, environment: run_streaming_prompt(
                command, prompt, timeout, environment,
                progress=progress, server=config.pdf_reader.server_name,
                connection_guard=config.connection_guard,
            )
        self._prompt_runner = lambda command, prompt, timeout, environment: delegate_prompt_runner(
            command, prompt, timeout, codex_proxy_environment(self.config.proxy, environment),
        )

    def _failure(
        self,
        checks: list[dict[str, str]],
        code: str,
        message: str,
        *,
        resolved_executable: str | None,
        cli_version: str | None = None,
        detected_auth_mode: str | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": False,
            "component": "card_generator",
            "checked_at": _now(),
            "adapter": self.config.adapter,
            "configured_executable": self.config.executable,
            "proxy": proxy_summary(self.config.proxy),
            "resolved_executable": resolved_executable,
            "configured_auth_mode": self.config.auth_mode,
            "detected_auth_mode": detected_auth_mode,
            "cli_version": cli_version,
            "checks": checks,
            "error": {"code": code, "message": message},
        }

    def preflight(self, *, check_pdf_reader: bool = True) -> dict[str, Any]:
        checks: list[dict[str, str]] = []
        executable = self._executable_finder(self.config.executable)
        if executable is None:
            checks.append(
                _check(
                    "executable",
                    "fail",
                    f"找不到配置的 Codex CLI：{self.config.executable}",
                )
            )
            return self._failure(
                checks,
                "CODEX_CLI_NOT_FOUND",
                "找不到 Codex CLI；请安装后检查 card_generator.executable",
                resolved_executable=None,
            )

        checks.append(_check("executable", "pass", "已找到 Codex CLI 可执行程序"))
        try:
            version_result = self._runner(
                [executable, "--version"],
                self.config.preflight_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            checks.append(_check("version", "fail", "Codex CLI 版本检查超时"))
            return self._failure(
                checks,
                "CODEX_CLI_TIMEOUT",
                "Codex CLI 版本检查超时",
                resolved_executable=executable,
            )
        except (OSError, subprocess.SubprocessError):
            checks.append(_check("version", "fail", "Codex CLI 无法启动"))
            return self._failure(
                checks,
                "CODEX_CLI_UNAVAILABLE",
                "Codex CLI 已找到但无法启动",
                resolved_executable=executable,
            )

        version_output = _combined_output(version_result)
        if version_result.returncode != 0 or not version_output:
            checks.append(_check("version", "fail", "Codex CLI 未返回有效版本"))
            return self._failure(
                checks,
                "CODEX_CLI_UNAVAILABLE",
                "Codex CLI 版本检查失败",
                resolved_executable=executable,
            )

        cli_version = version_output.splitlines()[0].strip()
        checks.append(_check("version", "pass", f"Codex CLI 可运行：{cli_version}"))

        try:
            auth_result = self._runner(
                [executable, "login", "status"],
                self.config.preflight_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            checks.append(_check("authentication", "fail", "Codex 登录状态检查超时"))
            return self._failure(
                checks,
                "CODEX_CLI_TIMEOUT",
                "Codex 登录状态检查超时",
                resolved_executable=executable,
                cli_version=cli_version,
            )
        except (OSError, subprocess.SubprocessError):
            checks.append(_check("authentication", "fail", "无法检查 Codex 登录状态"))
            return self._failure(
                checks,
                "CODEX_CLI_UNAVAILABLE",
                "Codex CLI 无法执行登录状态检查",
                resolved_executable=executable,
                cli_version=cli_version,
            )

        auth_output = _combined_output(auth_result)
        normalized_auth = auth_output.casefold()
        if auth_result.returncode != 0:
            checks.append(_check("authentication", "fail", "Codex CLI 当前未登录"))
            return self._failure(
                checks,
                "CODEX_NOT_LOGGED_IN",
                "Codex CLI 当前未登录；请先使用 ChatGPT 账号登录",
                resolved_executable=executable,
                cli_version=cli_version,
            )

        if any(
            marker in normalized_auth
            for marker in ("api key", "api-key", "api_key")
        ):
            checks.append(
                _check(
                    "authentication",
                    "fail",
                    "检测到 API Key 登录，与当前 ChatGPT 账号认证要求不一致",
                )
            )
            return self._failure(
                checks,
                "CODEX_AUTH_MODE_MISMATCH",
                "当前要求使用 ChatGPT 账号认证，但 Codex CLI 报告为 API Key 登录",
                resolved_executable=executable,
                cli_version=cli_version,
                detected_auth_mode="api_key",
            )

        if "chatgpt" not in normalized_auth:
            checks.append(
                _check(
                    "authentication",
                    "fail",
                    "Codex CLI 已返回成功，但无法确认是否使用 ChatGPT 账号",
                )
            )
            return self._failure(
                checks,
                "CODEX_AUTH_MODE_UNKNOWN",
                "无法从 Codex CLI 输出确认 ChatGPT 账号登录方式",
                resolved_executable=executable,
                cli_version=cli_version,
                detected_auth_mode="unknown",
            )

        checks.append(
            _check(
                "authentication",
                "pass",
                "已确认 Codex CLI 使用 ChatGPT 账号登录",
            )
        )
        if not check_pdf_reader:
            return {
                "schema_version": 1, "ok": True, "component": "card_generator",
                "resolved_executable": executable, "cli_version": cli_version,
                "detected_auth_mode": "chatgpt_account", "checks": checks,
                "proxy": proxy_summary(self.config.proxy),
            }
        reader = self.config.pdf_reader
        if not reader.server_file.is_file():
            checks.append(
                _check("pdf_reader_server", "fail", "项目内置 PDF MCP 服务文件不存在")
            )
            return self._failure(
                checks,
                "PDF_READER_SERVER_NOT_FOUND",
                "找不到项目内置 PDF MCP 服务文件；请检查 card_generator.pdf_reader.server_file",
                resolved_executable=executable,
                cli_version=cli_version,
                detected_auth_mode="chatgpt_account",
            )
        checks.append(
            _check("pdf_reader_server", "pass", "项目内置只读 PDF MCP 服务文件可用")
        )

        dependency_requests = {
            "python": reader.python_executable or sys.executable,
            "pdfinfo": reader.pdfinfo_executable,
            "pdftotext": reader.pdftotext_executable,
            "pdftoppm": reader.pdftoppm_executable,
        }
        resolved_dependencies: dict[str, str] = {}
        for name, requested in dependency_requests.items():
            resolved = self._executable_finder(requested)
            if resolved is None:
                checks.append(
                    _check(
                        f"pdf_reader_{name}",
                        "fail",
                        f"找不到 PDF 读取依赖：{name}",
                    )
                )
                return self._failure(
                    checks,
                    "PDF_READER_DEPENDENCY_NOT_FOUND",
                    f"找不到 PDF 读取依赖 {name}；请检查 card_generator.pdf_reader 配置",
                    resolved_executable=executable,
                    cli_version=cli_version,
                    detected_auth_mode="chatgpt_account",
                )
            resolved_dependencies[name] = resolved
            checks.append(
                _check(
                    f"pdf_reader_{name}",
                    "pass",
                    f"已找到 PDF 读取依赖：{name}",
                )
            )
        return {
            "schema_version": 1,
            "ok": True,
            "component": "card_generator",
            "checked_at": _now(),
            "adapter": self.config.adapter,
            "configured_executable": self.config.executable,
            "resolved_executable": executable,
            "configured_auth_mode": self.config.auth_mode,
            "proxy": proxy_summary(self.config.proxy),
            "detected_auth_mode": "chatgpt_account",
            "cli_version": cli_version,
            "pdf_reader": {
                "adapter": reader.adapter,
                "server_name": reader.server_name,
                "server_file": str(reader.server_file),
                "resolved_python_executable": resolved_dependencies["python"],
                "resolved_pdfinfo_executable": resolved_dependencies["pdfinfo"],
                "resolved_pdftotext_executable": resolved_dependencies["pdftotext"],
                "resolved_pdftoppm_executable": resolved_dependencies["pdftoppm"],
                "render_dpi": reader.render_dpi,
                "max_pages_per_call": reader.max_pages_per_call,
                "output_token_limit": reader.output_token_limit,
            },
            "checks": checks,
        }

    def _smoke_failure(
        self,
        preflight_result: dict[str, Any],
        checks: list[dict[str, str]],
        code: str,
        message: str,
        *,
        model_invoked: bool,
        unexpected_item_types: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": False,
            "component": "card_generator",
            "operation": "smoke_test",
            "checked_at": _now(),
            "adapter": self.config.adapter,
            "resolved_executable": preflight_result.get("resolved_executable"),
            "cli_version": preflight_result.get("cli_version"),
            "configured_auth_mode": self.config.auth_mode,
            "detected_auth_mode": preflight_result.get("detected_auth_mode"),
            "configured_model": self.config.model,
            "model_source": "configured" if self.config.model else "codex_default",
            "configured_reasoning_effort": self.config.reasoning_effort,
            "reasoning_effort_source": (
                "configured" if self.config.reasoning_effort else "model_default"
            ),
            "probe_version": SMOKE_TEST_VERSION,
            "isolated_workspace": True,
            "sandbox": "read-only",
            "ephemeral": True,
            "model_invoked": model_invoked,
            "unexpected_item_types": unexpected_item_types or [],
            "checks": checks,
            "error": {"code": code, "message": message},
        }

    def smoke_test(self) -> dict[str, Any]:
        preflight_result = self.preflight()
        checks = list(preflight_result.get("checks", []))
        if not preflight_result.get("ok"):
            checks.append(
                _check(
                    "model_invocation",
                    "skip",
                    "运行环境预检未通过，未调用模型",
                )
            )
            return self._smoke_failure(
                preflight_result,
                checks,
                preflight_result["error"]["code"],
                preflight_result["error"]["message"],
                model_invoked=False,
            )

        executable = preflight_result["resolved_executable"]
        try:
            with tempfile.TemporaryDirectory(
                prefix="hydro-generator-smoke-"
            ) as temporary_directory:
                isolated_workspace = Path(temporary_directory).resolve()
                command = [
                    executable,
                    "exec",
                    "--json",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "--color",
                    "never",
                    "--cd",
                    str(isolated_workspace),
                ]
                if self.config.model is not None:
                    command.extend(["--model", self.config.model])
                if self.config.reasoning_effort is not None:
                    command.extend(
                        [
                            "--config",
                            (
                                "model_reasoning_effort="
                                f'"{self.config.reasoning_effort}"'
                            ),
                        ]
                    )
                command.append(SMOKE_TEST_PROMPT)
                exec_result = self._runner(
                    command,
                    self.config.smoke_test_timeout_seconds,
                )
        except subprocess.TimeoutExpired:
            checks.append(_check("model_invocation", "fail", "Codex 最小调用超时"))
            return self._smoke_failure(
                preflight_result,
                checks,
                "CODEX_SMOKE_TIMEOUT",
                "Codex 最小模型调用超时",
                model_invoked=True,
            )
        except (OSError, subprocess.SubprocessError):
            checks.append(_check("model_invocation", "fail", "Codex CLI 调用失败"))
            return self._smoke_failure(
                preflight_result,
                checks,
                "CODEX_CLI_UNAVAILABLE",
                "Codex CLI 无法启动最小模型调用",
                model_invoked=True,
            )

        if exec_result.returncode != 0:
            code, message = _classify_exec_failure(_combined_output(exec_result))
            checks.append(_check("model_invocation", "fail", message))
            return self._smoke_failure(
                preflight_result,
                checks,
                code,
                message,
                model_invoked=True,
            )

        try:
            events = _parse_jsonl(exec_result.stdout or "")
        except ValueError:
            checks.append(
                _check(
                    "model_invocation",
                    "fail",
                    "Codex CLI 未返回有效 JSONL 事件",
                )
            )
            return self._smoke_failure(
                preflight_result,
                checks,
                "CODEX_EXEC_PROTOCOL_ERROR",
                "Codex CLI 返回格式不符合 JSONL 协议",
                model_invoked=True,
            )

        failed_events = _terminal_failure_events(events)
        if failed_events:
            classification_input = json.dumps(failed_events, ensure_ascii=False)
            code, message = _classify_exec_failure(classification_input)
            checks.append(_check("model_invocation", "fail", message))
            return self._smoke_failure(
                preflight_result,
                checks,
                code,
                message,
                model_invoked=True,
            )

        unexpected = _unexpected_item_types(events)
        if unexpected:
            checks.append(
                _check(
                    "model_invocation",
                    "fail",
                    "最小调用出现了不允许的工具活动",
                )
            )
            return self._smoke_failure(
                preflight_result,
                checks,
                "CODEX_SMOKE_UNEXPECTED_ACTIVITY",
                "最小调用不得执行命令、修改文件、调用 MCP 或联网搜索",
                model_invoked=True,
                unexpected_item_types=unexpected,
            )

        if not any(event.get("type") == "turn.completed" for event in events):
            checks.append(_check("model_invocation", "fail", "Codex 回合没有正常完成"))
            return self._smoke_failure(
                preflight_result,
                checks,
                "CODEX_EXEC_PROTOCOL_ERROR",
                "Codex CLI 没有返回 turn.completed 事件",
                model_invoked=True,
            )

        final_message = _last_agent_message(events)
        if final_message is None or final_message.strip() != SMOKE_TEST_EXPECTED_TEXT:
            checks.append(
                _check(
                    "expected_response",
                    "fail",
                    "模型没有返回预期的固定标记",
                )
            )
            return self._smoke_failure(
                preflight_result,
                checks,
                "CODEX_SMOKE_OUTPUT_INVALID",
                "Codex 模型调用成功，但响应不符合最小探针协议",
                model_invoked=True,
            )

        checks.extend(
            [
                _check("model_invocation", "pass", "Codex 最小模型调用已完成"),
                _check("expected_response", "pass", "模型返回了预期固定标记"),
            ]
        )
        return {
            "schema_version": 1,
            "ok": True,
            "component": "card_generator",
            "operation": "smoke_test",
            "checked_at": _now(),
            "adapter": self.config.adapter,
            "resolved_executable": executable,
            "cli_version": preflight_result["cli_version"],
            "configured_auth_mode": self.config.auth_mode,
            "detected_auth_mode": preflight_result["detected_auth_mode"],
            "configured_model": self.config.model,
            "model_source": "configured" if self.config.model else "codex_default",
            "configured_reasoning_effort": self.config.reasoning_effort,
            "reasoning_effort_source": (
                "configured" if self.config.reasoning_effort else "model_default"
            ),
            "probe_version": SMOKE_TEST_VERSION,
            "isolated_workspace": True,
            "sandbox": "read-only",
            "ephemeral": True,
            "model_invoked": True,
            "unexpected_item_types": [],
            "usage": _usage(events),
            "checks": checks,
        }

    def _generation_failure(
        self,
        preflight_result: dict[str, Any],
        code: str,
        message: str,
        *,
        model_invoked: bool,
        unexpected_item_types: list[str] | None = None,
        diagnostic: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = {
            "schema_version": 1,
            "ok": False,
            "component": "card_generator",
            "operation": "evidence_card_generation",
            "checked_at": _now(),
            "adapter": self.config.adapter,
            "resolved_executable": preflight_result.get("resolved_executable"),
            "cli_version": preflight_result.get("cli_version"),
            "configured_auth_mode": self.config.auth_mode,
            "detected_auth_mode": preflight_result.get("detected_auth_mode"),
            "configured_model": self.config.model,
            "model_source": "configured" if self.config.model else "codex_default",
            "configured_reasoning_effort": self.config.reasoning_effort,
            "reasoning_effort_source": (
                "configured" if self.config.reasoning_effort else "model_default"
            ),
            "generation_protocol_version": GENERATION_PROTOCOL_VERSION,
            "sandbox": "read-only",
            "ephemeral": True,
            "model_invoked": model_invoked,
            "unexpected_item_types": unexpected_item_types or [],
            "error": {"code": code, "message": message},
        }
        if diagnostic is not None:
            result["diagnostic"] = diagnostic
        return result

