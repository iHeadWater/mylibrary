"""Behaviour of the runner registry.

These tests cover the three promises the registry makes:

* ``ids()`` lists exactly what ``create`` can build, and an unknown id fails with
  that list instead of silently picking a different provider;
* adding a runner needs one adapter plus one registration -- no shared-layer
  edit, no CLI parser edit, no allowlist edit;
* importing the registry does not import any provider module, so ``cards --help``
  and ``cards ai-config`` stay cheap and provider-free.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from hydrolitagent.cards import ai_config
from hydrolitagent.cards.adapters.runners import registry
from hydrolitagent.cards.ports.runner import CardRunRequest, CardRunResult, RunnerDoctor

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_ids_list_only_the_buildable_runners() -> None:
    assert registry.ids() == ("claude", "codex", "in_session", "openai_compatible")


def test_unknown_id_reports_the_available_runners() -> None:
    with pytest.raises(registry.RegistryError) as caught:
        registry.create("mystery_provider")

    message = str(caught.value)
    assert "mystery_provider" in message
    for runner_id in registry.ids():
        assert runner_id in message, f"{runner_id} 未出现在错误信息里：{message}"


def test_in_session_runner_is_buildable_without_configuration() -> None:
    """Stage 4b: the file-based runner is real, not a planned placeholder."""

    assert registry.planned_ids() == ()
    runner = registry.create("in_session")
    assert runner.runner_id == "in_session"
    assert runner.doctor().available is True


def test_legacy_adapter_suffix_resolves_to_the_same_runner() -> None:
    """``claude_cli`` is the on-disk adapter spelling; it is not a second runner."""

    runner = registry.create("claude_cli", executable="claude-placeholder")
    assert runner.runner_id == "claude_markdown"


def test_builtin_factories_build_the_documented_runners() -> None:
    assert registry.create("claude", executable="claude-placeholder").runner_id == (
        "claude_markdown"
    )
    assert registry.create("codex", executable="codex-placeholder").runner_id == (
        "codex_markdown"
    )
    api = registry.create(
        "openai_compatible",
        base_url="https://api.example.test/v1",
        api_key="sk-placeholder-123456",
        model="example-model",
        max_input_tokens=1234,
        max_output_tokens=234,
    )
    assert api.runner_id == "openai_compatible"
    assert api.max_input_tokens == 1234
    assert api.max_output_tokens == 234


class _DummyRunner:
    """Minimal port implementation used only to prove the extension point."""

    runner_id = "dummy"

    def doctor(self) -> RunnerDoctor:
        return RunnerDoctor(self.runner_id, True, "dummy")

    def run(self, request: CardRunRequest) -> CardRunResult:  # pragma: no cover
        return CardRunResult(self.runner_id, True, output={})


def test_a_new_runner_needs_one_registration_and_no_shared_layer_change() -> None:
    def factory(**options: object) -> _DummyRunner:
        assert options["executable"] == "anything"  # composition passes one bag
        return _DummyRunner()

    registry.register("dummy", factory)
    try:
        assert "dummy" in registry.ids()
        assert isinstance(registry.create("dummy", executable="anything"), _DummyRunner)
        with pytest.raises(registry.RegistryError, match="已注册"):
            registry.register("dummy", factory)
    finally:
        registry.unregister("dummy")
    assert "dummy" not in registry.ids()


def test_registering_a_planned_id_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # The planned table is empty now; inject one so this guard stays exercised
    # instead of passing vacuously.
    monkeypatch.setitem(registry._PLANNED, "future_runner", "未来阶段")
    with pytest.raises(registry.RegistryError, match="计划中的运行器"):
        registry.register("future_runner", lambda **_: _DummyRunner())
    assert "future_runner" not in registry.ids()


def test_registry_import_pulls_no_provider_module() -> None:
    """A provider imported at module level would slow down every CLI start."""

    code = (
        "import sys\n"
        "import hydrolitagent.cards.adapters.runners.registry\n"
        "names = [m for m in sys.modules "
        "if m.startswith('hydrolitagent.cards.adapters.runners')]\n"
        "print('\\n'.join(sorted(names)))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    imported = set(completed.stdout.split())
    assert "hydrolitagent.cards.adapters.runners.registry" in imported
    provider_specific = {
        name
        for name in imported
        if any(word in name for word in ("markdown", "openai_compatible", "codex"))
    }
    assert not provider_specific, (
        "import registry 时拉起了 provider 模块：" + ", ".join(sorted(provider_specific))
    )


# --------------------------------------------------------------------------------------
# The AI selection layer reads its allowlist from the registry
# --------------------------------------------------------------------------------------


def test_ai_selection_accepts_every_registered_runner() -> None:
    for runner_id in registry.ids():
        selection = ai_config.resolve_ai_config(provider=runner_id)
        assert selection["provider"] == runner_id


def test_runner_is_an_alias_for_provider(tmp_path: Path) -> None:
    path = tmp_path / "ai.toml"
    path.write_text(
        '[ai]\nrunner = "openai_compatible"\nmodel = "example-model"\n', encoding="utf-8"
    )
    selection = ai_config.resolve_ai_config(path)
    assert selection["provider"] == "openai_compatible"
    # The alias is decoded, not echoed as a second field.
    assert "runner" not in selection

    assert ai_config.resolve_ai_config(path, runner="claude")["provider"] == "claude"

    conflicting = tmp_path / "conflicting.toml"
    conflicting.write_text(
        '[ai]\nprovider = "codex"\nrunner = "claude"\n', encoding="utf-8"
    )
    with pytest.raises(ai_config.AIConfigError):
        ai_config.resolve_ai_config(conflicting)


def test_ai_selection_rejects_an_unknown_runner_with_the_registry_list() -> None:
    with pytest.raises(ai_config.AIConfigError) as caught:
        ai_config.resolve_ai_config(provider="unknown")
    message = str(caught.value)
    for runner_id in registry.ids():
        assert runner_id in message


def test_cli_parser_accepts_a_registry_id() -> None:
    """The old ``choices=['codex', 'claude']`` was a second, stale allowlist."""

    from hydrolitagent.cards import cli

    parsed = cli._parser().parse_args(["ai-config", "--ai-provider", "openai_compatible"])
    assert parsed.ai_provider == "openai_compatible"


def test_ai_config_reports_runners_and_limits_without_credentials() -> None:
    selection = ai_config.resolve_ai_config(
        provider="openai_compatible", model="example-model"
    )
    described = ai_config.describe_ai(selection)
    ai = described["ai"]

    assert ai["provider"] == "openai_compatible"
    assert ai["runner"] == "openai_compatible"
    assert ai["runners"] == list(registry.ids())
    assert ai["runner_limits"] == {
        "max_input_tokens": 60000,
        "max_output_tokens": 16000,
    }
    # None of the new fields may become a credential echo.
    assert "api_key" not in ai
    assert "OPENAI_API_KEY" not in str(ai)


def test_subject_card_config_exposes_runner_options() -> None:
    selection = ai_config.resolve_ai_config(
        provider="openai_compatible",
        base_url="https://api.example.test/v1",
        max_input_tokens="1200",
        max_output_tokens=300,
    )
    app = ai_config.subject_card_config(selection)

    assert app.card_generator.adapter == "openai_compatible_cli"
    assert app.runner_options == {
        "base_url": "https://api.example.test/v1",
        "max_input_tokens": 1200,
        "max_output_tokens": 300,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"max_input_tokens": 0},
        {"max_input_tokens": True},
        {"max_output_tokens": "many"},
        {"max_output_tokens": 1_000_001},
    ],
)
def test_token_budgets_are_validated(change: dict) -> None:
    with pytest.raises(ai_config.AIConfigError):
        ai_config.resolve_ai_config(**change)


if __name__ == "__main__":  # pragma: no cover - manual invocation convenience
    raise SystemExit(pytest.main([__file__]))
