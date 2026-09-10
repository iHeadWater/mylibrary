"""Single isolated text-only call for theme discovery/refinement (no PDF or tools)."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from hydro_platform.card_generators.codex_cli import (
    CodexCliAdapter, _classify_exec_failure, _combined_output, _last_agent_message,
    _parse_jsonl, _safe_exec_diagnostic, _terminal_failure_events, _toml_string, _usage,
)
from hydro_platform.card_generators.streaming import ExecutionStopped
from hydro_platform.publication import atomic_text, text_hash


class CodexTextAdapter(CodexCliAdapter):
    def generate(self, prompt, *, output_schema_path, timeout_seconds=None, run_label=None):
        ready = self.preflight(check_pdf_reader=False)
        if not ready.get("ok"):
            return ready
        timeout = timeout_seconds or self.config.generation_timeout_seconds
        draft_path = None
        try:
            runtime = self.config.runtime_dir
            runtime.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="theme-text-", dir=runtime, ignore_cleanup_errors=True) as scratch:
                command = [ready["resolved_executable"], "exec", "--json", "--ephemeral",
                    "--ignore-user-config", "--skip-git-repo-check", "--sandbox", "read-only",
                    "--cd", scratch, "--color", "never", "--output-schema", str(Path(output_schema_path).resolve()),
                    "--config", 'approval_policy="never"', "--config", 'web_search="disabled"',
                    "--disable", "apps", "--disable", "plugins", "--disable", "multi_agent"]
                if self.config.model:
                    command += ["--model", self.config.model]
                if self.config.reasoning_effort:
                    command += ["--config", "model_reasoning_effort=" + _toml_string(self.config.reasoning_effort)]
                command.append("-")
                result = self._prompt_runner(command, prompt, timeout, {})
                try:
                    events = _parse_jsonl(result.stdout or "")
                except ValueError:
                    events = []
                message = _last_agent_message(events)
                if message:
                    # Retain output before decoding. A malformed transport must not erase useful work.
                    saved = runtime / "theme-drafts" / (uuid4().hex + ".json")
                    atomic_text(saved, json.dumps({"run_label": run_label, "prompt_sha256": text_hash(prompt),
                        "exit_code": result.returncode, "model_message": message}, ensure_ascii=False))
                    draft_path = str(saved)
            if result.returncode or _terminal_failure_events(events):
                code, message = _classify_exec_failure(_combined_output(result))
                return {"ok": False, "error": {"code": code, "message": message,
                    "diagnostic": _safe_exec_diagnostic(result, code), "draft_path": draft_path}}
            if not any(e.get("type") == "turn.completed" for e in events):
                raise ValueError("模型回合未正常结束")
            forbidden = {"command_execution", "file_change", "mcp_tool_call", "web_search", "web_search_call"}
            for event in events:
                kind = str((event.get("item") or {}).get("type", ""))
                if kind in forbidden or kind.startswith("collab_"):
                    raise ValueError("纯文本主题步骤出现了范围外的工具调用")
            output = json.loads(message or "")
            if not isinstance(output, dict):
                raise ValueError("模型未返回可读取的 JSON 对象")
            return {"ok": True, "output": output, "ephemeral": True, "model_invoked": True,
                "model": self.config.model, "reasoning_effort": self.config.reasoning_effort,
                "usage": _usage(events), "draft_path": draft_path, "cli_version": ready.get("cli_version")}
        except ExecutionStopped as exc:
            return {"ok": False, "error": {"code": exc.code, "message": str(exc),
                "diagnostic": _safe_exec_diagnostic(exc.result, exc.code)}}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": {"code": "CODEX_GENERATION_TIMEOUT", "message": "主题步骤超过配置时限，已完成步骤保留"}}
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": {"code": "THEME_PROVIDER_ERROR",
                "message": "主题调用的进程、文件或传输结构异常；不是正文格式检查失败",
                "exception_type": type(exc).__name__, "draft_path": draft_path}}
