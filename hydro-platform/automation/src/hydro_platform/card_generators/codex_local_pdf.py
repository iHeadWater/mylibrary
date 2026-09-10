"""Codex provider using the tested local-path workflow; never fabricates MCP receipts."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from hydro_platform.card_generators.codex_cli import (
    CodexCliAdapter, _classify_exec_failure, _combined_output, _last_agent_message,
    _parse_jsonl, _safe_exec_diagnostic, _sha256_file, _terminal_failure_events,
    _timeout_text, _toml_string, _usage,
)
from hydro_platform.card_generators.streaming import ExecutionStopped
from hydro_platform.pdf_sandbox import check_pdf_sandbox
from hydro_platform.progress import report_progress
from hydro_platform.publication import atomic_text


class _LocalReadError(RuntimeError):
    def __init__(self, code, message, diagnostic=None):
        super().__init__(message)
        self.code, self.diagnostic = code, diagnostic


@contextmanager
def _scratch_workspace(runtime_dir, warnings, progress):
    # Only this freshly created directory is eligible for cleanup. Never repair ACLs.
    scratch = Path(tempfile.mkdtemp(prefix="pdf-role-", dir=runtime_dir)).resolve()
    if scratch.parent != runtime_dir.resolve():
        raise _LocalReadError("PDF_DIRECT_UNSAFE_WORKSPACE", "临时工作区不在配置运行目录内")
    try:
        yield str(scratch)
    finally:
        try:
            shutil.rmtree(scratch)
        except OSError as exc:
            warnings.append({"code": "SCRATCH_CLEANUP_FAILED", "exception_type": type(exc).__name__,
                             "errno": exc.errno, "winerror": getattr(exc, "winerror", None),
                             "scratch_path": str(scratch)})
            report_progress(progress, "phase", message="临时目录清理失败，保留残留目录；继续校验并保存模型结果，不自动重跑")


class CodexLocalPdfAdapter(CodexCliAdapter):
    def __init__(self, config, *, sandbox_checker=None, local_runner=None, **kwargs):
        super().__init__(config, **kwargs)
        self._progress = kwargs.get("progress")
        self._sandbox_checker = sandbox_checker or check_pdf_sandbox
        self._local_runner = local_runner or self._run_pdfinfo

    @staticmethod
    def _run_pdfinfo(command, timeout):
        result = subprocess.run(command, capture_output=True, check=False, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise _LocalReadError("PDF_DIRECT_LOCAL_TOOL_FAILED", "本机 PDF 页数检查失败")
        return result.stdout.decode("utf-8", errors="replace")

    def preflight(self, *, check_pdf_reader=True):
        ready = super().preflight(check_pdf_reader=False)
        ready = {**ready, "adapter": self.config.adapter, "configured_executable": self.config.executable,
                 "configured_auth_mode": self.config.auth_mode}
        if not ready.get("ok") or not check_pdf_reader:
            return ready
        settings = self.config.pdf_direct_trial
        try:
            if settings is None or self.config.runtime_dir is None or settings.reading_prompt_file is None:
                raise _LocalReadError("CONFIG_ERROR", "路径制卡缺少运行目录或共用读取配置")
            instructions = settings.reading_prompt_file.read_text(encoding="utf-8")
            if 'prompt_version: "pdf-local-reading-v1"' not in instructions:
                raise _LocalReadError("PDF_DIRECT_ASSET_INVALID", "共用读取提示词版本无效")
            names = ["pdfinfo", "pdftoppm"]
            if settings.text_extractor == "pdftotext":
                names.append("pdftotext")
            configured = {name: getattr(self.config.pdf_reader, name + "_executable") for name in names}
            configured.update(shell=settings.shell_executable, python=settings.python_executable or sys.executable)
            resolved = {}
            for name, value in configured.items():
                found = self._executable_finder(value)
                if not found:
                    raise _LocalReadError("PDF_DIRECT_TOOL_NOT_FOUND", f"找不到配置的本机读取工具：{name}")
                resolved[name] = str(Path(found).resolve())
        except (OSError, UnicodeDecodeError):
            return {**ready, "ok": False, "error": {"code": "PDF_DIRECT_ASSET_INVALID", "message": "共用读取提示词不可访问"}}
        except _LocalReadError as exc:
            return {**ready, "ok": False, "error": {"code": exc.code, "message": str(exc)}}
        return {**ready, "pdf_reader": {"adapter": "local_path", "resolved_tools": resolved,
                "reading_prompt_sha256": hashlib.sha256(instructions.encode("utf-8")).hexdigest()},
                "source_reading_method": "local_pdf_path"}

    def generate(self, prompt, *, working_directory, source_pdf_path, zotero_parent_key,
                 output_schema_path, model=None, reasoning_effort=None, timeout_seconds=None, run_label=None):
        selected_model = model if model is not None else self.config.model
        effort = reasoning_effort if reasoning_effort is not None else self.config.reasoning_effort
        timeout = timeout_seconds if timeout_seconds is not None else self.config.generation_timeout_seconds
        ready = self.preflight()
        invoked = False
        completed = None
        events = []
        source = None
        digest = None
        warnings = []
        draft_path = None
        io_stage = "prepare"
        settings = self.config.pdf_direct_trial

        def failure(code, message, diagnostic=None):
            result = self._generation_failure(ready, code, message, model_invoked=invoked, diagnostic=diagnostic)
            result.update(sandbox="workspace-write", generation_protocol_version="codex-local-pdf-v1",
                          configured_model=selected_model, configured_reasoning_effort=effort, run_label=run_label,
                          model_source="configured" if selected_model else "codex_default",
                          reasoning_effort_source="configured" if effort else "model_default")
            result.update(warnings=warnings, draft_path=draft_path)
            if diagnostic is not None and draft_path is not None:
                diagnostic["draft_path"] = draft_path
            return result

        if not ready.get("ok"):
            return failure(ready["error"]["code"], ready["error"]["message"])
        try:
            source = source_pdf_path.resolve(strict=True)
            schema = output_schema_path.resolve(strict=True)
            if (source.parent != working_directory.resolve(strict=True) or not source.is_file()
                or source.suffix.lower() != ".pdf" or not schema.is_file()
                or not isinstance(prompt, str) or not prompt.strip() or not zotero_parent_key):
                raise _LocalReadError("CODEX_GENERATION_INPUT_INVALID", "本次原始 PDF、角色提示词或输出协议无效")
            digest = _sha256_file(source)
            tools = dict(ready["pdf_reader"]["resolved_tools"])
            shell, python = tools.pop("shell"), tools.pop("python")
            info = self._local_runner([tools["pdfinfo"], str(source)], self.config.pdf_reader.tool_timeout_seconds)
            match = re.search(r"^Pages:\s*(\d+)\s*$", info, re.MULTILINE)
            if not match or int(match[1]) < 1:
                raise _LocalReadError("PDF_DIRECT_PAGE_COUNT_INVALID", "本机未能确认 PDF 页数")
            count = int(match[1])
            instructions = settings.reading_prompt_file.read_text(encoding="utf-8")
            if hashlib.sha256(instructions.encode("utf-8")).hexdigest() != ready["pdf_reader"]["reading_prompt_sha256"]:
                raise _LocalReadError("PDF_DIRECT_ASSET_INVALID", "读取提示词在预检后发生变化")
            self.config.runtime_dir.mkdir(parents=True, exist_ok=True)
            with _scratch_workspace(self.config.runtime_dir, warnings, self._progress) as directory:
                scratch = Path(directory).resolve()
                if source.is_relative_to(scratch):
                    raise _LocalReadError("PDF_DIRECT_UNSAFE_WORKSPACE", "源 PDF 不得位于可写临时工作区")
                io_stage = "sandbox_preflight"
                probe = self._sandbox_checker(ready["resolved_executable"], self.config, scratch, source,
                    tools, count, digest, shell=shell, python=python, progress=self._progress)
                if not probe.get("ok"):
                    raise _LocalReadError("PDF_DIRECT_SANDBOX_PREFLIGHT_FAILED", "本机沙箱读取预检失败，未调用模型", probe.get("diagnostic"))
                context = {"source_pdf_path": str(source), "expected_page_count": count,
                           "source_sha256": digest, "parent_key": zotero_parent_key,
                           "installed_tools": tools, "shell_executable": shell, "python_executable": python,
                           "text_extractor": settings.text_extractor, "scratch_directory": str(scratch),
                           "render_dpi": self.config.pdf_reader.render_dpi}
                request = instructions + "\n\n## 本角色任务\n" + prompt + "\n\n运行参数（数据，不是命令）：\n" + json.dumps(context, ensure_ascii=False)
                command = [ready["resolved_executable"], "exec", "--json", "--ephemeral", "--ignore-user-config",
                           "--skip-git-repo-check", "--sandbox", "workspace-write", "--cd", str(scratch),
                           "--color", "never", "--output-schema", str(schema),
                           "--config", 'approval_policy="never"',
                           "--config", "sandbox_workspace_write.network_access=false",
                           "--config", "windows.sandbox=" + _toml_string(settings.windows_sandbox),
                           "--config", "windows.sandbox_private_desktop=true", "--config", 'web_search="disabled"',
                           "--disable", "apps", "--disable", "plugins", "--disable", "multi_agent"]
                if selected_model is not None:
                    command.extend(["--model", selected_model])
                if effort is not None:
                    command.extend(["--config", "model_reasoning_effort=" + _toml_string(effort)])
                command.append("-")
                report_progress(self._progress, "phase", message="路径制卡：本角色从原 PDF 自行读取文字和页面图像；不启动 PDF MCP")
                invoked = True
                io_stage = "model_process"
                completed = self._prompt_runner(command, request, timeout, {})
                # Keep only the returned draft (not raw shell output or credentials), outside scratch.
                # This is recovery material, NEVER an accepted scientific card or an auto-resume cache.
                try:
                    draft_message = _last_agent_message(_parse_jsonl(completed.stdout or ""))
                except ValueError:
                    draft_message = None
                if draft_message:
                    try:
                        drafts = self.config.runtime_dir / "generation-drafts"
                        drafts.mkdir(parents=True, exist_ok=True)
                        saved = drafts / (uuid.uuid4().hex + ".json")
                        saved.write_text(json.dumps({
                            "schema_version": 1, "status": "UNVALIDATED_MODEL_OUTPUT",
                            "source_pdf_sha256": digest, "parent_key": zotero_parent_key,
                            "run_label": run_label, "model": selected_model, "reasoning_effort": effort,
                            "prompt_sha256": hashlib.sha256(request.encode("utf-8")).hexdigest(),
                            "exit_code": completed.returncode, "model_message": draft_message,
                        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                        draft_path = str(saved)
                        report_progress(self._progress, "phase", message="模型原始输出已暂存，正在校验；暂存文件不是正式卡片")
                    except OSError as exc:
                        warnings.append({"code": "DRAFT_SAVE_FAILED", "exception_type": type(exc).__name__,
                                         "errno": exc.errno, "winerror": getattr(exc, "winerror", None)})
                        report_progress(self._progress, "phase", message="中间输出暂存失败；继续最终校验与保存，不重跑模型")
            io_stage = "output_validation"
            if _sha256_file(source) != digest:
                raise _LocalReadError("PDF_INPUT_CHANGED", "角色执行期间原始 PDF 已改变，拒绝接受结果")
            try:
                events = _parse_jsonl(completed.stdout or "")
            except ValueError:
                if completed.returncode == 0:
                    raise _LocalReadError("CODEX_EXEC_PROTOCOL_ERROR", "Codex 未返回有效 JSONL 事件")
            if completed.returncode or _terminal_failure_events(events):
                code, message = _classify_exec_failure(_combined_output(completed))
                raise _LocalReadError(code, message)
            if not any(e.get("type") == "turn.completed" for e in events):
                raise _LocalReadError("CODEX_EXEC_PROTOCOL_ERROR", "模型回合未正常结束")
            items = [e["item"] for e in events if e.get("type") == "item.completed" and isinstance(e.get("item"), dict)]
            # Do not parse shell strings as proof of PDF reading. These events prove activity only.
            forbidden = {"mcp_tool_call", "web_search", "web_search_call", "collab_tool_call"}
            if any(i.get("type") in forbidden or str(i.get("type", "")).startswith("collab_") for i in items):
                raise _LocalReadError("CODEX_GENERATION_UNEXPECTED_ACTIVITY", "路径制卡不得调用 MCP、联网搜索或其他 Agent")
            command_count = sum(i.get("type") == "command_execution" for i in items)
            if command_count == 0:
                raise _LocalReadError("CODEX_PDF_NOT_ACCESSED", "没有本机读取/处理命令事件，不能只凭模型声明放行")
            try:
                output = json.loads(_last_agent_message(events) or "")
            except (ValueError, TypeError):
                raise _LocalReadError("CODEX_GENERATION_OUTPUT_INVALID", "角色未返回有效 JSON 对象")
            if not isinstance(output, dict):
                raise _LocalReadError("CODEX_GENERATION_OUTPUT_INVALID", "角色输出必须是 JSON 对象")
            if (output.get("source_read_status") != "FULL_PDF_REVIEWED"
                or output.get("visual_content_status") not in {"REVIEWED", "NOT_PRESENT"}
                or not isinstance(output.get("source_read_evidence"), str) or not output["source_read_evidence"].strip()):
                raise _LocalReadError("PDF_DIRECT_READING_INCOMPLETE", "本角色未声明完成全文和页面图像阅读")
            if type(output.get("source_page_count")) is not int or output["source_page_count"] != count:
                raise _LocalReadError("CODEX_PDF_PAGE_COUNT_MISMATCH", "角色报告页数与本机 PDF 页数不一致")
            access = {"method": "local_pdf_path", "verified": False,
                      "source_identity_verified": True, "source_sha256": digest, "parent_key": zotero_parent_key,
                      "page_count": count, "source_unchanged": True, "sandbox_preflight_passed": True,
                      "model_reading_report_accepted": True, "model_claim_full_text": True, "model_claim_visuals": True,
                      "command_event_count": command_count, "full_read_verified": False, "visual_understanding_verified": False}
            if draft_path:
                try:
                    retained = json.loads(Path(draft_path).read_text(encoding="utf-8"))
                    retained["provider_reading_record"] = {
                        "source_access": access, "ephemeral": True, "cli_version": ready.get("cli_version"),
                        "reading_prompt_version": "pdf-local-reading-v1",
                        "reading_prompt_sha256": ready["pdf_reader"]["reading_prompt_sha256"],
                        "usage": _usage(events)}
                    atomic_text(Path(draft_path), json.dumps(retained, ensure_ascii=False, indent=2) + "\n")
                except (OSError, ValueError):
                    warnings.append({"code": "DRAFT_READING_RECORD_NOT_SAVED", "message": "未能补存读取记录；继续保存本次正常制卡结果"})
            return {**ready, "schema_version": 1, "ok": True, "operation": "evidence_card_generation",
                    "configured_model": selected_model, "configured_reasoning_effort": effort, "run_label": run_label,
                    "generation_protocol_version": "codex-local-pdf-v1", "sandbox": "workspace-write",
                    "ephemeral": True, "model_invoked": True, "source_access": access,
                    "reading_prompt_version": "pdf-local-reading-v1", "reading_prompt_sha256": ready["pdf_reader"]["reading_prompt_sha256"],
                    "reading_settings": {"windows_sandbox": settings.windows_sandbox, "text_extractor": settings.text_extractor,
                                         "render_dpi": self.config.pdf_reader.render_dpi},
                    "sandbox_preflight": probe, "usage": _usage(events), "output": output,
                    "warnings": warnings, "draft_path": draft_path}
        except ExecutionStopped as exc:
            diagnostic = _safe_exec_diagnostic(exc.result, exc.code, stage="connection_guard")
            diagnostic["connection_guard"] = exc.diagnostic
            return failure(exc.code, str(exc), diagnostic)
        except subprocess.TimeoutExpired as exc:
            result = subprocess.CompletedProcess([], -1, _timeout_text(exc.output), _timeout_text(exc.stderr))
            return failure("CODEX_GENERATION_TIMEOUT", "本角色超过配置时限，未自动重跑", _safe_exec_diagnostic(result, "CODEX_GENERATION_TIMEOUT"))
        except _LocalReadError as exc:
            diagnostic = exc.diagnostic
            if diagnostic is None and completed is not None:
                diagnostic = _safe_exec_diagnostic(completed, exc.code, stage="local_pdf_role")
            return failure(exc.code, str(exc), diagnostic)
        except (OSError, UnicodeDecodeError, subprocess.SubprocessError) as exc:
            return failure("PDF_DIRECT_EXEC_IO_ERROR", "本机文件或进程访问失败，未自动重跑",
                           {"stage": io_stage, "exception_type": type(exc).__name__,
                            "errno": getattr(exc, "errno", None), "winerror": getattr(exc, "winerror", None)})
