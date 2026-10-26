"""Bounded, non-domain smoke probe for a configured Codex CLI.

The probe makes exactly one tiny model call inside a temporary read-only
workspace. It never runs card generation and never reads user PDFs.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hydrolitagent.cards.adapters.runners.codex.common import _check, _now
from hydrolitagent.cards.adapters.runners.codex.constants import (
    SMOKE_TEST_EXPECTED_TEXT,
    SMOKE_TEST_PROMPT,
    SMOKE_TEST_VERSION,
)
from hydrolitagent.cards.adapters.runners.codex.events import (
    _classify_exec_failure,
    _combined_output,
    _last_agent_message,
    _parse_jsonl,
    _terminal_failure_events,
    _unexpected_item_types,
    _usage,
)


def build_smoke_failure(
    adapter: Any,
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
        "adapter": adapter.config.adapter,
        "resolved_executable": preflight_result.get("resolved_executable"),
        "cli_version": preflight_result.get("cli_version"),
        "configured_auth_mode": adapter.config.auth_mode,
        "detected_auth_mode": preflight_result.get("detected_auth_mode"),
        "configured_model": adapter.config.model,
        "model_source": "configured" if adapter.config.model else "codex_default",
        "configured_reasoning_effort": adapter.config.reasoning_effort,
        "reasoning_effort_source": (
            "configured" if adapter.config.reasoning_effort else "model_default"
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


def run_smoke_test(adapter: Any) -> dict[str, Any]:
    preflight_result = adapter.preflight()
    checks = list(preflight_result.get("checks", []))
    if not preflight_result.get("ok"):
        checks.append(
            _check(
                "model_invocation",
                "skip",
                "运行环境预检未通过，未调用模型",
            )
        )
        return adapter._smoke_failure(
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
            if adapter.config.model is not None:
                command.extend(["--model", adapter.config.model])
            if adapter.config.reasoning_effort is not None:
                command.extend(
                    [
                        "--config",
                        (
                            "model_reasoning_effort="
                            f'"{adapter.config.reasoning_effort}"'
                        ),
                    ]
                )
            command.append(SMOKE_TEST_PROMPT)
            exec_result = adapter._runner(
                command,
                adapter.config.smoke_test_timeout_seconds,
            )
    except subprocess.TimeoutExpired:
        checks.append(_check("model_invocation", "fail", "Codex 最小调用超时"))
        return adapter._smoke_failure(
            preflight_result,
            checks,
            "CODEX_SMOKE_TIMEOUT",
            "Codex 最小模型调用超时",
            model_invoked=True,
        )
    except (OSError, subprocess.SubprocessError):
        checks.append(_check("model_invocation", "fail", "Codex CLI 调用失败"))
        return adapter._smoke_failure(
            preflight_result,
            checks,
            "CODEX_CLI_UNAVAILABLE",
            "Codex CLI 无法启动最小模型调用",
            model_invoked=True,
        )

    if exec_result.returncode != 0:
        code, message = _classify_exec_failure(_combined_output(exec_result))
        checks.append(_check("model_invocation", "fail", message))
        return adapter._smoke_failure(
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
        return adapter._smoke_failure(
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
        return adapter._smoke_failure(
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
        return adapter._smoke_failure(
            preflight_result,
            checks,
            "CODEX_SMOKE_UNEXPECTED_ACTIVITY",
            "最小调用不得执行命令、修改文件、调用 MCP 或联网搜索",
            model_invoked=True,
            unexpected_item_types=unexpected,
        )

    if not any(event.get("type") == "turn.completed" for event in events):
        checks.append(_check("model_invocation", "fail", "Codex 回合没有正常完成"))
        return adapter._smoke_failure(
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
        return adapter._smoke_failure(
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
        "adapter": adapter.config.adapter,
        "resolved_executable": executable,
        "cli_version": preflight_result["cli_version"],
        "configured_auth_mode": adapter.config.auth_mode,
        "detected_auth_mode": preflight_result["detected_auth_mode"],
        "configured_model": adapter.config.model,
        "model_source": "configured" if adapter.config.model else "codex_default",
        "configured_reasoning_effort": adapter.config.reasoning_effort,
        "reasoning_effort_source": (
            "configured" if adapter.config.reasoning_effort else "model_default"
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


__all__ = ["build_smoke_failure", "run_smoke_test"]
