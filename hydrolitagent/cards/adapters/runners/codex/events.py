"""Decoding and classification of Codex CLI JSONL event streams.

Nothing here calls a model or touches the filesystem: every helper consumes the
child process's captured output and returns plain data.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

from hydrolitagent.cards.adapters.runners.codex.constants import (
    DISALLOWED_SMOKE_ITEM_TYPES,
    USAGE_FIELDS,
)
from hydrolitagent.cards.card_generators.connection_guard import is_reconnect_event


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(
        part.strip()
        for part in (result.stdout or "", result.stderr or "")
        if part and part.strip()
    )


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


__all__ = [
    "_classify_exec_failure",
    "_combined_output",
    "_last_agent_message",
    "_parse_jsonl",
    "_terminal_failure_events",
    "_unexpected_item_types",
    "_usage",
]
