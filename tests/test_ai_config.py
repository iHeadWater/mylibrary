import json
from pathlib import Path
import pytest
from hydrolitagent.cards import ai_config as config, cli


def test_file_dotenv_environment_and_argument_priority(tmp_path, monkeypatch):
    path = tmp_path / "ai.toml"
    path.write_text('[ai]\nprovider="claude"\nmodel="file-model"\n',encoding="utf-8")
    monkeypatch.setattr(config, "read_dotenv_values", lambda: {"HYDROLITAGENT_CARDS_AI_MODEL":"dotenv-model"})
    assert config.resolve_ai_config(path)["model"] == "dotenv-model"
    monkeypatch.setenv("HYDROLITAGENT_CARDS_AI_MODEL", "env-model")
    assert config.resolve_ai_config(path)["model"] == "env-model"
    assert config.resolve_ai_config(path, model="cli-model")["model"] == "cli-model"


@pytest.mark.parametrize("change", [{"provider":"unknown"}, {"timeout_seconds":0}, {"timeout_seconds":float("nan")},
    {"timeout_seconds":True}, {"model":42}, {"provider":"claude","reasoning_effort":"minimal"}])
def test_invalid_configuration_rejected(change):
    with pytest.raises(config.AIConfigError): config.resolve_ai_config(**change)


def test_selection_never_requires_private_platform_config(monkeypatch, capsys):
    monkeypatch.setenv("HYDROLITAGENT_CARDS_CONFIG", "missing.json")
    monkeypatch.setattr(cli, "load_config", lambda *a,**k: (_ for _ in ()).throw(AssertionError("no machine config")))
    assert cli.main(["ai-config","--ai-provider","claude","--json"]) == 0
    result=json.loads(capsys.readouterr().out)
    assert result["ai"]["provider"] == "claude"
    assert "api_key" not in result["ai"]


def test_both_selections_use_existing_single_agent_contract():
    for provider in ("codex","claude"):
        app=config.subject_card_config(config.resolve_ai_config(provider=provider))
        assert app.card_generator.workflow_mode == "single_agent"
        assert app.card_generator.adapter == provider + "_cli"
        assert app.paths.evidence_card_generation_prompt_file.is_file()
