"""``themes-run`` must honour the same AI selection as the single-paper path.

The bug this pins down: a theme run built its runner from ``config.json`` only,
so ``--ai-provider`` / ``configs/ai.toml`` / ``HYDROLITAGENT_CARDS_AI_*`` were
ignored and the run always tried the adapter baked into the asset config.
"""
from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from hydrolitagent.cards import ai_config, cli
from hydrolitagent.cards.config import load_config
from test_config import write_config

AI_ENV = ("HYDROLITAGENT_CARDS_AI_CONFIG",) + tuple(
    "HYDROLITAGENT_CARDS_AI_" + key.upper() for key in ai_config.DEFAULTS
)


@pytest.fixture(autouse=True)
def _clean_ai_environment(monkeypatch):
    """A developer's own AI env vars must not decide what this test observes."""

    for name in AI_ENV:
        monkeypatch.delenv(name, raising=False)


def _run_themes_cli(monkeypatch, config_path, extra_argv):
    """Invoke ``themes-run`` with the pipeline and the run itself intercepted."""

    captured: dict[str, object] = {}

    def fake_build(app_config):
        captured["config"] = app_config
        return object()  # opaque handle, never used because run_themes is fake

    def fake_run(app_config, *, progress=None, pipeline=None, **kwargs):
        captured["pipeline"] = pipeline
        captured["dry_run"] = kwargs.get("dry_run", False)
        return {
            "schema_version": 1,
            "ok": True,
            "operation": "themes_run",
            "status": "STARTED",
        }

    monkeypatch.setattr(cli, "build_theme_pipeline", fake_build)
    monkeypatch.setattr(cli, "run_themes", fake_run)
    output = io.StringIO()
    with redirect_stdout(output):
        code = cli.main(
            [
                "themes-run",
                "--config",
                str(config_path),
                "--json",
                "--no-progress",
                *extra_argv,
            ]
        )
    return code, captured


def test_themes_run_applies_the_cli_ai_provider(tmp_path, monkeypatch):
    config_path = write_config(tmp_path)
    ai_file = tmp_path / "ai.toml"
    ai_file.write_text(
        '[ai]\nprovider = "in_session"\n', encoding="utf-8"
    )
    code, captured = _run_themes_cli(
        monkeypatch,
        config_path,
        [
            "--ai-config",
            str(ai_file),
            "--ai-provider",
            "direct",
            "--ai-model",
            "deepseek-chat",
            "--ai-timeout",
            "90",
        ],
    )

    assert code == 0
    pipeline_config = captured["config"]
    assert captured["dry_run"] is False
    assert pipeline_config.card_generator.runner == "direct"
    assert pipeline_config.card_generator.model == "deepseek-chat"
    assert pipeline_config.card_generator.generation_timeout_seconds == 90
    assert pipeline_config.card_generator.reasoning_effort is None


def test_themes_run_keeps_the_loaded_configuration(tmp_path, monkeypatch):
    config_path = write_config(tmp_path)
    loaded = load_config(config_path)

    code, captured = _run_themes_cli(
        monkeypatch,
        config_path,
        ["--ai-provider", "direct"],
    )

    assert code == 0
    pipeline_config = captured["config"]
    # Only the provider-facing fields change; the theme run still reads the
    # same literature root and writes the same artifacts.
    assert pipeline_config.paths == loaded.paths
    assert pipeline_config.zotero == loaded.zotero
    assert pipeline_config.pdf_gate == loaded.pdf_gate
    assert pipeline_config.tasks == loaded.tasks
    assert pipeline_config.converter == loaded.converter
    assert pipeline_config.pipeline == loaded.pipeline
    assert pipeline_config.theme_pipeline == loaded.theme_pipeline
    assert pipeline_config.source_file == loaded.source_file


def test_themes_run_without_a_provider_reads_the_ai_config_file(tmp_path, monkeypatch):
    config_path = write_config(tmp_path)
    ai_file = tmp_path / "ai.toml"
    ai_file.write_text(
        '[ai]\nprovider = "direct"\nmodel = "from-toml"\n', encoding="utf-8"
    )

    code, captured = _run_themes_cli(
        monkeypatch, config_path, ["--ai-config", str(ai_file)]
    )

    assert code == 0
    card_generator = captured["config"].card_generator
    # The AI selection file decides the runner, whatever config.json says.
    assert card_generator.runner == "direct"
    assert card_generator.model == "from-toml"


def test_themes_run_reads_the_ai_config_from_the_environment(tmp_path, monkeypatch):
    config_path = write_config(tmp_path)
    ai_file = tmp_path / "ai.toml"
    ai_file.write_text(
        '[ai]\nprovider = "in_session"\n', encoding="utf-8"
    )
    monkeypatch.setenv("HYDROLITAGENT_CARDS_AI_CONFIG", str(ai_file))

    code, captured = _run_themes_cli(monkeypatch, config_path, [])

    assert code == 0
    assert captured["config"].card_generator.runner == "in_session"


@pytest.mark.parametrize("flag", ["--dry-run", "--migrate-only"])
def test_non_model_runs_do_not_resolve_a_provider(tmp_path, monkeypatch, flag):
    config_path = write_config(tmp_path)
    captured: dict[str, object] = {}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("非模型运行不得解析或构建模型运行器")

    def fake_run(app_config, *, dry_run=False, migration_only=False, **kwargs):
        captured.update(dry_run=dry_run, migration_only=migration_only)
        return {"schema_version": 1, "ok": True, "operation": "themes_run",
                "status": "LOCAL_PREVIEW", "dry_run": dry_run}

    monkeypatch.setattr(cli, "resolve_ai_config", forbidden)
    monkeypatch.setattr(cli, "build_theme_pipeline", forbidden)
    monkeypatch.setattr(cli, "run_themes", fake_run)
    output = io.StringIO()
    with redirect_stdout(output):
        code = cli.main(
            ["themes-run", "--config", str(config_path), "--json", flag]
        )

    assert code == 0
    assert captured["dry_run"] is (flag == "--dry-run")
    assert captured["migration_only"] is (flag == "--migrate-only")


def test_apply_ai_selection_is_the_only_mutation(tmp_path):
    loaded = load_config(write_config(tmp_path))
    selection = ai_config.resolve_ai_config(
        provider="direct",
        model="deepseek-chat",
        timeout_seconds=42,
    )

    updated = ai_config.apply_ai_selection(loaded, selection)

    assert updated is not loaded
    assert loaded.card_generator.runner == "in_session"  # input untouched
    assert updated.card_generator.runner == "direct"
    assert updated.card_generator.model == "deepseek-chat"
    assert updated.card_generator.generation_timeout_seconds == 42
    assert updated.card_generator.reasoning_effort is None
    assert updated.paths is loaded.paths
    assert updated.zotero is loaded.zotero
    assert updated.runner_options == {
        "base_url": "https://api.deepseek.com",
        "max_input_tokens": 60000,
        "max_output_tokens": 16000,
    }
