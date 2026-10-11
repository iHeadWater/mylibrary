from __future__ import annotations

import threading
import time
from typing import Any, Callable

from hydrolitagent.cards.config import ConnectionGuardConfig


def is_reconnect_event(event: dict[str, Any]) -> bool:
    message = event.get("message")
    return (
        event.get("type") == "error"
        and isinstance(message, str)
        and message.lstrip().lower().startswith("reconnecting")
    )


class ConnectionGuard:
    """Independent of terminal output and of the provider's own retry counters."""

    def __init__(
        self, config: ConnectionGuardConfig, server: str, *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.server = server
        self.clock = clock
        self.started = self.last_progress = clock()
        self.recovery_started: float | None = None
        self.reconnect_events = 0
        self.pdf_calls = 0
        self.failure: tuple[str, str] | None = None
        self._lock = threading.Lock()

    def observe(self, event: dict[str, Any]) -> None:
        with self._lock:
            now = self.clock()
            # Never clear a latched stop, even if a late completion arrives.
            if self.failure is not None:
                return
            kind = event.get("type")
            if is_reconnect_event(event):
                self.reconnect_events += 1
                if self.recovery_started is None:
                    self.recovery_started = now
                if self.config.reconnect_stop_enabled and self.reconnect_events >= self.config.reconnect_event_limit:
                    self.failure = (
                        "CODEX_RECONNECT_LIMIT_REACHED",
                        f"本角色已收到 {self.reconnect_events} 次重连提示，达到上限，已停止本次调用",
                    )
                return
            item = event.get("item")
            if kind in {"item.started", "item.updated", "item.completed"} and isinstance(item, dict):
                item_type = item.get("type")
                if item_type in {"mcp_tool_call", "agent_message", "reasoning"}:
                    self.last_progress = now
                    # A local tool return alone cannot prove network recovery.
                    if kind == "item.started" or item_type in {"agent_message", "reasoning"}:
                        self.recovery_started = None
                if (
                    kind == "item.started" and item_type == "mcp_tool_call"
                    and item.get("server") == self.server
                    and item.get("tool") == "read_full_source_pdf"
                ):
                    self.pdf_calls += 1
                    if self.pdf_calls > self.config.pdf_tool_call_limit:
                        self.failure = (
                            "CODEX_PDF_READ_REPEAT_LIMIT",
                            "检测到重复整篇 PDF 调用超过上限，已停止本次调用",
                        )
            elif kind in {"thread.started", "turn.started", "turn.completed", "turn.failed"}:
                self.last_progress = now
                if kind == "turn.completed":
                    self.recovery_started = None

    def check(self) -> tuple[str, str] | None:
        with self._lock:
            now = self.clock()
            if self.failure is None:
                if (
                    self.config.reconnect_stop_enabled
                    and self.recovery_started is not None
                    and now - self.recovery_started >= self.config.recovery_timeout_seconds
                ):
                    self.failure = (
                        "CODEX_RECONNECT_TIMEOUT",
                        "连接中断后未在规定时间内恢复，已停止本次调用",
                    )
                elif now - self.last_progress >= self.config.idle_timeout_seconds:
                    self.failure = (
                        "CODEX_NO_PROGRESS_TIMEOUT",
                        "在规定时间内没有收到进展事件，已停止本次调用；这不等于确认模型没有思考",
                    )
            return self.failure

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = self.clock()
            return {
                "reconnect_stop_enabled": self.config.reconnect_stop_enabled,
                "reconnect_events": self.reconnect_events,
                "reconnect_event_limit": self.config.reconnect_event_limit,
                "pdf_tool_calls": self.pdf_calls,
                "pdf_tool_call_limit": self.config.pdf_tool_call_limit,
                "elapsed_seconds": round(now - self.started, 2),
                "seconds_without_progress": round(now - self.last_progress, 2),
                "recovery_timeout_seconds": self.config.recovery_timeout_seconds,
                "idle_timeout_seconds": self.config.idle_timeout_seconds,
            }
