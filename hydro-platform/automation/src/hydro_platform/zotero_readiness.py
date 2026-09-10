"""Bounded app readiness for run-once; no preference, sync or library writes."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path

from hydro_platform.progress import report_progress
from hydro_platform.zotero import preflight


RETRYABLE = {"ZOTERO_NOT_RUNNING", "LOCAL_API_UNAVAILABLE", "GROUP_NOT_AVAILABLE"}


class ZoteroStartupError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def resolve_startup_executable(settings):
    if platform.system() != "Windows":
        raise ZoteroStartupError("ZOTERO_STARTUP_UNSUPPORTED", "自动启动当前仅支持Windows；可手动打开Zotero")
    candidates = [settings.executable] if settings.executable else [
        shutil.which("zotero.exe"),
        *[str(Path(os.environ[key]) / "Zotero" / "zotero.exe")
          for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)") if os.environ.get(key)],
        str(Path(os.environ["LOCALAPPDATA"]) / "Zotero" / "zotero.exe") if os.environ.get("LOCALAPPDATA") else None,
    ]
    for value in candidates:
        if not value:
            continue
        resolved = shutil.which(value)
        path = Path(resolved or value)
        if path.is_file() and path.name.lower() == "zotero.exe":
            return str(path.resolve())
    raise ZoteroStartupError("ZOTERO_EXECUTABLE_NOT_FOUND", "找不到Zotero可执行文件；在zotero.startup.executable填写路径，不附加命令参数")


def launch_zotero(settings):
    executable = resolve_startup_executable(settings)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    try:
        # GUI process must outlive this one-shot runner. Never terminate/restart an existing Zotero.
        process = subprocess.Popen([executable], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, shell=False, close_fds=True, startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
    except OSError as exc:
        raise ZoteroStartupError("ZOTERO_START_FAILED", "无法启动配置的Zotero；未修改账号或系统设置") from exc
    return process


def ensure_zotero_ready(config, *, progress=None, probe=None, launcher=None,
                        clock=time.monotonic, sleep=time.sleep, wait_budget=None):
    probe = probe or preflight
    settings = config.startup
    if not settings.enabled:
        return probe(config)
    started = clock()
    budget = min(settings.wait_timeout_seconds, wait_budget) if wait_budget is not None else settings.wait_timeout_seconds
    metadata = {"enabled": True, "launch_attempted": False, "launched": False,
                "poll_count": 0, "wait_budget_seconds": max(0, budget)}
    last = {"ok": False, "error": {"code": "ZOTERO_NOT_READY", "message": "等待Zotero就绪"}}
    process = None

    def finish(result):
        metadata["elapsed_seconds"] = round(clock() - started, 2)
        metadata["note"] = "仅证明本地API与指定群组可访问，不证明云端同步完成；PDF仍由逐篇门禁检查"
        return {**result, "startup": metadata}

    while True:
        remaining = budget - (clock() - started)
        if remaining <= 0:
            return finish({"ok": False, "error": {"code": "ZOTERO_READY_TIMEOUT",
                "message": "等待Zotero或共享库就绪超时；保留成果，下次调度按冷却规则再试",
                "cause_code": last.get("error", {}).get("code")}})
        # Preflight performs at most a process check and two API requests.
        bounded = replace(config, timeout_seconds=min(config.timeout_seconds, remaining / 3),
                          process_timeout_seconds=min(config.process_timeout_seconds, remaining / 3))
        last = probe(bounded)
        metadata["poll_count"] += 1
        if last.get("ok"):
            return finish(last)
        code = last.get("error", {}).get("code")
        if code not in RETRYABLE:
            return finish(last)
        if clock() - started >= budget:
            continue
        if code == "ZOTERO_NOT_RUNNING" and settings.launch_if_missing and not metadata["launch_attempted"]:
            metadata["launch_attempted"] = True
            report_progress(progress, "phase", message="Zotero未运行，尝试启动已配置的本机程序（本轮只启动一次）")
            try:
                process = (launcher or launch_zotero)(settings)
            except ZoteroStartupError as exc:
                return finish({"ok": False, "error": {"code": exc.code, "message": str(exc)}})
            metadata.update(launched=True, launched_pid=process.pid)
        if process is not None:
            # The launcher can exit after handing off to another process. Exit alone is not readiness failure.
            metadata["launcher_exit_code"] = process.poll()
        remaining = budget - (clock() - started)
        if remaining <= 0:
            continue
        report_progress(progress, "phase", message=f"等待Zotero/共享库就绪：{code}；剩余约{int(remaining)}秒，不调用模型")
        sleep(min(settings.poll_interval_seconds, remaining))
