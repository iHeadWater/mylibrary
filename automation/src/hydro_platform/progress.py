from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable, TextIO


ProgressCallback = Callable[[dict[str, Any]], None]
ROLE_LABELS = {
    "card_writer": "全文阅读与详细制卡",
    "fact_extractor_a": "事实提取 A",
    "fact_extractor_b": "事实提取 B",
    "fact_adjudicator": "事实裁决",
    "critical_analyst": "批判分析",
    "card_synthesizer": "卡片综合",
    "adversarial_reviewer": "对抗复核",
}


def report_progress(callback: ProgressCallback | None, event: str, **fields: Any) -> None:
    if callback is not None:
        callback({"event": event, **fields})


def _duration(seconds: float) -> str:
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d}:{seconds:02d}"


class ConsoleProgress:
    """Human progress on stderr only; a heartbeat is not evidence of model activity."""

    def __init__(
        self, *, enabled: bool = True, heartbeat_interval_seconds: float = 15,
        stream: TextIO | None = None,
    ) -> None:
        self.enabled = enabled
        self.interval = heartbeat_interval_seconds
        self.stream = stream if stream is not None else sys.stderr
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = self._stage_started = self._last_event = time.monotonic()
        self._stage = "准备"
        self._activity = "检查 Zotero、任务及 PDF"

    def __enter__(self) -> ConsoleProgress:
        self._started = self._stage_started = self._last_event = time.monotonic()
        if self.enabled:
            self({"event": "phase", "message": self._activity})
            self._thread = threading.Thread(target=self._heartbeat, daemon=True)
            self._thread.start()
        return self

    def _write(self, message: str) -> None:
        # An unavailable terminal must not fail or retry a costly model operation.
        try:
            elapsed = _duration(time.monotonic() - self._started)
            print(f"[AI进度 {elapsed}] [{self._stage}] {message}", file=self.stream, flush=True)
        except (OSError, ValueError):
            self.enabled = False
            self._stop.set()

    def __call__(self, event: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._stop.is_set():
                return
            kind = event.get("event")
            now = time.monotonic()
            if kind == "role_started":
                role = event["role"]
                self._stage = f"{event['index']}/{event['total']} {ROLE_LABELS.get(role, role)}"
                self._stage_started = now
                message = "开始独立会话，检查模型运行环境"
            elif kind == "role_completed":
                message = f"阶段校验通过，用时 {_duration(now - self._stage_started)}"
            elif kind == "workflow_completed":
                self._stage = "保存"
                self._stage_started = now
                message = "模型处理已完成，正在执行最终卡片结构校验与保存"
            elif kind == "phase":
                message = event["message"]
            else:
                return
            self._last_event = now
            self._activity = message
            self._write(message)

    def _heartbeat(self) -> None:
        while not self._stop.wait(self.interval):
            with self._lock:
                if self._stop.is_set():
                    return
                now = time.monotonic()
                self._write(
                    f"等待中；本阶段已用 {_duration(now - self._stage_started)}；"
                    f"距最近进展事件 {_duration(now - self._last_event)}；"
                    f"最近状态：{self._activity}"
                )

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def finish(self, result: dict[str, Any]) -> None:
        self.close()
        if not self.enabled:
            return
        with self._lock:
            if not result.get("ok"):
                code = result.get("error", {}).get("code", "FAILED")
                self._write(f"失败，停在本阶段；错误码：{code}（详见最终结果）")
            elif result.get("action") == "SKIPPED_EXISTING_CARD":
                self._write("已跳过：已有证据卡，未调用模型")
            elif result.get("operation") == "evidence_generate_trial":
                self._write("试运行完成并保存；正式卡片与任务未修改")
            else:
                self._write("处理完成，结果已保存")

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
        if exc_type is not None and self.enabled:
            with self._lock:
                self._write("已中止" if exc_type is KeyboardInterrupt else "异常中止，详见错误输出")
