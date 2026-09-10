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
        self, *, enabled: bool = True, heartbeat_interval_seconds: float = 60,
        stream: TextIO | None = None,
        label: str = "AI进度", initial_activity: str = "检查 Zotero、任务及 PDF",
    ) -> None:
        self.enabled = enabled
        self.label = label
        self.interval = heartbeat_interval_seconds
        self.stream = stream if stream is not None else sys.stderr
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = self._stage_started = self._last_event = time.monotonic()
        self._stage = "准备"
        self._activity = initial_activity

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
            print(f"[{self.label} {elapsed}] [{self._stage}] {message}", file=self.stream, flush=True)
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
                message = f"模型阶段完成，用时 {_duration(now - self._stage_started)}"
            elif kind == "workflow_completed":
                self._stage = "保存"
                self._stage_started = now
                message = "模型处理已完成，正在检查来源、重复与写入状态并保存"
            elif kind == "phase":
                if event.get("stage") and event["stage"] != self._stage:
                    self._stage = str(event["stage"])
                    self._stage_started = now
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
            if result.get("operation") == "run_once":
                # The last paper's stage is not the outcome of the entire queue.
                self._stage = "整轮汇总"
                status = result.get("status", "UNKNOWN")
                labels = {"COMPLETED": "本轮处理完成", "COMPLETED_WITH_BLOCKERS": "本轮结束，仍有失败或阻塞",
                          "COMPLETED_WITH_PENDING": "本轮结束，仍有等待或延后项", "CANCELLED": "本轮已取消",
                          "FAILED": "本轮运行失败", "ALREADY_RUNNING": "已有运行实例，本次未启动",
                          "LOCAL_PREVIEW": "本地预览完成，未执行处理"}
                self._write(labels.get(status, f"本轮状态：{status}"))
                counts = result.get("counts")
                if isinstance(counts, dict):
                    self._write("；".join(f"{label} {counts.get(key, 0)}" for key, label in (
                        ("completed", "本轮新完成"), ("recovered", "恢复完成"), ("skipped", "跳过"),
                        ("failed", "失败"), ("blocked", "阻塞"), ("waiting", "等待"), ("deferred", "延后"))))
                for item in result.get("items", []):
                    if item.get("status") in {"FAILED", "BLOCKED", "WAITING", "DEFERRED"}:
                        reason = item.get("reason_code") or (item.get("error") or {}).get("code", "未提供原因码")
                        self._write(f"未完成项 {item.get('parent_key', '未知')}：{item['status']}，{reason}")
                theme = result.get("theme_pipeline")
                if isinstance(theme, dict):
                    self._write("主题流程暂缓，本轮未生成新主题" if theme.get("status") == "DEFERRED"
                                else f"主题流程状态：{theme.get('status', 'UNKNOWN')}")
                if result.get("error"):
                    self._write(f"整轮错误：{result['error'].get('code', '未提供原因码')}（详见最终结果）")
                for key in ("monitoring_warning", "report_warning"):
                    if result.get(key):
                        self._write(str(result[key]))
                if result.get("report_path"):
                    self._write(f"运行报告：{result['report_path']}")
            elif not result.get("ok"):
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
