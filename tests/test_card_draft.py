"""#30 contracts, using a real fixed PDF and the existing simulated Codex provider."""
from __future__ import annotations

import hashlib
import io
import json
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfWriter

from hydrolitagent.cards._paths import ASSETS_DIR, PACKAGE_DIR
from hydrolitagent import _config as literature_config
from hydrolitagent.cards import card_draft, cli
from hydrolitagent.cards.card_generators.single_agent import SingleAgentCardGeneratorAdapter
from hydrolitagent.cards.config import load_config
from test_card_generation import FakeAdapter, PARENT_KEY
from test_codex_local_pdf import LocalProviderFixture
from test_config import write_config

AUTOMATION = ASSETS_DIR
PLATFORM = ASSETS_DIR

@pytest.fixture
def draft_case(tmp_path, monkeypatch):
    provider = LocalProviderFixture(tmp_path / "provider")
    writer = PdfWriter()
    for _ in range(12):
        writer.add_blank_page(width=300, height=300)
    writer.write(provider.pdf)
    app = load_config(write_config(tmp_path / "app", {"zotero": {"group_id": None}}))
    app = replace(app, card_generator=replace(provider.config, workflow_mode="single_agent", multi_agent_workflow=None),
                  paths=replace(app.paths,
                      evidence_card_templates_dir=PLATFORM / "templates/evidence-cards",
                      evidence_card_template_catalog_file=PLATFORM / "templates/evidence-cards/_catalog.json",
                      evidence_card_generation_prompt_file=AUTOMATION / "prompts/evidence-card-generation-v8.md"))
    record = {
        "schema_version": 1, "ok": True, "operation": "paper_input", "status": "READY",
        "reason_code": "PDF_READY", "library": {"type": "user", "id": 0},
        "requested_item_key": "ATTACH01",
        "item": {"item_key": PARENT_KEY, "title": "Fixed test paper"},
        "pdf_attachment_count": 1,
        "pdf": {"attachment_key": "ATTACH01", "parent_key": PARENT_KEY,
                "file_size_bytes": provider.pdf.stat().st_size,
                "sha256": hashlib.sha256(provider.pdf.read_bytes()).hexdigest(),
                "local_path": str(provider.pdf.resolve()), "fulltext_indexed": False},
    }
    statement = {
        "statement": "Synthetic fixture result; not a scientific claim.",
        "statement_role": "original_statement", "information_status": "reported",
        "source_locations": [{"pdf_page": 2, "section": "Results", "figure": None, "table": None}],
    }
    fields = {"schema_version": 1}
    for key in ("research_questions", "study_objects_and_scales", "data_and_methods",
                "comparison_baselines", "findings", "boundaries", "missing_information"):
        fields[key] = [deepcopy(statement)]
    fields["findings"][0]["finding_id"] = "F001"
    output = {**FakeAdapter().output, "card_body_markdown": "# Fixed paper\n\nF001: fixture result.\n",
              "machine_fields": fields}
    provider.outputs = [deepcopy(output)]
    monkeypatch.setenv("HYDROLITAGENT_LITERATURE_ROOT", str(tmp_path / "cloud"))
    adapter = SingleAgentCardGeneratorAdapter(provider.adapter)
    return app, record, provider, adapter, output

def run(case):
    app, record, _, adapter, _ = case
    return card_draft.generate_subject_card_draft(app, record, adapter=adapter)

def test_one_call_returns_traceable_unvalidated_pair_in_shared_root(draft_case, tmp_path):
    app, record, provider, _, _ = draft_case
    original = deepcopy(record)
    result = run(draft_case)
    assert result["ok"], result
    assert len(provider.calls) == 1
    assert result["model_invoked"]
    assert result["status"] == "DRAFT_PENDING_VALIDATION"
    assert not result["production_eligible"]
    assert not result["content_validation_performed"]
    assert Path(result["literature_root"]) == tmp_path / "cloud"
    assert Path(result["draft_path"]).relative_to(tmp_path / "cloud").parts[:3] == (
        "zotero", f"user-0-{PARENT_KEY}", "drafts")
    draft = json.loads(Path(result["draft_path"]).read_text(encoding="utf-8"))
    assert draft["source"]["library"] == {"type": "user", "id": 0}
    assert draft["source"]["parent_key"] == PARENT_KEY
    assert draft["source"]["requested_item_key"] == "ATTACH01"
    assert draft["source"]["pdf_sha256"] == record["pdf"]["sha256"]
    assert draft["machine_fields"]["findings"][0]["finding_id"] == "F001"
    assert draft["provenance"]["prompt_version"] == "evidence-card-generation-v8"
    assert draft["provenance"]["draft_prompt_version"] == "subject-card-draft-v1"
    assert draft["provenance"]["template_version"]
    assert len(draft["provenance"]["template_sha256"]) == 64
    assert not draft["reading_record"]["full_read_verified"]
    assert Path(result["card_path"]).read_text(encoding="utf-8").endswith(draft["card_body_markdown"])
    assert record == original
    assert not app.paths.tasks_file.exists()
    assert not app.paths.evidence_packs_dir.exists()
    assert not app.paths.themes_dir.exists()
    prompt = provider.calls[0][1]
    assert "platform-decision-synthesis" not in prompt
    assert "research_questions" in prompt
    assert "待校验" in prompt or "DRAFT_PENDING_VALIDATION" in prompt

@pytest.mark.parametrize("change", [
    {"status": "WAITING"}, {"status": "SELECTION_REQUIRED"}, {"ok": False},
    {"requested_item_key": "OTHER123"}, {"schema_version": True}, {"operation": "paper_input_batch"}, {"pdf_attachment_count": 2},
    {"library": {"type": "group", "id": 0}}, {"library": {"type": "user", "id": True}},
])
def test_not_ready_or_ambiguous_input_never_calls_model(draft_case, change):
    draft_case[1].update(change)
    result = run(draft_case)
    assert not result["ok"]
    assert result["error"]["code"] == "CARD_DRAFT_INPUT_INVALID"
    assert not draft_case[2].calls
    assert "draft_path" not in result

@pytest.mark.parametrize("field,value,code", [
    ("parent_key", "OTHER123", "CARD_DRAFT_INPUT_INVALID"),
    ("attachment_key", "../wrong", "CARD_DRAFT_INPUT_INVALID"),
    ("local_path", "relative.pdf", "CARD_DRAFT_INPUT_INVALID"),
    ("sha256", "0" * 64, "PDF_INPUT_CHANGED"),
    ("file_size_bytes", 1, "PDF_INPUT_CHANGED"),
])
def test_input_identity_and_hash_are_bound_before_generation(draft_case, field, value, code):
    draft_case[1]["pdf"][field] = value
    result = run(draft_case)
    assert result["error"]["code"] == code
    assert not draft_case[2].calls

def test_missing_pdf_does_not_create_pseudodraft(draft_case, tmp_path):
    draft_case[2].pdf.unlink()
    result = run(draft_case)
    assert result["error"]["code"] == "CARD_DRAFT_PDF_UNREADABLE"
    assert not draft_case[2].calls
    assert not (tmp_path / "cloud").exists()

def test_changed_pdf_during_generation_is_rejected_without_retry(draft_case):
    _, _, provider, _, _ = draft_case
    original = provider.model
    def change(command, prompt, timeout, environment):
        response = original(command, prompt, timeout, environment)
        provider.pdf.write_bytes(provider.pdf.read_bytes() + b"\nchanged")
        return response
    provider.runner.side_effect = change
    result = run(draft_case)
    assert result["error"]["code"] == "PDF_INPUT_CHANGED"
    assert len(provider.calls) == 1
    assert "draft_path" not in result

@pytest.mark.parametrize("bad_fields", [
    None, [], {}, {"schema_version": 1}, "not JSON",
])
def test_machine_fields_must_be_parseable_before_draft_is_saved(draft_case, bad_fields, tmp_path):
    draft_case[2].outputs[0]["machine_fields"] = bad_fields
    result = run(draft_case)
    assert result["error"]["code"] == "CARD_DRAFT_OUTPUT_INVALID"
    assert len(draft_case[2].calls) == 1
    assert not (tmp_path / "cloud").exists()

def test_wire_rejects_wrong_field_type(draft_case):
    draft_case[2].outputs[0]["machine_fields"]["findings"][0]["source_locations"][0]["pdf_page"] = True
    result = run(draft_case)
    assert result["error"]["code"] == "CARD_DRAFT_OUTPUT_INVALID"
    assert len(draft_case[2].calls) == 1

def test_no_content_gate_or_claim_of_semantic_verification(draft_case):
    # Empty fields / dangling finding ids need #31, not another AI call here.
    fields = draft_case[2].outputs[0]["machine_fields"]
    fields["research_questions"] = []
    fields["findings"][0]["finding_id"] = ""
    fields["findings"][0]["source_locations"][0]["pdf_page"] = 10 ** 400
    result = run(draft_case)
    assert result["ok"], result
    draft = json.loads(Path(result["draft_path"]).read_text(encoding="utf-8"))
    assert draft["status"] == "DRAFT_PENDING_VALIDATION"
    assert not draft["scientific_correctness_verified"]
    assert len(draft_case[2].calls) == 1

def test_synthesis_template_is_not_a_single_source_card(draft_case):
    draft_case[2].outputs[0]["template_id"] = "platform-decision-synthesis"
    result = run(draft_case)
    assert result["error"]["code"] == "CARD_GENERATION_TEMPLATE_INVALID"
    assert "draft_path" not in result

def test_unreadable_report_stops_without_retry(draft_case):
    draft_case[2].outputs[0]["source_read_status"] = "UNREADABLE"
    result = run(draft_case)
    assert result["error"]["code"] == "PDF_DIRECT_READING_INCOMPLETE"
    assert len(draft_case[2].calls) == 1
    assert "draft_path" not in result

def test_group_and_user_keys_have_separate_append_only_paths(draft_case):
    _, record, provider, _, output = draft_case
    first = run(draft_case)
    first_bytes = Path(first["draft_path"]).read_bytes()
    provider.outputs.append(deepcopy(output))
    second = run(draft_case)
    assert first["draft_path"] != second["draft_path"]
    record["library"] = {"type": "group", "id": 42}
    provider.outputs.append(deepcopy(output))
    group = run(draft_case)
    assert f"group-42-{PARENT_KEY}" in group["draft_path"]
    assert Path(first["draft_path"]).read_bytes() == first_bytes
    assert len(provider.calls) == 3  # One per explicit request; never an internal retry.

def test_multi_agent_config_fails_before_dispatch(draft_case):
    app, record, provider, adapter, _ = draft_case
    result = card_draft.generate_subject_card_draft(
        replace(app, card_generator=replace(app.card_generator, workflow_mode="multi_agent")),
        record, adapter=adapter)
    assert result["error"]["code"] == "CARD_DRAFT_SINGLE_AGENT_REQUIRED"
    assert not provider.calls

def test_paths_toml_and_dotenv_share_pr27_precedence(draft_case, tmp_path, monkeypatch):
    config_path = tmp_path / "paths.toml"
    config_path.write_text('[literature]\nroot = "' + (tmp_path / "configured").as_posix()
                           + '"\nexternal = true\n', encoding="utf-8")
    monkeypatch.setattr(literature_config, "DEFAULT_PATHS_CONFIG", config_path)
    monkeypatch.setattr(literature_config, "read_dotenv_values", lambda: {})
    monkeypatch.delenv("HYDROLITAGENT_LITERATURE_ROOT")
    configured = run(draft_case)
    assert Path(configured["literature_root"]) == tmp_path / "configured"
    draft_case[2].outputs.append(deepcopy(draft_case[4]))
    monkeypatch.setattr(literature_config, "read_dotenv_values",
                        lambda: {"HYDROLITAGENT_LITERATURE_ROOT": str(tmp_path / "dotenv")})
    from_dotenv = run(draft_case)
    assert Path(from_dotenv["literature_root"]) == tmp_path / "dotenv"

def test_default_root_and_external_opt_in(draft_case, tmp_path, monkeypatch):
    config_path = tmp_path / "paths.toml"
    monkeypatch.setattr(literature_config, "DEFAULT_PATHS_CONFIG", config_path)
    monkeypatch.setattr(literature_config, "read_dotenv_values", lambda: {})
    monkeypatch.setattr(literature_config, "DEFAULT_LITERATURE_ROOT", tmp_path / "outputs")
    monkeypatch.delenv("HYDROLITAGENT_LITERATURE_ROOT")
    result = run(draft_case)
    assert Path(result["literature_root"]) == tmp_path / "outputs"
    config_path.write_text('[literature]\nroot = "' + (tmp_path / "forbidden").as_posix()
                           + '"\nexternal = false\n', encoding="utf-8")
    failed = run(draft_case)
    assert failed["error"]["code"] == "CARD_DRAFT_PATH_INVALID"
    assert len(draft_case[2].calls) == 1

def test_save_failure_keeps_single_attempt_and_reports_failure(draft_case):
    with patch.object(card_draft, "_save", side_effect=PermissionError("read-only cloud")):
        result = run(draft_case)
    assert not result["ok"]
    assert result["failed_stage"] == "save"
    diagnostic = result["error"]["diagnostic"]["unvalidated_model_output_path"]
    assert Path(diagnostic).is_file()
    assert len(draft_case[2].calls) == 1
    assert "draft_path" not in result

def test_cli_consumes_ready_json_without_zotero_or_group(draft_case, tmp_path, capsys):
    app, record, provider, adapter, _ = draft_case
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps(record), encoding="utf-8-sig")
    with patch.object(cli, "load_config", return_value=app) as loader, \
         patch.object(cli, "preflight", side_effect=AssertionError("must not contact Zotero")), \
         patch.object(card_draft, "build_card_generator_adapter", return_value=adapter):
        code = cli.main(["evidence-generate", "--paper-input", str(input_file), "--json", "--no-progress"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0, result
    loader.assert_not_called()
    assert result["status"] == "DRAFT_PENDING_VALIDATION"
    assert len(provider.calls) == 1

def test_cli_stdin_and_bad_json(draft_case, capsys):
    app, record, _, adapter, _ = draft_case
    with patch.object(cli, "load_config", return_value=app), \
         patch.object(card_draft, "build_card_generator_adapter", return_value=adapter), \
         patch("sys.stdin", io.StringIO(json.dumps(record))):
        assert cli.main(["evidence-generate", "--paper-input", "-", "--json", "--no-progress"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    with patch.object(cli, "load_config", return_value=app), patch("sys.stdin", io.StringIO("{bad")):
        assert cli.main(["evidence-generate", "--paper-input", "-", "--json", "--no-progress"]) == 3
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "CARD_DRAFT_INPUT_INVALID"

def test_cli_keeps_old_item_key_and_rejects_ambiguous_source():
    parsed = cli._parser().parse_args(["evidence-generate", "--item-key", PARENT_KEY])
    assert parsed.item_key == PARENT_KEY and parsed.paper_input is None
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["evidence-generate", "--item-key", PARENT_KEY, "--paper-input", "input.json"])
