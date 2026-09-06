from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from hydro_platform.config import CardGeneratorConfig


CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]
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
USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _run_command(
    command: Sequence[str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(
        part.strip()
        for part in (result.stdout or "", result.stderr or "")
        if part and part.strip()
    )


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


def _unexpected_item_types(events: list[dict[str, Any]]) -> list[str]:
    unexpected: set[str] = set()
    for event in events:
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if isinstance(item_type, str) and item_type in DISALLOWED_SMOKE_ITEM_TYPES:
            unexpected.add(item_type)
    return sorted(unexpected)


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


class CodexCliAdapter:
    """Codex CLI runtime checks and a bounded, non-domain smoke probe."""

    def __init__(
        self,
        config: CardGeneratorConfig,
        *,
        executable_finder: ExecutableFinder = shutil.which,
        runner: CommandRunner = _run_command,
    ):
        self.config = config
        self._executable_finder = executable_finder
        self._runner = runner

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
            "resolved_executable": resolved_executable,
            "configured_auth_mode": self.config.auth_mode,
            "detected_auth_mode": detected_auth_mode,
            "cli_version": cli_version,
            "checks": checks,
            "error": {"code": code, "message": message},
        }

    def preflight(self) -> dict[str, Any]:
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
        return {
            "schema_version": 1,
            "ok": True,
            "component": "card_generator",
            "checked_at": _now(),
            "adapter": self.config.adapter,
            "configured_executable": self.config.executable,
            "resolved_executable": executable,
            "configured_auth_mode": self.config.auth_mode,
            "detected_auth_mode": "chatgpt_account",
            "cli_version": cli_version,
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

        failed_events = [
            event
            for event in events
            if event.get("type") in {"turn.failed", "error"}
        ]
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
