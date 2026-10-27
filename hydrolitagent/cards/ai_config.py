"""Provider selection over the existing card-generator interface, with portable defaults."""
from __future__ import annotations
import os
import math
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

from hydrolitagent._config import PROJECT_ROOT, read_dotenv_values, resolve_literature_root
from hydrolitagent.cards.adapters.runners.registry import (
    ids as runner_ids,
    planned_ids as planned_runner_ids,
)
from hydrolitagent.cards.config import (
    CardGeneratorConfig,
    ConnectionGuardConfig,
    resolve_pipeline_mode,
)
from hydrolitagent.cards._paths import PROMPTS_DIR, TEMPLATES_DIR, REPO_ROOT


DEFAULT_FILE = PROJECT_ROOT / "configs/ai.toml"
# ``max_input_tokens`` / ``max_output_tokens`` bound the HTTP runner only: a
# local CLI decides its own output budget, which the platform can observe but
# not limit.
INTEGER_KEYS = ("max_input_tokens", "max_output_tokens")
INTEGER_LIMITS = {"max_input_tokens": 10_000_000, "max_output_tokens": 1_000_000}
DEFAULTS = {"provider": "codex", "model": "", "executable": "", "reasoning_effort": "",
            "timeout_seconds": 1500, "base_url": "", "max_input_tokens": 60000,
            "max_output_tokens": 16000}


class AIConfigError(ValueError):
    pass


def _positive_int(name: str, value: object) -> int:
    """Accept an integer or a decimal string; reject booleans and floats."""

    if isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise AIConfigError(f"{name} 必须为正整数")
        parsed = int(text)
    elif type(value) is int:
        parsed = value
    else:
        raise AIConfigError(f"{name} 必须为正整数")
    if not 1 <= parsed <= INTEGER_LIMITS[name]:
        raise AIConfigError(f"{name} 必须在 1..{INTEGER_LIMITS[name]} 之间")
    return parsed


def _with_runner_alias(raw):
    """``runner`` is the new spelling of ``provider``; both may not disagree."""

    values = dict(raw)
    alias = values.pop("runner", None)
    if alias is None:
        return values
    provider = values.get("provider")
    if provider is not None and provider != alias:
        raise AIConfigError("provider 与 runner 不能同时给出不同的值")
    values["provider"] = alias
    return values


def resolve_ai_config(config_file=None, **overrides):
    env = {**read_dotenv_values(), **os.environ}
    selected = config_file or env.get("HYDROLITAGENT_CARDS_AI_CONFIG")
    path = Path(selected).expanduser().resolve() if selected else DEFAULT_FILE
    values = dict(DEFAULTS)
    if selected or path.exists():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise AIConfigError(f"无法读取 AI 选择配置：{path}（{type(exc).__name__}）") from exc
        if set(raw) != {"ai"} or not isinstance(raw["ai"], dict):
            raise AIConfigError("AI 配置只接受公开的 [ai] 字段，凭据请交给本机 CLI")
        ai = _with_runner_alias(raw["ai"])
        if ai.keys() - DEFAULTS.keys():
            raise AIConfigError("AI 配置只接受公开的 [ai] 字段，凭据请交给本机 CLI")
        values.update(ai)
    for key in DEFAULTS:
        name = "HYDROLITAGENT_CARDS_AI_" + key.upper()
        if name in env:
            values[key] = env[name]
    for key, value in _with_runner_alias(overrides).items():
        if key not in DEFAULTS:
            raise AIConfigError(f"未知 AI 配置：{key}")
        if value is not None:
            values[key] = value
    provider = values["provider"]
    # The registry owns the list of buildable runners; this module must not keep
    # a second, easily-stale allowlist.
    available = runner_ids()
    if provider not in available:
        planned = planned_runner_ids()
        message = "provider 仅支持：" + "、".join(available)
        if planned:
            message += "；计划中：" + "、".join(planned)
        raise AIConfigError(message)
    for key in DEFAULTS.keys() - {"timeout_seconds", *INTEGER_KEYS}:
        if not isinstance(values[key], str) or "\n" in values[key] or "\x00" in values[key]:
            raise AIConfigError(f"{key} 必须为单行字符串")
    for key in INTEGER_KEYS:
        values[key] = _positive_int(key, values[key])
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
    return values


def apply_ai_selection(app_config, selection):
    """Overlay an AI selection onto an already loaded application config.

    ``themes-run`` needs the provider choice *and* the rest of the loaded
    configuration (paths, Zotero group, converter, pipeline limits). Rebuilding
    the config from the selection would silently drop those, so only the
    provider-facing fields change and everything else is carried over.

    The executable is kept exactly as ``resolve_ai_config`` returned it: that
    function owns the "bare command name or explicit path" contract, and the
    runners add whatever platform wrapping is needed to launch it.
    """

    cfg = app_config.card_generator
    updated = replace(
        cfg,
        adapter=selection["provider"] + "_cli",
        executable=selection["executable"],
        model=selection["model"] or None,
        reasoning_effort=selection["reasoning_effort"] or None,
        generation_timeout_seconds=selection["timeout_seconds"],
    )
    return replace(
        app_config,
        card_generator=updated,
        # Same provider-neutral bag ``subject_card_config`` hands to
        # ``composition``; only the HTTP runner reads it.
        runner_options={
            "base_url": selection.get("base_url") or None,
            "max_input_tokens": selection.get("max_input_tokens"),
            "max_output_tokens": selection.get("max_output_tokens"),
        },
    )


def subject_card_config(selection, *, base_config=None):
    """Reuse existing dataclasses/adapters; single-paper work does not need Zotero/scheduler config."""
    if base_config is not None:
        cfg = base_config.card_generator
    else:
        cfg = CardGeneratorConfig("codex_cli", "codex", "chatgpt_account", 10, None, None, 120, 1500,
                  workflow_mode="single_agent", runtime_dir=REPO_ROOT / ".runtime",
                  connection_guard=ConnectionGuardConfig(reconnect_stop_enabled=False, idle_timeout_seconds=1500))
    cfg = replace(cfg, adapter=selection["provider"] + "_cli", executable=selection["executable"],
          model=selection["model"] or None, reasoning_effort=selection["reasoning_effort"] or None,
          generation_timeout_seconds=selection["timeout_seconds"], workflow_mode="single_agent", multi_agent_workflow=None)
    paths = base_config.paths if base_config is not None else SimpleNamespace(
          evidence_card_generation_prompt_file=PROMPTS_DIR / "evidence-card-generation-v8.md",
          evidence_card_templates_dir=TEMPLATES_DIR / "evidence-cards",
          evidence_card_template_catalog_file=TEMPLATES_DIR / "evidence-cards/_catalog.json")
    # ``runner_options`` is the provider-neutral bag ``composition`` hands to the
    # selected runner factory. It carries no credential: the API key is read from
    # the environment by the runner itself.
    runner_options = {
        "base_url": selection.get("base_url") or None,
        "max_input_tokens": selection.get("max_input_tokens"),
        "max_output_tokens": selection.get("max_output_tokens"),
    }
    return SimpleNamespace(card_generator=cfg, paths=paths, runner_options=runner_options)


def describe_ai(selection, *, output_root=None):
    # ``pipeline`` is data, not a provider choice: it tells the operator which
    # single-paper path the next ``evidence-generate`` run will take.
    ai = {
        **selection,
        # ``provider`` keeps its historical name and values; ``runner`` is the
        # alias new consumers should read.
        "runner": selection.get("provider"),
        # Every id ``--ai-provider`` accepts right now, straight from the registry.
        "runners": list(runner_ids()),
        # Budgets the HTTP runner enforces. Local CLIs decide their own output
        # budget, so these values bound only the API runner.
        "runner_limits": {
            "max_input_tokens": selection.get("max_input_tokens"),
            "max_output_tokens": selection.get("max_output_tokens"),
        },
        "pipeline": resolve_pipeline_mode(),
    }
    return {"ok": True, "operation": "ai_config", "ai": ai,
            "literature_root": str(resolve_literature_root(root=output_root)),
            "credentials": "由所选 CLI 使用本机登录或环境变量；本配置不保存凭据"}
