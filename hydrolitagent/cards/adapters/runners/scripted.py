"""Deterministic runner used by tests and by the workflow self-checks.

It implements the same ``ports.runner.CardRunner`` contract as the real
runners, so a workflow can be exercised end to end without a model, a network
call or an agent: the preset answer is returned as-is and the request that would
have gone to a provider is recorded.

The same ``CardRunRequest`` shape applies -- a ``PreparedPaper`` or ``None`` for
a text-only task -- so a test that passes here exercises the same contract the
``in_session`` and ``direct`` runners receive.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from hydrolitagent.cards.ports.runner import (
    CardRunError,
    CardRunRequest,
    CardRunResult,
    RunnerDoctor,
)


class ScriptedRunner:
    """Deterministic runner for tests: replays one preset answer."""

    runner_id = "scripted"

    def __init__(
        self,
        output: Mapping[str, Any] | None = None,
        *,
        ok: bool = True,
        error: CardRunError | None = None,
        model_invoked: bool = True,
    ) -> None:
        self.output = deepcopy(dict(output)) if output is not None else None
        self.ok = ok
        self.error = error
        self.model_invoked = model_invoked
        self.requests: list[CardRunRequest] = []

    def doctor(self) -> RunnerDoctor:
        return RunnerDoctor(
            runner_id=self.runner_id, available=True, detail="测试替身，不需要外部程序"
        )

    def run(self, request: CardRunRequest) -> CardRunResult:
        self.requests.append(request)
        if not self.ok:
            return CardRunResult(
                runner_id=self.runner_id,
                ok=False,
                error=self.error
                or CardRunError("SCRIPTED_RUNNER_FAILED", "测试替身被要求返回失败"),
                model_invoked=self.model_invoked,
            )
        if self.output is None:
            return CardRunResult(
                runner_id=self.runner_id,
                ok=False,
                error=CardRunError(
                    "SCRIPTED_RUNNER_OUTPUT_MISSING", "测试替身没有预置输出"
                ),
                model_invoked=self.model_invoked,
            )
        return CardRunResult(
            runner_id=self.runner_id,
            ok=True,
            output=deepcopy(self.output),
            model_invoked=True,
        )


__all__ = ["ScriptedRunner"]
