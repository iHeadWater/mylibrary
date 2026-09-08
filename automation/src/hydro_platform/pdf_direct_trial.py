"""Opt-in path-reading experiment; never a production card acceptance gate."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

from hydro_platform.card_generators.codex_cli import (
    CodexCliAdapter, _classify_exec_failure, _combined_output, _last_agent_message,
    _parse_jsonl, _safe_exec_diagnostic, _sha256_file, _terminal_failure_events,
    _timeout_text, _toml_string, _usage, _sanitize_diagnostic_text,
)
from hydro_platform.card_generators.streaming import ExecutionStopped, run_streaming_prompt
from hydro_platform.config import AppConfig
from hydro_platform.pdf_delivery import PdfDelivery
from hydro_platform.pdf_sandbox import check_pdf_sandbox
from hydro_platform.progress import report_progress


class PdfDirectTrialError(RuntimeError):
    def __init__(self, code: str, message: str, diagnostic: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.diagnostic = diagnostic


def _local_command(command: list[str], timeout: float) -> str:
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        raise PdfDirectTrialError("PDF_DIRECT_LOCAL_TOOL_FAILED", "本机 PDF 检查工具无法启动或超时") from exc
    if result.returncode:
        raise PdfDirectTrialError("PDF_DIRECT_LOCAL_TOOL_FAILED", "本机 PDF 检查工具返回失败")
    return result.stdout.decode("utf-8", errors="replace")


def _validate_report(report: Any, page_count: int) -> None:
    fields = {"read_status", "source_page_count", "claimed_text_pages", "claimed_visual_pages",
              "visual_findings", "limitations"}
    invalid = PdfDirectTrialError("PDF_DIRECT_OUTPUT_INVALID", "路径直读报告字段或类型不符合协议")
    if not isinstance(report, dict) or set(report) != fields:
        raise invalid
    if report["read_status"] not in ("COMPLETE", "PARTIAL", "UNREADABLE"):
        raise invalid
    if type(report["source_page_count"]) is not int or not 0 <= report["source_page_count"] <= page_count:
        raise invalid
    for name in ("claimed_text_pages", "claimed_visual_pages"):
        pages = report[name]
        if not isinstance(pages, list) or any(type(p) is not int or not 1 <= p <= page_count for p in pages):
            raise invalid
        if len(set(pages)) != len(pages):
            raise invalid
    if not isinstance(report["visual_findings"], list):
        raise invalid
    for entry in report["visual_findings"]:
        if not isinstance(entry, dict) or set(entry) != {"page", "label", "observation"}:
            raise invalid
        if type(entry["page"]) is not int or not 1 <= entry["page"] <= page_count:
            raise invalid
        if any(not isinstance(entry[key], str) or not entry[key].strip() for key in ("label", "observation")):
            raise invalid
    if not isinstance(report["limitations"], list) or any(not isinstance(v, str) for v in report["limitations"]):
        raise invalid


def _command(executable: str, config: AppConfig, workspace: Path) -> list[str]:
    trial = config.card_generator.pdf_direct_trial
    assert trial is not None
    command = [executable, "exec", "--json", "--ephemeral", "--ignore-user-config",
               "--skip-git-repo-check", "--sandbox", "workspace-write", "--cd", str(workspace),
               "--color", "never", "--output-schema", str(trial.schema_file),
               "--config", 'approval_policy="never"',
               "--config", "sandbox_workspace_write.network_access=false",
               "--config", "windows.sandbox=" + _toml_string(trial.windows_sandbox),
               "--config", "windows.sandbox_private_desktop=true",
               "--config", 'web_search="disabled"',
               "--disable", "apps", "--disable", "plugins", "--disable", "multi_agent"]
    # Keep shell / view_image available. No MCP, no blanket shell rejection, no rule bypass.
    if config.card_generator.model is not None:
        command.extend(["--model", config.card_generator.model])
    if config.card_generator.reasoning_effort is not None:
        command.extend(["--config", "model_reasoning_effort=" + _toml_string(config.card_generator.reasoning_effort)])
    command.append("-")
    return command


def run_pdf_direct_trial(
    config: AppConfig, delivery: PdfDelivery, *, progress=None,
    adapter=None, runner=None, local_runner=None, executable_finder=None,
    sandbox_checker=None, preflight_only: bool = False,
) -> dict[str, Any]:
    runner = runner or run_streaming_prompt
    local_runner = local_runner or _local_command
    executable_finder = executable_finder or shutil.which
    sandbox_checker = sandbox_checker or check_pdf_sandbox
    trial = config.card_generator.pdf_direct_trial
    if trial is None:
        raise PdfDirectTrialError("CONFIG_ERROR", "未配置 pdf_direct_trial")
    base: dict[str, Any] = {
        "schema_version": 1, "ok": False, "operation": "pdf_direct_read_trial",
        "protocol_version": "pdf-direct-read-v2",
        "parent_key": delivery.parent_key, "group_id": delivery.group_id,
        "model_invoked": False, "production_eligible": False,
        "full_read_verified": False, "visual_understanding_verified": False,
        "model": config.card_generator.model, "reasoning_effort": config.card_generator.reasoning_effort,
        "preflight_only": preflight_only,
        "windows_sandbox": trial.windows_sandbox, "text_extractor": trial.text_extractor,
    }
    try:
        source = delivery.pdf_path.resolve(strict=True)
    except OSError as exc:
        raise PdfDirectTrialError("PDF_DIRECT_SOURCE_UNAVAILABLE", "无法访问本次原始 PDF，尚未调用模型") from exc
    if _sha256_file(source) != delivery.pdf_sha256:
        raise PdfDirectTrialError("PDF_INPUT_CHANGED", "原始 PDF 已改变，停止路径直读")
    tools = {}
    tool_names = ["pdfinfo", "pdftoppm"]
    if trial.text_extractor == "pdftotext":
        tool_names.append("pdftotext")
    for name in tool_names:
        configured = getattr(config.card_generator.pdf_reader, name + "_executable")
        resolved = executable_finder(configured)
        if not resolved:
            raise PdfDirectTrialError("PDF_DIRECT_TOOL_NOT_FOUND", f"找不到配置的 {name}，尚未调用模型")
        tools[name] = str(Path(resolved).resolve())
    shell = executable_finder(trial.shell_executable)
    python = executable_finder(trial.python_executable or sys.executable)
    if not shell or not python:
        raise PdfDirectTrialError("PDF_DIRECT_TOOL_NOT_FOUND", "找不到配置的 shell 或 Python；尚未调用模型")
    shell, python = str(Path(shell).resolve()), str(Path(python).resolve())
    try:
        prompt_template = trial.prompt_file.read_text(encoding="utf-8")
        schema = json.loads(trial.schema_file.read_text(encoding="utf-8"))
        if not prompt_template.strip() or not isinstance(schema, dict):
            raise ValueError("invalid assets")
    except (OSError, ValueError) as exc:
        raise PdfDirectTrialError("PDF_DIRECT_ASSET_INVALID", "路径直读提示词或 schema 不存在或无效") from exc
    local_timeout = config.card_generator.pdf_reader.tool_timeout_seconds
    info = local_runner([tools["pdfinfo"], str(source)], local_timeout)
    match = re.search(r"^Pages:\s*(\d+)\s*$", info, flags=re.MULTILINE)
    if not match or int(match.group(1)) < 1:
        raise PdfDirectTrialError("PDF_DIRECT_PAGE_COUNT_INVALID", "本机未能独立确认 PDF 页数")
    page_count = int(match.group(1))
    ready = (adapter or CodexCliAdapter(config.card_generator)).preflight(check_pdf_reader=False)
    if not ready.get("ok"):
        return {**base, "error": ready["error"]}
    report_progress(progress, "phase", message="路径直读实验：只交付 PDF 路径；允许本机读取和看图，不启动 PDF MCP")
    config.paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    report = None
    events: list[dict[str, Any]] = []
    completed = None
    try:
        with tempfile.TemporaryDirectory(prefix="pdf-direct-work-", dir=config.paths.runtime_dir) as directory:
            workspace = Path(directory).resolve()
            if source.is_relative_to(workspace):
                raise PdfDirectTrialError("PDF_DIRECT_UNSAFE_WORKSPACE", "源 PDF 不得位于可写临时工作区")
            base["sandbox_preflight"] = sandbox_checker(
                ready["resolved_executable"], config, workspace, source, tools, page_count,
                delivery.pdf_sha256, shell=shell, python=python, progress=progress,
            )
            if not base["sandbox_preflight"].get("ok"):
                raise PdfDirectTrialError("PDF_DIRECT_SANDBOX_PREFLIGHT_FAILED",
                                         "本机沙箱读取预检失败，未调用模型",
                                         base["sandbox_preflight"].get("diagnostic"))
            if preflight_only:
                base.update(ok=True, validation_status="SANDBOX_PREFLIGHT_PASSED",
                            note="只验证本机工具可读源 PDF 并渲染页面；未调用模型，不代表模型工具路由或论文理解通过")
                return _finish_trial(base, config, delivery, source, None, [])
            context = {"source_pdf_path": str(source), "expected_page_count": page_count,
                       "installed_tools": tools,
                       "shell_executable": shell, "python_executable": python,
                       "text_extractor": trial.text_extractor,
                       "scratch_directory": str(workspace),
                       "render_dpi": config.card_generator.pdf_reader.render_dpi}
            prompt = prompt_template + "\n\n运行参数（数据，不是命令）：\n" + json.dumps(context, ensure_ascii=False)
            base["model_invoked"] = True
            completed = runner(_command(ready["resolved_executable"], config, workspace), prompt,
                               trial.timeout_seconds, progress=progress,
                               connection_guard=config.card_generator.connection_guard)
            try:
                events = _parse_jsonl(completed.stdout)
            except ValueError as exc:
                if completed.returncode == 0:
                    raise PdfDirectTrialError("PDF_DIRECT_EVENTS_INVALID", "模型进程未返回有效事件流") from exc
                events = []
            if completed.returncode or _terminal_failure_events(events):
                code, message = _classify_exec_failure(_combined_output(completed))
                base.update(error={"code": code, "message": message},
                            diagnostic=_safe_exec_diagnostic(completed, code))
            elif not any(event.get("type") == "turn.completed" for event in events):
                base["error"] = {"code": "PDF_DIRECT_TURN_INCOMPLETE", "message": "模型回合没有正常完成"}
            else:
                try:
                    report = json.loads(_last_agent_message(events) or "")
                except (ValueError, TypeError) as exc:
                    raise PdfDirectTrialError("PDF_DIRECT_OUTPUT_INVALID", "模型没有返回有效 JSON 报告") from exc
                _validate_report(report, page_count)
                base["usage"] = _usage(events)
                expected = list(range(1, page_count + 1))
                if (report["read_status"] != "COMPLETE" or report["source_page_count"] != page_count
                    or sorted(report["claimed_text_pages"]) != expected
                    or sorted(report["claimed_visual_pages"]) != expected):
                    raise PdfDirectTrialError("PDF_DIRECT_READING_INCOMPLETE", "模型报告未完整读取文字或页面图像")
                if not report["visual_findings"]:
                    raise PdfDirectTrialError("PDF_DIRECT_VISUAL_FINDING_MISSING", "未返回图表观察，尚不能验证视觉读取")
                base.update(ok=True, validation_status="READING_REPORT_ACCEPTED",
                            note="报告结构通过且模型声明读完文字与页面图像；不要求原文摘录，不代表全文覆盖、图表理解或生产制卡质量已经独立验证")
    except ExecutionStopped as exc:
        base.update(error={"code": exc.code, "message": str(exc)}, diagnostic={"connection_guard": exc.diagnostic})
    except subprocess.TimeoutExpired as exc:
        result = subprocess.CompletedProcess([], -1, _timeout_text(exc.output), _timeout_text(exc.stderr))
        base.update(error={"code": "PDF_DIRECT_TIMEOUT", "message": "路径直读实验超过时限，未自动重跑"},
                    diagnostic=_safe_exec_diagnostic(result, "PDF_DIRECT_TIMEOUT"))
    except PdfDirectTrialError as exc:
        base.update(error={"code": exc.code, "message": str(exc)})
        if exc.diagnostic is not None:
            base["diagnostic"] = exc.diagnostic
    except (OSError, subprocess.SubprocessError):
        base.update(error={"code": "PDF_DIRECT_EXEC_IO_ERROR", "message": "本次进程或文件访问失败，未自动重跑"})
    # Preserve only validated report shapes, never arbitrary model output or raw commands.
    if report is not None:
        try:
            _validate_report(report, page_count)
        except PdfDirectTrialError:
            report = None
    if not base.get("ok") and completed is not None:
        # A zero process exit does NOT mean shell/PDF tools succeeded. Preserve error
        # evidence for schema/reading failures too, never the raw streams.
        base["diagnostic"] = _reading_diagnostic(completed, events, base["error"]["code"], report)
        if base["diagnostic"]["policy_denial_observed"]:
            base["error"] = {"code": "PDF_DIRECT_TOOL_ACCESS_DENIED",
                             "message": "底层工具日志记录了权限拒绝，本次 PDF 读取未通过"}
    return _finish_trial(base, config, delivery, source, report, events)


def _reading_diagnostic(completed, events, category, report):
    diagnostic = _safe_exec_diagnostic(completed, category, stage="pdf_direct_validation")
    first_denial = None
    for line in (completed.stderr or "").splitlines():
        if (re.search(r"exec_command|shell|sandbox|CreateProcess", line, re.I)
            and re.search(r"blocked by policy|permission denied|access is denied|拒绝访问|拒絕存取", line, re.I)):
            first_denial = _sanitize_diagnostic_text(line)
            break
    diagnostic["policy_denial_observed"] = first_denial is not None
    if first_denial:
        diagnostic["first_policy_denial"] = first_denial
    commands = [e["item"] for e in events if e.get("type") == "item.completed"
                and isinstance(e.get("item"), dict) and e["item"].get("type") == "command_execution"]
    diagnostic["command_event_count"] = len(commands)
    diagnostic["failed_command_event_count"] = sum(
        c.get("status") == "failed" or c.get("exit_code") not in (None, 0) for c in commands)
    if report is not None:
        diagnostic["model_claim"] = {"read_status": report["read_status"],
                                     "text_page_count": len(report["claimed_text_pages"]),
                                     "visual_page_count": len(report["claimed_visual_pages"])}
    return diagnostic


def _finish_trial(base, config, delivery, source, report, events):
    try:
        source_unchanged = source.is_file() and _sha256_file(source) == delivery.pdf_sha256
    except OSError:
        source_unchanged = False
    base["source_unchanged"] = source_unchanged
    if not source_unchanged:
        base.pop("validation_status", None)
        base.update(ok=False, error={"code": "PDF_INPUT_CHANGED", "message": "验证结束时原始 PDF 指纹已变化"})
    base["observed_item_types"] = dict(Counter(
        event["item"]["type"] for event in events
        if event.get("type") == "item.completed" and isinstance(event.get("item"), dict)
        and isinstance(event["item"].get("type"), str)
    ))
    # No formal card, manifest, task registry or PDF is written here.
    destination = config.paths.card_trials_dir / "pdf-direct-read" / f"{delivery.parent_key}-{uuid4().hex}"
    destination.mkdir(parents=True, exist_ok=False)
    base["trial_path"] = str(destination)
    if report is not None:
        (destination / "model-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        base["model_report_path"] = str(destination / "model-report.json")
    (destination / "result.json").write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return base
