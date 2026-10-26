"""Windows PDF capability checks without a model call or changes to the source."""
from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

from hydrolitagent.cards.adapters.runners.diagnostics import (
    safe_exec_diagnostic,
    sanitize_diagnostic_text,
)
from hydrolitagent.cards.infrastructure.toml import toml_string
from hydrolitagent.cards.card_generators.streaming import run_streaming_prompt
from hydrolitagent.cards.config import AppConfig, CardGeneratorConfig
from hydrolitagent.cards.progress import report_progress


# Fixed, reviewed probe; PDF text is counted, never returned as model input.
# Dynamic paths arrive as data through argv, never as executable source.
PROBE_SCRIPT = r'''
import base64, hashlib, json, pathlib, re, subprocess, sys
p = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
checks = []
def invoke(name, args):
    result = subprocess.run([p['tools'][name], *args], capture_output=True,
                            timeout=p['tool_timeout'], check=False,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        sys.stderr.write(result.stderr.decode('utf-8', errors='replace')[-4000:])
        raise RuntimeError('local_pdf_tool_failed:' + name + ':exit=' + str(result.returncode))
    return result.stdout
def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()
try:
    source = p['source']
    if digest(source) != p['sha256']:
        raise RuntimeError('source_fingerprint_changed')
    checks.append({'name':'source_read', 'status':'pass'})
    info = invoke('pdfinfo', [source]).decode('utf-8', errors='replace')
    match = re.search(r'^Pages:\s*(\d+)\s*$', info, flags=re.MULTILINE)
    if not match or int(match.group(1)) != p['page_count']:
        raise RuntimeError('source_page_count_mismatch')
    checks.append({'name':'pdfinfo', 'status':'pass', 'page_count':int(match.group(1))})
    if p['text_extractor'] == 'pypdf':
        import pypdf
        text = pypdf.PdfReader(source).pages[0].extract_text() or ''
    else:
        text = invoke('pdftotext', ['-f','1','-l','1','-enc','UTF-8',source,'-']).decode('utf-8',errors='replace')
    if len(text.strip()) < 40:
        raise RuntimeError('first_page_text_unavailable')
    checks.append({'name':'text_extract', 'status':'pass', 'character_count':len(text.strip())})
    prefix = str(pathlib.Path(p['workspace']) / 'sandbox-probe-page')
    invoke('pdftoppm', ['-f','1','-l','1','-singlefile','-r',str(p['dpi']),'-png',source,prefix])
    png = pathlib.Path(prefix + '.png')
    with png.open('rb') as f:
        if f.read(8) != b'\x89PNG\r\n\x1a\n':
            raise RuntimeError('page_render_invalid')
    checks.append({'name':'page_render', 'status':'pass', 'file_size_bytes':png.stat().st_size})
    if digest(source) != p['sha256']:
        raise RuntimeError('source_fingerprint_changed')
    png.unlink()
    print(json.dumps({'ok':True, 'checks':checks}))
except Exception as exc:
    print(json.dumps({'ok':False, 'checks':checks, 'failure_type':type(exc).__name__,
                      'failure_reason':str(exc) if type(exc) is RuntimeError else None,
                      'errno':getattr(exc,'errno',None), 'winerror':getattr(exc,'winerror',None)}))
    sys.exit(3)
'''


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_sandbox_probe_command(
    executable: str, config: AppConfig | CardGeneratorConfig, workspace: Path, source: Path, tools: dict[str, str],
    page_count: int, sha256: str, shell: str, python: str,
) -> list[str]:
    generator = config.card_generator if isinstance(config, AppConfig) else config
    trial = generator.pdf_direct_trial
    assert trial is not None
    parameters = {"source": str(source), "tools": tools, "workspace": str(workspace),
                  "page_count": page_count, "sha256": sha256,
                  "tool_timeout": generator.pdf_reader.tool_timeout_seconds,
                  "dpi": generator.pdf_reader.render_dpi,
                  "text_extractor": trial.text_extractor}
    # EncodedCommand is just a quoting transport for the fixed PowerShell wrapper.
    parameter_data = base64.b64encode(json.dumps(parameters, ensure_ascii=False).encode("utf-8")).decode("ascii")
    script = ("$ErrorActionPreference = 'Stop'; & " + _ps_quote(python) + " '-c' "
              + _ps_quote(PROBE_SCRIPT) + " " + _ps_quote(parameter_data)
              + "; exit $LASTEXITCODE")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    # This installed native Windows CLI uses `sandbox COMMAND`, not `sandbox windows COMMAND`.
    # Explicit built-in profile prevents inheriting personal full-access permissions.
    return [executable, "sandbox", "-P", ":workspace", "-C", str(workspace),
            "--include-managed-config", "-c", "windows.sandbox=" + toml_string(trial.windows_sandbox),
            "-c", "windows.sandbox_private_desktop=true",
            "--", shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


def check_pdf_sandbox(
    executable: str, config: AppConfig | CardGeneratorConfig, workspace: Path, source: Path, tools: dict[str, str],
    page_count: int, sha256: str, *, shell: str, python: str, progress=None, runner=None,
) -> dict[str, Any]:
    generator = config.card_generator if isinstance(config, AppConfig) else config
    trial = generator.pdf_direct_trial
    assert trial is not None
    report_progress(progress, "phase", message="本机权限预检：在 Windows 沙箱中检查 shell、PDF 文字提取和页面渲染（不调用模型）")
    command = build_sandbox_probe_command(executable, config, workspace, source, tools,
                                          page_count, sha256, shell, python)
    runner = runner or run_streaming_prompt
    checks: list[dict[str, Any]] = []
    diagnostic = None
    result = None
    try:
        # Do not forward streaming status: this subprocess is a sandbox probe, not an AI call.
        result = runner(command, "", trial.preflight_timeout_seconds)
        try:
            payload = json.loads(result.stdout.strip())
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("checks"), list):
            for entry in payload["checks"]:
                if isinstance(entry, dict) and entry.get("name") in {"source_read", "pdfinfo", "text_extract", "page_render"}:
                    # This output comes from fixed host code, nevertheless persist only known fields.
                    checks.append({key: entry[key] for key in ("name", "status", "page_count", "character_count", "file_size_bytes") if key in entry})
        success = (result.returncode == 0 and isinstance(payload, dict) and payload.get("ok") is True
                   and [c.get("name") for c in checks] == ["source_read", "pdfinfo", "text_extract", "page_render"]
                   and all(c.get("status") == "pass" for c in checks))
        if not success:
            diagnostic = safe_exec_diagnostic(result, "PDF_DIRECT_SANDBOX_PREFLIGHT_FAILED", stage="local_sandbox_preflight")
            if isinstance(payload, dict):
                diagnostic["probe_failure"] = {
                    k: sanitize_diagnostic_text(payload[k]) if isinstance(payload[k], str) else payload[k]
                    for k in ("failure_type", "failure_reason", "errno", "winerror")
                    if k in payload and (payload[k] is None or type(payload[k]) in (str, int))
                }
    except subprocess.TimeoutExpired:
        success = False
        diagnostic = {"stage": "local_sandbox_preflight", "category": "TIMEOUT", "summary": "本机沙箱检查超时，已停止本次检查进程"}
    except (OSError, subprocess.SubprocessError):
        success = False
        diagnostic = {"stage": "local_sandbox_preflight", "category": "PROCESS_ERROR", "summary": "无法启动或读取本机沙箱检查进程"}
    outcome = {"ok": success, "model_invoked": False, "windows_sandbox": trial.windows_sandbox,
               "text_extractor": trial.text_extractor,
               "permission_profile": ":workspace", "checks": checks,
               "scope": "仅验证本机 shell/PDF 工具；不证明模型工具路由或论文理解已通过"}
    if diagnostic is not None:
        outcome["diagnostic"] = diagnostic
    report_progress(progress, "phase", message="本机权限预检通过，尚未调用模型" if success else "本机权限预检失败，停止；不会调用模型")
    return outcome
