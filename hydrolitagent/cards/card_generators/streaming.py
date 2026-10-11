from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import Mapping, Sequence, TextIO

from hydrolitagent.cards.card_generators.connection_guard import ConnectionGuard
from hydrolitagent.cards.config import ConnectionGuardConfig
from hydrolitagent.cards.progress import ProgressCallback, report_progress


class ExecutionStopped(subprocess.SubprocessError):
    def __init__(self, code: str, message: str, diagnostic: dict) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostic = diagnostic
        self.result: subprocess.CompletedProcess[str] | None = None


def _status_event(line: str, progress: ProgressCallback | None, server: str) -> None:
    """Only expose known lifecycle events, never model text, prompts or tool payloads."""
    try:
        event = json.loads(line)
    except (ValueError, TypeError):
        return
    if not isinstance(event, dict):
        return
    kind = event.get("type")
    message = None
    if kind == "turn.started":
        message = "模型回合已开始，等待工具调用或输出"
    elif kind == "error":
        raw_message = event.get("message", "")
        if isinstance(raw_message, str) and "reconnect" in raw_message.lower():
            message = "Codex 报告连接重试，等待恢复"
        else:
            message = "Codex 报告错误事件，等待调用结束后判定结果"
    elif kind in {"item.started", "item.completed"}:
        item = event.get("item")
        if not isinstance(item, dict):
            return
        if (
            item.get("type") == "mcp_tool_call"
            and item.get("server") == server
            and item.get("tool") == "read_full_source_pdf"
        ):
            if kind == "item.started":
                message = "PDF 全文读取工具已开始调用（含页面图像）"
            elif item.get("status") == "failed":
                message = "PDF 工具调用失败，等待调用结束后判定结果"
            elif item.get("status") == "completed":
                message = "PDF 工具已返回，完整性仍须由程序校验"
        elif item.get("type") == "agent_message" and kind == "item.completed":
            message = "收到模型回复，等待本回合结束"
        elif item.get("type") == "command_execution":
            if kind == "item.started":
                message = "本机读取/处理命令已开始"
            elif item.get("status") == "failed" or item.get("exit_code") not in (None, 0):
                message = "本机命令返回失败，等待模型处理或最终诊断"
            else:
                message = "本机命令已结束；不代表已读完 PDF 或看过图表"
    elif kind == "turn.completed":
        message = "模型回合已结束，等待进程退出与结果校验"
    elif kind == "turn.failed":
        message = "模型回合失败，正在收集诊断"
    if message is not None:
        report_progress(progress, "phase", message=message)


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        # This PID belongs to the child we just created, not another user session.
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=5, check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.SubprocessError):
                pass
        if process.poll() is None:
            process.kill()
    process.wait(timeout=5)


def run_streaming_prompt(
    command: Sequence[str], prompt: str, timeout_seconds: float,
    environment: Mapping[str, str] | None = None, *,
    progress: ProgressCallback | None = None, server: str = "hydro_pdf_reader",
    connection_guard: ConnectionGuardConfig | None = None, cwd=None, provider_label="Codex",
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(environment or {})
    deadline = time.monotonic() + timeout_seconds
    guard = ConnectionGuard(connection_guard or ConnectionGuardConfig(), server)
    process = subprocess.Popen(
        list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
        text=True, encoding="utf-8", errors="replace", env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    stdout: list[str] = []
    stderr: list[str] = []
    errors: list[Exception] = []

    def drain(stream: TextIO, destination: list[str], *, events: bool) -> None:
        try:
            for line in stream:
                destination.append(line)
                if events:
                    try:
                        event = json.loads(line)
                    except (ValueError, TypeError):
                        event = None
                    if isinstance(event, dict):
                        guard.observe(event)
                    _status_event(line, progress, server)
        except Exception as exc:
            errors.append(exc)
        finally:
            stream.close()

    def send_input() -> None:
        try:
            process.stdin.write(prompt)
        except BrokenPipeError:
            pass
        except Exception as exc:
            errors.append(exc)
        finally:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass

    threads = [
        threading.Thread(target=drain, args=(process.stdout, stdout), kwargs={"events": True}, daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr), kwargs={"events": False}, daemon=True),
        threading.Thread(target=send_input, daemon=True),
    ]
    try:
        report_progress(progress, "phase", message=f"{provider_label} 子进程已启动，等待模型服务响应")
        for thread in threads:
            thread.start()
        while True:
            reason = guard.check()
            if reason is not None:
                raise ExecutionStopped(*reason, guard.snapshot())
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout_seconds)
            if errors:
                raise subprocess.SubprocessError(f"读取 {provider_label} 进程输出失败") from errors[0]
            try:
                process.wait(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired:
                continue
            for thread in threads:
                thread.join(timeout=min(0.03, max(0, deadline - time.monotonic())))
            if all(not thread.is_alive() for thread in threads):
                break
        reason = guard.check()
        if reason is not None:
            raise ExecutionStopped(*reason, guard.snapshot())
        if errors:
            raise subprocess.SubprocessError(f"读取 {provider_label} 进程输出失败") from errors[0]
        report_progress(progress, "phase", message=f"{provider_label} 进程已退出，正在校验输出并判定结果")
        return subprocess.CompletedProcess(command, process.returncode, "".join(stdout), "".join(stderr))
    except BaseException as exc:
        if isinstance(exc, ExecutionStopped):
            report_progress(progress, "phase", message=f"已触发停止保护：{exc}；正在清理本次子进程")
        _stop_process(process)
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=1)
        if isinstance(exc, ExecutionStopped):
            exc.result = subprocess.CompletedProcess(command, process.returncode, "".join(stdout), "".join(stderr))
        elif isinstance(exc, subprocess.TimeoutExpired):
            exc.output = "".join(stdout)
            exc.stderr = "".join(stderr)
        raise
