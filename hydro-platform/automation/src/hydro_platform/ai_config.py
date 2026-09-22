"""Provider selection over the existing card-generator interface, with portable defaults."""
from __future__ import annotations
import os
import sys
import math
import shutil
import platform
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

from hydrolitagent._config import PROJECT_ROOT, read_dotenv_values, resolve_literature_root
from hydro_platform.config import CardGeneratorConfig, PdfReaderConfig, PdfDirectTrialConfig, ConnectionGuardConfig

PLATFORM = Path(__file__).resolve().parents[3]
DEFAULT_FILE = PROJECT_ROOT / "configs/ai.toml"
DEFAULTS = {"provider": "codex", "model": "", "executable": "", "reasoning_effort": "",
            "timeout_seconds": 1500, "python_executable": "", "pdfinfo_executable": "",
            "pdftotext_executable": "", "pdftoppm_executable": ""}


class AIConfigError(ValueError):
    pass


def resolve_ai_config(config_file=None, **overrides):
    env = {**read_dotenv_values(), **os.environ}
    selected = config_file or env.get("HYDRO_PLATFORM_AI_CONFIG")
    path = Path(selected).expanduser().resolve() if selected else DEFAULT_FILE
    values = dict(DEFAULTS)
    if selected or path.exists():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))
            if set(raw) != {"ai"} or not isinstance(raw["ai"], dict) or raw["ai"].keys() - DEFAULTS.keys():
                raise AIConfigError("AI 配置只接受公开的 [ai] 字段，凭据请交给本机 CLI")
            values.update(raw["ai"])
        except (OSError, ValueError) as exc:
            raise AIConfigError(f"无法读取 AI 选择配置：{path}（{type(exc).__name__}）") from exc
    for key in DEFAULTS:
        name = "HYDRO_PLATFORM_AI_" + key.upper()
        if name in env:
            values[key] = env[name]
    for key, value in overrides.items():
        if key not in DEFAULTS:
            raise AIConfigError(f"未知 AI 配置：{key}")
        if value is not None:
            values[key] = value
    provider = values["provider"]
    if provider not in ("codex", "claude"):
        raise AIConfigError("provider 仅支持 codex 或 claude")
    for key in DEFAULTS.keys() - {"timeout_seconds"}:
        if not isinstance(values[key], str) or "\n" in values[key] or "\x00" in values[key]:
            raise AIConfigError(f"{key} 必须为单行字符串")
    try:
        timeout = float(values["timeout_seconds"])
    except (TypeError, ValueError) as exc:
        raise AIConfigError("timeout_seconds 必须为正数") from exc
    if isinstance(values["timeout_seconds"], bool) or not math.isfinite(timeout) or not 1 <= timeout <= 7200:
        raise AIConfigError("timeout_seconds 必须为 1..7200 秒")
    values["timeout_seconds"] = timeout
    efforts = {"", "low", "medium", "high", "xhigh", "max"} if provider == "claude" else {"", "none", "minimal", "low", "medium", "high", "xhigh", "max"}
    if values["reasoning_effort"] not in efforts:
        raise AIConfigError("当前提供方不支持该 reasoning_effort")
    values["executable"] = values["executable"] or provider
    # npm wrappers have a much smaller Windows command-line limit; prefer their installed native binary.
    if os.name == "nt" and values["executable"] == provider:
        found = shutil.which(provider)
        if found and Path(found).suffix.lower() in {".cmd", ".bat", ".ps1"}:
            npm = Path(found).parent / "node_modules"
            if provider == "claude":
                native = npm / "@anthropic-ai/claude-code/bin/claude.exe"
            else:
                arm = platform.machine().lower() in {"arm64", "aarch64"}
                package, arch = ("codex-win32-arm64", "aarch64") if arm else ("codex-win32-x64", "x86_64")
                native = npm / f"@openai/codex/node_modules/@openai/{package}/vendor/{arch}-pc-windows-msvc/bin/codex.exe"
            if native.is_file():
                values["executable"] = str(native)
    return values


def subject_card_config(selection, *, base_config=None):
    """Reuse existing dataclasses/adapters; single-paper work does not need Zotero/scheduler config."""
    if base_config is not None:
        cfg = base_config.card_generator
    else:
        suffix = ".exe" if os.name == "nt" else ""
        tool_dir = PLATFORM / ".tools/poppler/Library/bin"
        def tool(name):
            bundled = tool_dir / (name + suffix)
            return str(bundled) if bundled.is_file() else name
        reader = PdfReaderConfig("local_path", "hydro_pdf_reader", None,
                  PLATFORM / "automation/src/hydro_platform/pdf_reader_mcp.py",
                  tool("pdfinfo"), tool("pdftotext"), tool("pdftoppm"), 120, 4, 60000, 15, 120)
        trial = PdfDirectTrialConfig(PLATFORM / "automation/prompts/pdf-direct-read-trial-v2.md",
                  PLATFORM / "automation/schemas/pdf-direct-read-trial-output.schema.json", 1200,
                  python_executable=sys.executable, text_extractor="pypdf",
                  reading_prompt_file=PLATFORM / "automation/prompts/pdf-local-reading-v1.md")
        cfg = CardGeneratorConfig("codex_cli", "codex", "chatgpt_account", 10, None, None, 120, 1500, reader,
                  workflow_mode="single_agent", pdf_direct_trial=trial, runtime_dir=PLATFORM / ".runtime",
                  connection_guard=ConnectionGuardConfig(reconnect_stop_enabled=False, idle_timeout_seconds=1500))
    reader = cfg.pdf_reader
    tools = {k: selection[k] for k in ("pdfinfo_executable", "pdftotext_executable", "pdftoppm_executable") if selection[k]}
    trial = cfg.pdf_direct_trial
    if trial is None:
        raise AIConfigError("生成配置缺少 PDF 读取参数")
    trial = replace(trial, python_executable=selection["python_executable"] or sys.executable)
    cfg = replace(cfg, adapter=selection["provider"] + "_cli", executable=selection["executable"],
          model=selection["model"] or None, reasoning_effort=selection["reasoning_effort"] or None,
          generation_timeout_seconds=selection["timeout_seconds"], workflow_mode="single_agent", multi_agent_workflow=None,
          pdf_reader=replace(reader, adapter="local_path", **tools), pdf_direct_trial=trial)
    paths = base_config.paths if base_config is not None else SimpleNamespace(
          evidence_card_generation_prompt_file=PLATFORM / "automation/prompts/evidence-card-generation-v8.md",
          evidence_card_templates_dir=PLATFORM / "templates/evidence-cards",
          evidence_card_template_catalog_file=PLATFORM / "templates/evidence-cards/_catalog.json")
    return SimpleNamespace(card_generator=cfg, paths=paths)


def describe_ai(selection, *, output_root=None):
    return {"ok": True, "operation": "ai_config", "ai": selection,
            "literature_root": str(resolve_literature_root(root=output_root)),
            "credentials": "由所选 CLI 使用本机登录或环境变量；本配置不保存凭据"}
