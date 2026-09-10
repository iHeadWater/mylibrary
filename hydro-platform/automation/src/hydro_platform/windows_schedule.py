"""Owned Windows task registration; Python owns daily-slot and retry decisions."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from hydro_platform.scheduled import due_status, read_state

NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
ET.register_namespace("", NS)

PS_BRIDGE = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$request = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__REQUEST__')) | ConvertFrom-Json
try {
  $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $found = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object { $_.TaskName -ceq $request.name })
  $task = if ($found.Count -eq 1) { $found[0] } else { $null }
  if ($found.Count -gt 1) { throw 'SCHEDULE_AMBIGUOUS' }
  if ($request.op -ne 'query') {
    if ($task -and $task.Description -cne $request.owner) { throw 'SCHEDULE_OWNERSHIP_CONFLICT' }
    if ($task -and $task.State.ToString() -eq 'Running' -and $request.op -ne 'run') { throw 'SCHEDULE_RUNNING' }
    if ($request.op -eq 'install') {
      Register-ScheduledTask -TaskName $request.name -TaskPath '\' -Xml $request.xml -Force:([bool]$task) -ErrorAction Stop | Out-Null
    } elseif ($request.op -eq 'remove') {
      if ($task) { Unregister-ScheduledTask -TaskName $request.name -TaskPath '\' -Confirm:$false -ErrorAction Stop }
    } elseif ($request.op -eq 'run') {
      if (-not $task) { throw 'SCHEDULE_NOT_FOUND' }
      Start-ScheduledTask -TaskName $request.name -TaskPath '\' -ErrorAction Stop
    } else { throw 'SCHEDULE_OPERATION_INVALID' }
    $found = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object { $_.TaskName -ceq $request.name })
    $task = if ($found.Count -eq 1) { $found[0] } else { $null }
  }
  $result = @{ok=$true;user_sid=$sid;user_name=[Security.Principal.WindowsIdentity]::GetCurrent().Name;exists=([bool]$task)}
  if ($task) {
    $result.state = $task.State.ToString()
    $result.description = $task.Description
    if ($task.Description -ceq $request.owner) {
      $result.xml = Export-ScheduledTask -TaskName $request.name -TaskPath '\' -ErrorAction Stop
      $info = Get-ScheduledTaskInfo -TaskName $request.name -TaskPath '\' -ErrorAction Stop
      $result.last_task_result = $info.LastTaskResult
      $result.last_run_time = if ($info.LastRunTime) { $info.LastRunTime.ToString('o') } else { $null }
      $result.next_run_time = if ($info.NextRunTime) { $info.NextRunTime.ToString('o') } else { $null }
    }
  }
  $result | ConvertTo-Json -Depth 8 -Compress
} catch {
  $code = if ($_.Exception.Message -match '^SCHEDULE_[A-Z_]+$') { $_.Exception.Message } else { 'WINDOWS_SCHEDULER_ERROR' }
  @{ok=$false;error=@{code=$code;hresult=$_.Exception.HResult;exception_type=$_.Exception.GetType().Name;
    message='Windows task operation failed; existing tasks were not intentionally replaced without ownership.'}} | ConvertTo-Json -Compress
  exit 3
}
'''


class ScheduleError(RuntimeError):
    def __init__(self, code, message, diagnostic=None):
        super().__init__(message)
        self.code = code
        self.diagnostic = diagnostic


def ownership(config):
    value = [str(config.paths.project_root), str(config.source_file), config.zotero.group_id]
    return "hydro-platform-schedule-v1:" + hashlib.sha256(json.dumps(value).encode()).hexdigest()


def native_call(config, operation, *, task_name=None, xml=None):
    if os.name != "nt":
        raise ScheduleError("SCHEDULE_PLATFORM_UNSUPPORTED", "当前调度安装器仅支持 Windows")
    executable = shutil.which(config.scheduler.powershell_executable)
    if not executable:
        raise ScheduleError("SCHEDULE_SHELL_MISSING", "找不到配置的 PowerShell")
    payload = {"op": operation, "name": task_name or config.scheduler.task_name, "owner": ownership(config), "xml": xml}
    encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    script = PS_BRIDGE.replace("__REQUEST__", encoded)
    argv = [executable, "-NoProfile", "-NonInteractive", "-EncodedCommand",
            base64.b64encode(script.encode("utf-16-le")).decode("ascii")]
    try:
        completed = subprocess.run(argv, capture_output=True, timeout=config.scheduler.command_timeout_seconds,
                                   check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result = json.loads(completed.stdout.decode("utf-8-sig"))
        if not isinstance(result, dict):
            raise ValueError("unexpected task response")
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise ScheduleError("SCHEDULE_COMMAND_UNCERTAIN", "无法确定 Windows 调度操作结果；请先运行 schedule-status，不要因观察超时直接重复创建") from exc
    if not result.get("ok") or completed.returncode:
        code = result.get("error", {}).get("code", "WINDOWS_SCHEDULER_ERROR")
        error = result.get("error", {})
        raise ScheduleError(code, "Windows 调度操作未完成；检查服务、账号权限、同名任务归属或正在运行的实例",
                            {k: error[k] for k in ("hresult", "exception_type") if k in error})
    return result


def task_xml(config, sid, *, probe_token=None):
    target = config.deployment.environment_dir or config.paths.project_root / ".venv"
    python = target / "Scripts/pythonw.exe"
    runner = config.paths.project_root / "automation/scheduled_run.py"
    for path in (python, runner, config.source_file):
        if path is None or not Path(path).is_file():
            raise ScheduleError("SCHEDULE_DEPENDENCY_MISSING", "计划任务需要已安装的项目 pythonw.exe、仓库入口和完整总配置")
    root = ET.Element("{" + NS + "}Task", version="1.2")
    def add(parent, tag, text=None, **attrs):
        node = ET.SubElement(parent, "{" + NS + "}" + tag, attrs)
        node.text = text
        return node
    info = add(root, "RegistrationInfo")
    add(info, "Description", ownership(config))
    triggers = add(root, "Triggers")
    if not probe_token:
        daily = add(triggers, "CalendarTrigger")
        repeat = add(daily, "Repetition")
        add(repeat, "Interval", f"PT{config.scheduler.poll_interval_minutes}M")
        add(repeat, "Duration", "P1D")
        add(repeat, "StopAtDurationEnd", "false")
        # A stable, past calendar anchor avoids drifting XML on each reinstall/status check.
        add(daily, "StartBoundary", "2000-01-01T" + config.scheduler.daily_time + ":00")
        add(daily, "Enabled", "true")
        add(add(daily, "ScheduleByDay"), "DaysInterval", "1")
        logon = add(triggers, "LogonTrigger")
        add(logon, "Enabled", "true")
        add(logon, "UserId", sid)
        add(logon, "Delay", f"PT{config.scheduler.logon_delay_seconds}S")
    principals = add(root, "Principals")
    principal = add(principals, "Principal", id="Operator")
    add(principal, "UserId", sid)
    add(principal, "LogonType", "InteractiveToken")
    add(principal, "RunLevel", "LeastPrivilege")
    settings = add(root, "Settings")
    fields = {"MultipleInstancesPolicy": "IgnoreNew", "DisallowStartIfOnBatteries": "false",
              "StopIfGoingOnBatteries": "false", "AllowHardTerminate": "true",
              "StartWhenAvailable": "true", "RunOnlyIfNetworkAvailable": "false",
              "AllowStartOnDemand": "true", "Enabled": str(config.scheduler.enabled or bool(probe_token)).lower(),
              "Hidden": "true", "WakeToRun": "false",
              "ExecutionTimeLimit": f"PT{config.scheduler.execution_time_limit_seconds}S", "Priority": "7"}
    for key, value in fields.items():
        add(settings, key, value)
    action = add(add(root, "Actions", Context="Operator"), "Exec")
    add(action, "Command", str(python))
    arguments = [str(runner), "--config", str(config.source_file)]
    if probe_token:
        arguments += ["--probe-token", probe_token]
    add(action, "Arguments", subprocess.list2cmdline(arguments))
    add(action, "WorkingDirectory", str(config.paths.project_root))
    return ET.tostring(root, encoding="unicode")


def comparable(xml, *, user_sid=None, user_name=None):
    root = ET.fromstring(xml)
    def tag(name):
        return "{" + NS + "}" + name
    def default(parent, name, value):
        if parent is not None and parent.find(tag(name)) is None:
            ET.SubElement(parent, tag(name)).text = value
    # Windows exports omit schema defaults and normalize durations/account names.
    # Apply only documented equivalent forms; changed privileges/actions still differ.
    settings = root.find(tag("Settings"))
    for name, value in {"RunOnlyIfNetworkAvailable": "false", "AllowStartOnDemand": "true",
                        "Enabled": "true", "WakeToRun": "false"}.items():
        default(settings, name, value)
    for principal in root.findall(tag("Principals") + "/" + tag("Principal")):
        default(principal, "RunLevel", "LeastPrivilege")
    triggers = root.find(tag("Triggers"))
    if triggers is not None:
        for trigger in triggers:
            default(trigger, "Enabled", "true")
            default(trigger.find(tag("Repetition")), "StopAtDurationEnd", "false")
    def values(path):
        node = root.find("/".join("{" + NS + "}" + part for part in path.split("/")))
        if node is None:
            return None
        def normalize(element):
            name, text = element.tag.split("}")[-1], (element.text or "").strip()
            if name == "UserId" and user_sid and user_name and text.casefold() == user_name.casefold():
                text = user_sid
            if name in {"Delay", "Interval", "Duration", "ExecutionTimeLimit"}:
                duration = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", text)
                if duration and any(duration.groups()):
                    text = str(sum(int(v or 0) * scale for v, scale in zip(duration.groups(), (86400, 3600, 60, 1))))
            return (name, text,
                    tuple(sorted((normalize(c) for c in element), key=repr)))
        return normalize(node)
    # Windows may add harmless default settings. Pin the important ones individually.
    paths = ["RegistrationInfo/Description", "Principals", "Actions", "Triggers"]
    paths += ["Settings/" + name for name in (
        "MultipleInstancesPolicy", "DisallowStartIfOnBatteries", "StopIfGoingOnBatteries",
        "StartWhenAvailable", "RunOnlyIfNetworkAvailable", "AllowStartOnDemand", "Enabled",
        "Hidden", "WakeToRun", "ExecutionTimeLimit")]
    return {path: values(path) for path in paths}


def manage_schedule(config, operation="status", *, backend=None):
    call = backend or (lambda op, **kw: native_call(config, op, **kw))
    result = {"schema_version": 1, "operation": "schedule_" + operation, "ok": False,
              "task_name": config.scheduler.task_name, "model_call_count": 0}
    try:
        current = call("query")
        if current["exists"] and current.get("description") != ownership(config):
            raise ScheduleError("SCHEDULE_OWNERSHIP_CONFLICT", "同名 Windows 任务不属于当前仓库/配置；不修改或删除它")
        if operation == "remove":
            call("remove")
            return {**result, "ok": True, "status": "REMOVED" if current["exists"] else "ABSENT",
                    "note": "只移除本项目计划任务；知识和运行记录保留，可用 schedule-install 重建"}
        xml = task_xml(config, current["user_sid"])
        def matched(observed):
            identity = {k: observed.get(k) for k in ("user_sid", "user_name")}
            return observed["exists"] and comparable(observed["xml"], **identity) == comparable(xml, **identity)
        matches = matched(current)
        if operation == "install" and not matches:
            current = call("install", xml=xml)
            matches = matched(current)
            if not matches:
                raise ScheduleError("SCHEDULE_REGISTRATION_MISMATCH", "Windows 已处理注册，但读回定义不匹配；请检查状态，不自动再次注册")
        elif operation not in {"status", "plan", "install"}:
            raise ValueError("invalid schedule operation")
        result.update(ok=operation == "plan" or bool(matches),
            status="PLANNED" if operation == "plan" else "ABSENT" if not current["exists"] else
            "DRIFTED" if not matches else "ENABLED" if config.scheduler.enabled else "DISABLED",
            registered=current["exists"], definition_matches=bool(matches),
            daily_time=config.scheduler.daily_time, timezone="Windows 本机时区",
            native_state=current.get("state"), last_task_result=current.get("last_task_result"),
            last_run_time=current.get("last_run_time"), next_run_time=current.get("next_run_time"),
            next_check_time=current.get("next_run_time"),
            action_python=str((config.deployment.environment_dir or config.paths.project_root / ".venv") / "Scripts/pythonw.exe"),
            note="需要 Windows 用户登录；无需 Codex 对话窗口。定时/登录后轮询，只有到期或允许补跑才进入流水线；不自动 Git 推送")
        state = read_state(config)
        result["runtime_state"] = state
        result["due_status"] = due_status(config, state, datetime.now().astimezone())[1]
        if config.scheduler.enabled and matches:
            if current.get("last_task_result") == 0x41303:
                result["warning"] = "计划已注册，但 Windows 尚未执行过；不能视为真实启动已验收"
            elif result["due_status"] in {"ATTEMPTS_EXHAUSTED", "CLOCK_REVERSED"}:
                result["warning"] = "调度定义正确，但运行处于次数上限或时钟异常；查看 runtime_state 和流水线摘要"
            elif state and state["status"] == "FAILED":
                result["warning"] = "最近一轮流水线失败，计划定义仍在；是否允许补跑见 due_status"
            elif state and state["status"] == "PENDING":
                result["warning"] = "仍有文献等待或延后，不是全部完成；按冷却与日次数上限补查，详见流水线摘要"
            elif current.get("last_task_result") not in {None, 0, 0x41301}:
                result["warning"] = "Windows 最近任务返回非零状态；检查 last_task_result 与本地运行记录"
        return result
    except (ScheduleError, OSError, ValueError, TypeError, KeyError) as exc:
        return {**result, "status": "FAILED", "error": {"code": getattr(exc, "code", "SCHEDULE_STATE_ERROR"),
                "message": str(exc) if isinstance(exc, ScheduleError) else "调度定义或本地状态无法核对；保留现有任务与文件",
                "diagnostic": getattr(exc, "diagnostic", None)}}
