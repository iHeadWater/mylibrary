"""Claude CLI backend for the existing single-agent workflow, with native PDF Read receipts."""
from __future__ import annotations
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError
from hydrolitagent.cards.domain.source_access import CLAUDE_PDF_READ
from hydrolitagent.cards.card_generators.streaming import run_streaming_prompt
from hydrolitagent.cards.progress import report_progress
from hydrolitagent.cards._paths import PROMPTS_DIR

READING_PROMPT = PROMPTS_DIR / "pdf-claude-reading-v1.md"
PROTOCOL = "claude-local-pdf-v1"


class ClaudePdfProtocolError(ValueError):
    """Controlled protocol failure; never constructed from raw CLI diagnostics."""


# 对外报错的总长上限，以及其中模型自报证据的上限。证据上限必须明显小于总上限，
# 否则外层再次截断会把证据连同其后的内容一起切掉，等于把刚补上的原因又丢掉。
DIAGNOSTIC_LIMIT = 1200
EVIDENCE_LIMIT = 600
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SECRET_KEY = r"[A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|APIKEY|API_KEY|CREDENTIAL)[A-Za-z0-9_]*"
_SECRET_VALUE = r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}]+)'''
_LOG_OR_COMMAND = re.compile(
    r"(?i)```|\b(?:traceback|stdout|stderr|command failed)\b|(?<!\S)--?[a-z][\w-]*(?:\s|=|$)"
)

# 只隐去高置信度的凭据形态。刻意不匹配裸十六进制或长随机串：读取证据里合法包含
# 源 PDF 的 sha256，也包含页码与文件名，粗暴屏蔽会把最有用的诊断信息一起毁掉。
_REDACTIONS = (
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "[已隐去]"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{8,}"), r"\1 [已隐去]"),
    (re.compile(rf'''(?i)(["']{_SECRET_KEY}["']\s*:\s*){_SECRET_VALUE}'''), r"\1[已隐去]"),
    (re.compile(rf"(?i)\b({_SECRET_KEY})\s*=\s*{_SECRET_VALUE}"), r"\1=[已隐去]"),
)


def _redact(text):
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def _bounded_diagnostic(text, limit=DIAGNOSTIC_LIMIT):
    """把诊断文本收敛为单行、有界长、不含控制字符，并隐去高置信度凭据形态。

    异常文本可能来自文件系统、PDF 解析或子进程，模型给的证据也不受本模块控制，
    先移除终端转义及控制字符，再隐去已知凭据形态、压成单行并截断。
    这是尽力过滤，不是任意文本均可安全公开的保证。
    """
    if not isinstance(text, str):
        return ""
    text = _ANSI_ESCAPE.sub("", text)
    cleaned = "".join(ch if ch.isprintable() else " " if ch.isspace() else "" for ch in text)
    cleaned = _redact(cleaned)
    return " ".join(cleaned.split())[:limit]


def read_receipts(events, source, count):
    """Pair successful native Read tool results with explicit physical-page requests."""
    requests, successful, seen_results, seen_ids = {}, set(), set(), set()
    for event in events:
        if event.get("type") not in {"assistant", "user"}:
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            raise ClaudePdfProtocolError("工具消息格式无效")
        blocks = message.get("content", [])
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                if block.get("name") != "Read":
                    # The CLI may use its internal StructuredOutput tool for --json-schema.
                    if block.get("name") == "StructuredOutput":
                        continue
                    raise ClaudePdfProtocolError("出现 Read 之外的工具活动")
                data = block.get("input", {})
                if not isinstance(data, dict):
                    raise ClaudePdfProtocolError("Read 输入格式无效")
                file = data.get("file_path")
                if not isinstance(file, str) or Path(file).resolve() != source.resolve():
                    raise ClaudePdfProtocolError("读取了本次 PDF 之外的文件")
                # 先校验请求编号唯一性，再决定是否计入页覆盖：无页码的探测式读取不产生页覆盖，
                # 但它的编号同样必须唯一——否则后续成功回执会借旧编号把未读页记成已读。
                ident = block.get("id")
                if not isinstance(ident, str) or not ident.strip() or ident in seen_ids:
                    raise ClaudePdfProtocolError("Read 请求 ID 无效或重复")
                seen_ids.add(ident)
                raw_pages = data.get("pages")
                if raw_pages is None or not str(raw_pages).strip():
                    # 探测式读取不产生页覆盖；覆盖完整性仍由下方统一强制。
                    continue
                match = re.fullmatch(r"(\d+)(?:-(\d+))?", str(raw_pages))
                if not match:
                    raise ClaudePdfProtocolError("PDF Read 的 pages 不是有效物理页范围")
                start, end = int(match[1]), int(match[2] or match[1])
                if not 1 <= start <= end <= count or end-start >= 20:
                    raise ClaudePdfProtocolError("Read 页范围无效")
                requests[ident] = set(range(start, end+1))
            elif block.get("type") == "tool_result":
                ident = block.get("tool_use_id")
                if ident in requests and ident not in seen_results:
                    seen_results.add(ident)
                    if block.get("is_error", False) is False and block.get("content"):
                        successful.update(requests[ident])
    if successful != set(range(1, count+1)):
        raise ClaudePdfProtocolError("没有收到覆盖全部 PDF 页的成功 Read 回执")
    return sorted(successful)


class ClaudeCliAdapter:
    def __init__(self, config, *, progress=None, runner=None, finder=None):
        self.config, self.progress = config, progress
        self.runner = runner or run_streaming_prompt
        self.finder = finder or shutil.which

    def preflight(self, **kwargs):
        executable = self.finder(self.config.executable)
        return {"ok": bool(executable), "adapter": "claude_cli", "resolved_executable": executable,
                "model_invoked": False, "error": None if executable else {
                    "code": "CLAUDE_NOT_FOUND", "message": "未找到 Claude CLI；请安装或配置本机可执行文件路径"}}

    def smoke_test(self):
        ready = self.preflight()
        result = {"ok": False, "operation": "card_generator_smoke_test", "model_invoked": False}
        if not ready["ok"]:
            return {**result, "error": ready["error"]}
        try:
            self.config.runtime_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="claude-smoke-", dir=self.config.runtime_dir) as directory:
                command = [ready["resolved_executable"], "--print", "--safe-mode", "--restricted",
                           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--tools", "",
                           "--no-session-persistence", "--output-format", "stream-json", "--verbose"]
                if self.config.model:
                    command += ["--model", self.config.model]
                result["model_invoked"] = True
                completed = self.runner(command, "Only output HYDRO_GENERATOR_OK. Do not use tools.",
                    self.config.smoke_test_timeout_seconds, cwd=directory, provider_label="Claude")
            events = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
            terminal = [e for e in events if isinstance(e, dict) and e.get("type") == "result"]
            if (completed.returncode == 0 and len(terminal) == 1 and terminal[0].get("subtype") == "success"
                and terminal[0].get("is_error") is not True and terminal[0].get("result", "").strip() == "HYDRO_GENERATOR_OK"):
                return {**result, "ok": True}
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            pass
        return {**result, "error": {"code": "CLAUDE_SMOKE_FAILED", "message": "Claude 最小调用未通过，请检查本机认证和所选模型"}}

    def generate(self, prompt, *, working_directory, source_pdf_path, zotero_parent_key,
                 output_schema_path, run_label=None, model=None, reasoning_effort=None, timeout_seconds=None):
        selected_model = model if model is not None else self.config.model
        effort = reasoning_effort if reasoning_effort is not None else self.config.reasoning_effort
        timeout = timeout_seconds if timeout_seconds is not None else self.config.generation_timeout_seconds
        result = {"ok": False, "operation": "evidence_card_generation", "model_invoked": False,
                  "generation_protocol_version": PROTOCOL, "ephemeral": True,
                  "configured_model": selected_model, "configured_reasoning_effort": effort,
                  "warnings": []}
        try:
            ready = self.preflight()
            if not ready["ok"]:
                return {**result, "error": ready["error"]}
            source = Path(source_pdf_path).resolve(strict=True)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            reader = PdfReader(source)
            if reader.is_encrypted or not reader.pages:
                raise ClaudePdfProtocolError("需要未加密且至少有一页的 PDF")
            count = len(reader.pages)
            instructions = READING_PROMPT.read_text(encoding="utf-8")
            schema = json.loads(Path(output_schema_path).read_text(encoding="utf-8"))
            request = instructions + "\n\n## 本角色任务\n" + prompt + "\n\n运行参数（数据）\n" + json.dumps(
                {"source_pdf_path": str(source), "expected_page_count": count,
                 "source_sha256": digest, "parent_key": zotero_parent_key}, ensure_ascii=False)
            self.config.runtime_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="claude-paper-", dir=self.config.runtime_dir) as directory:
                command = [ready["resolved_executable"], "--print", "--safe-mode", "--restricted",
                           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                           "--tools", "Read", "--allowedTools", "Read", "--add-dir", str(source.parent),
                           "--no-session-persistence", "--output-format", "stream-json", "--verbose",
                           "--json-schema", json.dumps(schema, ensure_ascii=False, separators=(",", ":"))]
                if selected_model:
                    command += ["--model", selected_model]
                if effort:
                    command += ["--effort", effort]
                report_progress(self.progress, "phase", message="Claude 正在通过只读 PDF 工具生成主体卡")
                result["model_invoked"] = True
                completed = self.runner(command, request, timeout,
                    progress=self.progress, connection_guard=self.config.connection_guard, cwd=directory, provider_label="Claude")
            # Never return raw stdout/stderr: CLI diagnostics may include local auth settings.
            events = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
            if any(not isinstance(event, dict) for event in events):
                raise ClaudePdfProtocolError("Claude 返回了非对象事件")
            terminal = [event for event in events if event.get("type") == "result"]
            if completed.returncode or len(terminal) != 1 or terminal[0].get("is_error") is True or terminal[0].get("subtype") != "success":
                return {**result, "error": {"code": "CLAUDE_GENERATION_FAILED", "message": "Claude 未成功完成；请检查本机登录、模型选择与服务可用性"}}
            output = terminal[0].get("structured_output")
            if not isinstance(output, dict):
                raise ClaudePdfProtocolError("Claude 没有返回所需结构化输出")
            try:
                pages = read_receipts(events, source, count)
            except ClaudePdfProtocolError as exc:
                # 读不到页时，模型自报的读取状态与证据才是可行动的原因（例如缺少 PDF 渲染工具），
                # 仅报页覆盖不足会把原因再次藏起来。不回传原始 stdout，只带这两个既有字段。
                status = output.get("source_read_status")
                if not isinstance(status, str) or status not in {"UNREADABLE", "FULL_PDF_REVIEWED"}:
                    status = "INVALID"
                hint = f"；模型自报（未经独立验证）source_read_status={status}"
                raw_evidence = output.get("source_read_evidence")
                if isinstance(raw_evidence, str) and _LOG_OR_COMMAND.search(_ANSI_ESCAPE.sub("", raw_evidence)):
                    evidence = "模型说明含命令或日志片段，已省略；请检查 PDF 渲染工具及当前进程 PATH"
                else:
                    evidence = _bounded_diagnostic(raw_evidence, limit=EVIDENCE_LIMIT)
                if evidence:
                    hint += f"、证据：{evidence}"
                raise ClaudePdfProtocolError(f"{exc}{hint}") from exc
            if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                return {**result, "error": {"code": "PDF_INPUT_CHANGED", "message": "读取期间 PDF 已改变"}}
            if (type(output.get("source_page_count")) is not int or output["source_page_count"] != count
                or output.get("source_read_status") != "FULL_PDF_REVIEWED"
                or output.get("visual_content_status") not in {"REVIEWED", "NOT_PRESENT"}
                or not isinstance(output.get("source_read_evidence"), str) or not output["source_read_evidence"].strip()):
                raise ClaudePdfProtocolError("Claude 阅读声明不完整或页数不一致")
            access = {"method": CLAUDE_PDF_READ, "source_sha256": digest, "parent_key": zotero_parent_key,
                      "page_count": count, "source_identity_verified": True, "source_unchanged": True,
                      "model_reading_report_accepted": True, "model_claim_full_text": True, "model_claim_visuals": True,
                      "read_only_tools": True, "pages_requested_successfully": pages,
                      "verified": False, "full_read_verified": False, "visual_understanding_verified": False}
            return {**result, "ok": True, "source_access": access, "output": output,
                    "reading_prompt_version": "pdf-claude-reading-v1",
                    "reading_prompt_sha256": hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
                    "usage": terminal[0].get("usage")}
        except (OSError, ValueError, TypeError, PyPdfError, subprocess.SubprocessError) as exc:
            # 仅本模块的受控协议错误可回显；第三方异常可能携带完整命令或认证设置。
            if isinstance(exc, ClaudePdfProtocolError):
                detail = _bounded_diagnostic(str(exc))
            elif isinstance(exc, subprocess.TimeoutExpired):
                detail = "Claude 调用超时；请检查服务状态或调整超时设置"
            elif isinstance(exc, OSError):
                detail = "本地文件或程序无法访问；请检查 PDF、CLI 路径及访问权限"
            elif isinstance(exc, PyPdfError):
                detail = "PDF 解析失败；请检查文件是否完整且可读取"
            elif isinstance(exc, subprocess.SubprocessError):
                detail = "Claude 子进程被停止或通信失败；请检查连接状态"
            else:
                detail = "输出或配置格式无效；请检查 CLI 版本与结构化输出协议"
            return {**result, "error": {"code": "CLAUDE_PDF_GENERATION_FAILED",
                    "message": f"Claude PDF 流程失败（{type(exc).__name__}：{detail}）；未重试或保存已接受草稿"}}
