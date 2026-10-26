"""The Codex CLI runner adapter: wiring plus its record builders.

Stage 1.6 split the former 993-line ``card_generators/codex_cli.py`` by
responsibility. ``CodexCliAdapter`` stays the single object that owns the
configured subprocess runners, so subclasses (``CodexTextAdapter``,
``CodexLocalPdfAdapter``) keep working unchanged.
"""
from __future__ import annotations

import shutil
from typing import Any

from hydrolitagent.cards.adapters.runners.codex.common import _now
from hydrolitagent.cards.adapters.runners.codex.preflight import run_preflight
from hydrolitagent.cards.adapters.runners.codex.process import (
    CommandRunner,
    ExecutableFinder,
    PromptRunner,
    _run_command,
    _run_prompt_command,
)
from hydrolitagent.cards.adapters.runners.codex.smoke import (
    build_smoke_failure,
    run_smoke_test,
)
from hydrolitagent.cards.adapters.runners.codex.proxy import (
    codex_proxy_environment,
    proxy_summary,
)
from hydrolitagent.cards.card_generators.streaming import run_streaming_prompt
from hydrolitagent.cards.config import CardGeneratorConfig
from hydrolitagent.cards.domain.protocol import GENERATION_PROTOCOL_VERSION
from hydrolitagent.cards.progress import ProgressCallback


class CodexCliAdapter:
    """Codex CLI runtime checks and a bounded, non-domain smoke probe."""

    def __init__(
        self,
        config: CardGeneratorConfig,
        *,
        executable_finder: ExecutableFinder = shutil.which,
        runner: CommandRunner = _run_command,
        prompt_runner: PromptRunner = _run_prompt_command,
        progress: ProgressCallback | None = None,
    ):
        self.config = config
        self._executable_finder = executable_finder
        self._runner = runner
        if runner is _run_command:
            # Includes version/login-status and smoke calls; no global env assignment.
            self._runner = lambda command, timeout: runner(
                command, timeout, codex_proxy_environment(self.config.proxy),
            )
        delegate_prompt_runner = prompt_runner
        if prompt_runner is _run_prompt_command:
            delegate_prompt_runner = lambda command, prompt, timeout, environment: run_streaming_prompt(
                command, prompt, timeout, environment,
                progress=progress,
                connection_guard=config.connection_guard,
            )
        self._prompt_runner = lambda command, prompt, timeout, environment: delegate_prompt_runner(
            command, prompt, timeout, codex_proxy_environment(self.config.proxy, environment),
        )

    def _failure(
        self,
        checks: list[dict[str, str]],
        code: str,
        message: str,
        *,
        resolved_executable: str | None,
        cli_version: str | None = None,
        detected_auth_mode: str | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": False,
            "component": "card_generator",
            "checked_at": _now(),
            "adapter": self.config.adapter,
            "configured_executable": self.config.executable,
            "proxy": proxy_summary(self.config.proxy),
            "resolved_executable": resolved_executable,
            "configured_auth_mode": self.config.auth_mode,
            "detected_auth_mode": detected_auth_mode,
            "cli_version": cli_version,
            "checks": checks,
            "error": {"code": code, "message": message},
        }

    def preflight(self) -> dict[str, Any]:
        return run_preflight(self)

    def _smoke_failure(
        self,
        preflight_result: dict[str, Any],
        checks: list[dict[str, str]],
        code: str,
        message: str,
        *,
        model_invoked: bool,
        unexpected_item_types: list[str] | None = None,
    ) -> dict[str, Any]:
        return build_smoke_failure(
            self,
            preflight_result,
            checks,
            code,
            message,
            model_invoked=model_invoked,
            unexpected_item_types=unexpected_item_types,
        )

    def smoke_test(self) -> dict[str, Any]:
        return run_smoke_test(self)

    def _generation_failure(
        self,
        preflight_result: dict[str, Any],
        code: str,
        message: str,
        *,
        model_invoked: bool,
        unexpected_item_types: list[str] | None = None,
        diagnostic: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = {
            "schema_version": 1,
            "ok": False,
            "component": "card_generator",
            "operation": "evidence_card_generation",
            "checked_at": _now(),
            "adapter": self.config.adapter,
            "resolved_executable": preflight_result.get("resolved_executable"),
            "cli_version": preflight_result.get("cli_version"),
            "configured_auth_mode": self.config.auth_mode,
            "detected_auth_mode": preflight_result.get("detected_auth_mode"),
            "configured_model": self.config.model,
            "model_source": "configured" if self.config.model else "codex_default",
            "configured_reasoning_effort": self.config.reasoning_effort,
            "reasoning_effort_source": (
                "configured" if self.config.reasoning_effort else "model_default"
            ),
            "generation_protocol_version": GENERATION_PROTOCOL_VERSION,
            "sandbox": "read-only",
            "ephemeral": True,
            "model_invoked": model_invoked,
            "unexpected_item_types": unexpected_item_types or [],
            "error": {"code": code, "message": message},
        }
        if diagnostic is not None:
            result["diagnostic"] = diagnostic
        return result


__all__ = ["CodexCliAdapter"]
