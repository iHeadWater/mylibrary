"""#31: fixed #30 provider fixtures, no network or scientific correctness claim."""
from copy import deepcopy
import hashlib
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from hydrolitagent.cards._paths import ASSETS_DIR, PACKAGE_DIR
from hydrolitagent.cards import card_validation as gate, cli, themes
from card_fixtures import legacy_draft_case


@pytest.fixture
def case(legacy_draft_case):
    return legacy_draft_case


def check(case):
    return gate.validate_subject_card(*case[:3])


def codes(report):
    return {e["code"] for e in report["errors"]}


def save(case):
    app, draft, _, path, input_path = case
    path.write_text(json.dumps(draft), encoding="utf-8")
    return gate.validate_subject_card_file(app, path, input_path)


def select(case, report):
    return {"draft_path": case[3], "input_path": case[4], "validation_path": report["validation_path"]}


def _markdown_provenance() -> dict:
    """Build the v2 provenance the Markdown pipeline would have written."""
    from hydrolitagent.cards.application.prompts import load_template_bundle, read_prompt

    assets = gate.ValidationAssets.from_root()
    base = read_prompt(assets.generation_prompt)
    reading = read_prompt(assets.markdown_reading_prompt)
    catalog, templates = load_template_bundle(assets.templates_dir, assets.catalog_file)
    template = templates["original-research"]
    return {
        "prompt_version": base["version"], "prompt_sha256": base["sha256"],
        "draft_prompt_version": reading["version"], "draft_prompt_sha256": reading["sha256"],
        "combined_prompt_sha256": "b" * 64,
        "output_schema_sha256": hashlib.sha256(
            assets.markdown_output_schema.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest(),
        "template_id": "original-research",
        "template_version": template["local_version"],
        "template_sha256": template["content_sha256"],
        "catalog_version": catalog["catalog_version"],
        "converter_id": "pymupdf", "converter_version": "1.0-test",
        "runner_id": "scripted",
        "generation_protocol_version": gate.MARKDOWN_CARD_PROTOCOL_VERSION,
    }


@pytest.fixture
def markdown_case(case):
    """Turn the v1 fixture into the v2 draft the Markdown pipeline saves."""
    draft = case[1]
    access = {
        "method": gate.MARKDOWN_PREPARED,
        "source_pdf_sha256": draft["source"]["pdf_sha256"],
        "markdown_sha256": "a" * 64,
        "parent_key": draft["source"]["parent_key"],
        "page_count": draft["source"]["pdf_page_count"],
        "converter_id": "pymupdf",
        "converter_version": "1.0-test",
        "reading": {
            "read_mode": "file",
            "model_claimed_status": "FULL_MARKDOWN_REVIEWED",
            "verified_pages": [2],
            # Pages 2 and 3 carry prose; page 4 is a full-page figure and can be
            # mentioned without a quote.
            "content_pages": [2, 3],
            "verified_quotes": 1,
            "quote_coverage": 1.0,
            "canaries_ok": True,
            "anchor_conflicts": [],
            "verified": True,
            "full_read_verified": True,
            "scientific_correctness_verified": False,
        },
    }
    draft.update(
        schema_version=gate.MARKDOWN_DRAFT_SCHEMA_VERSION,
        pipeline="markdown",
        source_access=deepcopy(access),
        reading_record=deepcopy(access),
        provenance=_markdown_provenance(),
    )
    # A v2 card is read by a human: it points at pages, not at machine ids.
    draft["card_body_markdown"] = "# Fixed paper\n\nFixture result（第 2 页）.\n"
    return case


def test_valid_short_draft_passes_without_ai_or_mutating_inputs(case):
    before = deepcopy(case[1:3])
    report = check(case)
    assert report["status"] == "PASS", report
    assert report["eligible_for_theme_generation"]
    assert not report["scientific_correctness_verified"]
    assert not report["production_eligible"]
    assert report["warnings"][0]["code"] == "CARD_TEXT_SHORT"
    assert report["draft_sha256"] == gate.fingerprint(case[1])
    assert case[1:3] == before


@pytest.mark.parametrize("field", gate.FIELDS)
def test_every_minimum_content_category_is_required(case, field):
    case[1]["machine_fields"][field] = []
    result = check(case)
    assert "CARD_CONTENT_MISSING" in codes(result)
    assert any(e["path"] == f"/machine_fields/{field}" for e in result["errors"])
    assert not result["eligible_for_theme_generation"]


@pytest.mark.parametrize("value", [None, "wrong", {}, {"schema_version": 1}])
def test_machine_shape_missing_or_wrong_type(case, value):
    case[1]["machine_fields"] = value
    assert codes(check(case)) & {"CARD_FIELD_TYPE", "CARD_FIELD_MISSING"}


@pytest.mark.parametrize("field,value,code", [
    ("statement", "", "CARD_CONTENT_MISSING"),
    ("statement", "TBD", "CARD_CONTENT_MISSING"),
    ("statement", "未报告", "CARD_CONTENT_MISSING"),
    ("statement", "{{result}}", "CARD_CONTENT_MISSING"),
    ("statement_role", "verified_science", "CARD_FIELD_ENUM"),
    ("information_status", True, "CARD_FIELD_TYPE"),
    ("source_locations", [], "CARD_LOCATION_REQUIRED"),
    ("source_locations", [{"pdf_page": 2}], "CARD_FIELD_MISSING"),
])
def test_invalid_statement_returns_structured_path(case, field, value, code):
    case[1]["machine_fields"]["findings"][0][field] = value
    report = check(case)
    assert code in codes(report)
    assert all(e["path"].startswith("/") for e in report["errors"])


@pytest.mark.parametrize("page", [0, -1, 13, 10**400, True, "2", None])
def test_locations_must_use_real_pdf_page_range(case, page):
    case[1]["machine_fields"]["findings"][0]["source_locations"][0]["pdf_page"] = page
    assert "CARD_LOCATION_INVALID" in codes(check(case))


def test_explicit_missing_information_needs_no_invented_location(case):
    case[1]["machine_fields"]["missing_information"] = [{
        "statement": "论文未报告参数敏感性分析，无法从本文获得该信息。",
        "statement_role": "information_boundary", "information_status": "not_reported",
        "source_locations": [],
    }]
    assert check(case)["ok"]
    case[1]["machine_fields"]["missing_information"][0]["statement_role"] = "original_statement"
    assert "CARD_INFORMATION_BOUNDARY" in codes(check(case))


def test_reported_external_paraphrase_is_not_independent_verification(case):
    statement = case[1]["machine_fields"]["comparison_baselines"][0]
    statement.update(
        statement="当前论文第 2 页转述另一研究的比较结果；未核查被引原文。",
        statement_role="original_paraphrase", information_status="reported",
    )
    report = check(case)
    assert report["status"] == "PASS", report
    assert not report["scientific_correctness_verified"]
    statement["source_locations"] = []
    assert "CARD_LOCATION_REQUIRED" in codes(check(case))


@pytest.mark.parametrize("status", ["not_reported", "not_applicable", "unavailable"])
def test_missing_information_requires_boundary_role_for_every_status(case, status):
    statement = case[1]["machine_fields"]["comparison_baselines"][0]
    statement.update(statement="所需比较材料未提供或不适用于当前来源，无法据此比较。",
                     information_status=status, statement_role="original_paraphrase",
                     source_locations=[])
    assert "CARD_INFORMATION_BOUNDARY" in codes(check(case))
    statement["statement_role"] = "information_boundary"
    assert check(case)["status"] == "PASS"


def test_body_can_reorder_findings_without_renumbering(case):
    fields = case[1]["machine_fields"]
    second = deepcopy(fields["findings"][0])
    second.update(finding_id="F002", statement="Second synthetic result for contract testing.")
    fields["findings"].append(second)
    case[1]["card_body_markdown"] = "F002: second fixture result.\n\nF001: first fixture result."
    assert check(case)["status"] == "PASS"


@pytest.mark.parametrize("body", ["", "# Heading only\n", "<!-- F001 hidden -->", "TBD"])
def test_missing_readable_body_fails_even_with_machine_fields(case, body):
    case[1]["card_body_markdown"] = body
    assert "CARD_CONTENT_MISSING" in codes(check(case))


def test_finding_ids_are_unique_and_referenced(case):
    findings = case[1]["machine_fields"]["findings"]
    findings.append(deepcopy(findings[0]))
    assert "CARD_FINDING_ID_INVALID" in codes(check(case))
    findings.pop()
    findings[0]["finding_id"] = "F002"
    assert "CARD_FINDING_REFERENCE" in codes(check(case))


@pytest.mark.parametrize("field,value", [
    ("parent_key", "OTHER123"), ("attachment_key", "OTHER123"),
    ("pdf_sha256", "0"*64), ("pdf_size_bytes", True),
    ("library", {"type": "group", "id": 9}), ("requested_item_key", "OTHER123"),
    ("item", {"item_key": "OTHER123", "title": "Another paper"}),
])
def test_source_is_bound_to_input_record(case, field, value):
    case[1]["source"][field] = value
    assert "CARD_SOURCE_MISMATCH" in codes(check(case))


@pytest.mark.parametrize("part", ["schema_version", "draft_id", "created_at", "status"])
def test_card_version_and_state_are_required(case, part):
    del case[1][part]
    assert not check(case)["ok"]


def test_input_and_machine_versions_are_strict_integers(case):
    case[2]["schema_version"] = True
    case[1]["machine_fields"]["schema_version"] = True
    assert {"CARD_INPUT_VERSION", "CARD_FIELD_TYPE"} <= codes(check(case))


@pytest.mark.parametrize("field", [
    "template_version", "template_sha256", "catalog_version", "prompt_version",
    "prompt_sha256", "draft_prompt_version", "output_schema_sha256",
    "reading_prompt_sha256", "combined_prompt_sha256",
])
def test_wrong_or_missing_provenance_is_rejected(case, field):
    old = case[1]["provenance"].pop(field)
    assert "CARD_PROVENANCE_MISSING" in codes(check(case))
    case[1]["provenance"][field] = "wrong-" + str(old)
    assert "CARD_VERSION_MISMATCH" in codes(check(case))


def test_reading_identity_must_agree(case):
    case[1]["reading_record"]["source_sha256"] = "0"*64
    assert "CARD_READING_RECORD_INVALID" in codes(check(case))


def test_no_pdf_reread_and_deterministic_error_codes(case):
    # The #29 record + #30 reading record are inputs, not an instruction to re-read the paper.
    Path(case[2]["pdf"]["local_path"]).unlink()
    assert check(case)["ok"]
    case[1]["machine_fields"]["research_questions"] = []
    first, second = check(case), check(case)
    assert first["errors"] == second["errors"]
    assert first["draft_sha256"] == second["draft_sha256"]


def test_file_validation_is_append_only_and_preserves_draft(case):
    original = case[3].read_bytes()
    first = gate.validate_subject_card_file(case[0], case[3], case[4])
    second = gate.validate_subject_card_file(case[0], case[3], case[4])
    assert first["ok"] and second["ok"]
    assert first["validation_path"] != second["validation_path"]
    assert case[3].read_bytes() == original
    assert Path(first["validation_path"]).is_file()


def test_theme_boundary_accepts_current_pass_only(case):
    report = save(case)
    accepted = themes.load_subject_card_sources(case[0], [select(case, report)])
    assert accepted[0]["card"] == case[1]["card_body_markdown"]
    assert accepted[0]["validation"]["status"] == "PASS"
    assert case[1]["status"] == "DRAFT_PENDING_VALIDATION"


def test_theme_boundary_rejects_failed_card_even_with_forged_pass_label(case):
    case[1]["machine_fields"]["data_and_methods"] = []
    report = save(case)
    assert not report["ok"]
    path = Path(report["validation_path"])
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved.update(status="PASS", ok=True, eligible_for_theme_generation=True)
    path.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(themes.ThemeError, match="未通过校验"):
        themes.load_subject_card_sources(case[0], [select(case, report)])


@pytest.mark.parametrize("changed", ["draft", "input", "rules", "report"])
def test_stale_pass_is_not_reusable(case, monkeypatch, changed):
    report = save(case)
    if changed == "draft":
        case[1]["card_body_markdown"] += "\nA harmless edit still needs a new record."
        case[3].write_text(json.dumps(case[1]), encoding="utf-8")
    elif changed == "input":
        record = deepcopy(case[2])
        record["additional_input_revision"] = 2
        case[4].write_text(json.dumps(record), encoding="utf-8")
    elif changed == "rules":
        monkeypatch.setattr(gate, "POLICY", "subject-card-validation-v999")
    else:
        path = Path(report["validation_path"])
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["draft_sha256"] = "0"*64
        path.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(gate.CardValidationError) as error:
        gate.load_validated_subject_card(case[0], case[3], case[4], report["validation_path"])
    assert error.value.code == "CARD_VALIDATION_STALE"


def test_missing_report_and_mixed_selection_fail_closed(case):
    passed = save(case)
    missing = {**select(case, passed), "validation_path": str(case[3].parent / "absent.json")}
    with pytest.raises(themes.ThemeError) as error:
        themes.load_subject_card_sources(case[0], [select(case, passed), missing])
    assert error.value.code == "CARD_VALIDATION_REQUIRED"


@pytest.mark.parametrize("invalid", ['{"x":1,"x":2}', '{"x": NaN}', "{bad"])
def test_bad_json_returns_failure_not_an_exception(case, invalid):
    case[3].write_text(invalid, encoding="utf-8")
    report = gate.validate_subject_card_file(case[0], case[3], case[4])
    assert not report["ok"] and "validation_path" not in report
    assert codes(report) == {"CARD_VALIDATION_IO"}


def test_cannot_claim_pass_when_report_cannot_be_saved(case):
    with patch.object(gate, "atomic_text", side_effect=PermissionError):
        report = gate.validate_subject_card_file(case[0], case[3], case[4])
    assert not report["ok"] and not report["eligible_for_theme_generation"]


def test_cli_offline_personal_library_and_exit_status(case, capsys):
    with patch.object(cli, "load_config", return_value=case[0]) as config:
        args = ["evidence-validate", "--config", "explicit-config.json", "--draft", str(case[3]), "--paper-input", str(case[4]), "--json"]
        assert cli.main(args) == 0
        passed = json.loads(capsys.readouterr().out)
        assert passed["status"] == "PASS"
        assert config.call_args.kwargs["require_group"] is False
        case[1]["machine_fields"]["findings"] = []
        case[3].write_text(json.dumps(case[1]), encoding="utf-8")
        assert cli.main(args) == 3
        failed = json.loads(capsys.readouterr().out)
        assert failed["status"] == "FAIL" and Path(failed["validation_path"]).exists()



def test_hidden_comment_cannot_satisfy_finding_reference(case):
    case[1]["card_body_markdown"] = "Visible explanation.\n<!-- F001 -->"
    assert "CARD_FINDING_REFERENCE" in codes(check(case))


def test_boolean_source_id_cannot_impersonate_integer_library(case):
    case[2]["library"]["id"] = 1
    case[1]["source"]["library"]["id"] = True
    assert "CARD_SOURCE_MISMATCH" in codes(check(case))


@pytest.mark.parametrize("value", [None, [], "bad", {"schema_version": 1}])
def test_malformed_top_level_records_fail_without_crashing(case, value):
    assert not gate.validate_subject_card(case[0], value, case[2])["ok"]
    assert not gate.validate_subject_card(case[0], case[1], value)["ok"]


def test_current_pass_does_not_allow_wrong_report_boolean_types(case):
    report = save(case)
    path = Path(report["validation_path"])
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["ok"] = 1
    path.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(gate.CardValidationError) as error:
        gate.load_validated_subject_card(case[0], case[3], case[4], path)
    assert error.value.code == "CARD_VALIDATION_STALE"



def test_long_body_cannot_compensate_for_missing_content(case):
    case[1]["card_body_markdown"] += "\n" + "Long prose. " * 400
    case[1]["machine_fields"]["boundaries"] = []
    result = check(case)
    assert "CARD_CONTENT_MISSING" in codes(result)
    assert not result["warnings"]


def test_missing_reference_identifies_the_result_without_parsing_message(case):
    case[1]["machine_fields"]["findings"][0]["finding_id"] = "F002"
    result = check(case)
    assert {e["finding_id"] for e in result["errors"]
            if e["code"] == "CARD_FINDING_REFERENCE"} == {"F001", "F002"}



def test_cli_default_ignores_machine_config_and_accepts_external_report_dir(case, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HYDROLITAGENT_CARDS_CONFIG", str(tmp_path / "nonexistent-private.json"))
    monkeypatch.chdir(tmp_path)
    dest = tmp_path / "selected-reports"
    with patch.object(cli, "load_config", side_effect=AssertionError("must not load machine config")):
        assert cli.main(["evidence-validate", "--draft", str(case[3]), "--paper-input", str(case[4]),
                         "--report-dir", str(dest), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert Path(result["validation_path"]).is_relative_to(dest)
    assert Path(result["asset_paths"]["output_schema"]).is_file()
    assert not (case[3].parent / "validations").exists()


def test_report_environment_and_command_line_priority(case, tmp_path, monkeypatch, capsys):
    env_dir, explicit = tmp_path / "environment", tmp_path / "explicit"
    monkeypatch.setenv("HYDROLITAGENT_CARDS_VALIDATION_REPORT_DIR", str(env_dir))
    args = ["evidence-validate", "--draft", str(case[3]), "--paper-input", str(case[4]), "--json"]
    assert cli.main(args) == 0
    assert Path(json.loads(capsys.readouterr().out)["validation_path"]).is_relative_to(env_dir)
    assert cli.main(args + ["--report-dir", str(explicit)]) == 0
    assert Path(json.loads(capsys.readouterr().out)["validation_path"]).is_relative_to(explicit)


def test_assets_can_be_selected_from_a_relocated_copy(case, tmp_path):
    original = gate.ValidationAssets.from_root()
    root = tmp_path / "another checkout" / "hydro-platform"
    alternate = gate.ValidationAssets.from_root(root)
    for name, source in original.as_dict().items():
        if name == "templates_dir":
            continue
        target = Path(alternate.as_dict()[name])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for source in original.templates_dir.glob("*.md"):
        shutil.copyfile(source, alternate.templates_dir / source.name)
    report = gate.validate_subject_card(alternate, case[1], case[2])
    assert report["ok"], report
    changed = alternate.generation_prompt
    changed.write_text(changed.read_text(encoding="utf-8") + "\nModified asset.\n", encoding="utf-8")
    assert "CARD_VERSION_MISMATCH" in codes(gate.validate_subject_card(alternate, case[1], case[2]))


@pytest.mark.parametrize("source_path", [
    "C:\\research\\paper.pdf", "/home/research/paper.pdf", "\\\\server\\share\\paper.pdf",
])
def test_foreign_origin_path_is_not_resolved_again_on_this_host(case, source_path):
    from hydrolitagent.cards.application.card_draft import SINGLE_SOURCE_TEMPLATES
    from hydrolitagent.cards.application.prompts import (
        build_template_prompt, load_template_bundle, read_prompt,
    )
    import hashlib
    assets = gate.ValidationAssets.from_root()
    _, templates = load_template_bundle(assets.templates_dir, assets.catalog_file)
    templates = {k:v for k,v in templates.items() if k in SINGLE_SOURCE_TEMPLATES}
    case[2]["pdf"]["local_path"] = source_path
    source = case[1]["source"]
    context = {"library":case[2]["library"],"item":case[2]["item"],
               "zotero_parent_key":source["parent_key"],"zotero_attachment_key":source["attachment_key"],
               "source_pdf_sha256":source["pdf_sha256"],"source_pdf_absolute_path":source_path,
               "reading_scope":"FULL_PDF","card_state":"DRAFT_PENDING_VALIDATION",
               "enabled_template_ids":sorted(templates)}
    prompt = build_template_prompt(read_prompt(assets.generation_prompt), context, templates)
    prompt += "\n" + read_prompt(assets.draft_prompt)["content"]
    case[1]["provenance"]["combined_prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
    result = gate.validate_subject_card(assets, case[1], case[2])
    assert result["ok"], result


def test_assets_root_and_config_are_mutually_exclusive(case, capsys):
    assert cli.main(["evidence-validate", "--draft", str(case[3]), "--paper-input", str(case[4]),
                     "--config", "local.json", "--assets-root", "elsewhere", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "CONFIG_ERROR"


def test_shipped_example_passes_without_private_config_or_pdf(tmp_path, monkeypatch):
    root = ASSETS_DIR / "examples/subject-card-validation"
    draft = gate._read_json(root / "draft.json")
    record = gate._read_json(root / "paper-input.json")
    monkeypatch.chdir(tmp_path)
    assert gate.validate_subject_card(None, draft, record)["ok"]



def test_provider_protocol_cannot_mismatch_reading_method(case):
    case[1]["provenance"]["generation_protocol_version"] = "claude-local-pdf-v1"
    assert "CARD_READING_RECORD_INVALID" in codes(check(case))



def test_finding_reference_in_visible_heading_counts(case):
    case[1]["card_body_markdown"] = "# Fixture\n\n### F001 Result\n\nThis paragraph explains the reported synthetic result."
    assert check(case)["ok"]
    case[1]["card_body_markdown"] = "# F001 Heading only\n"
    assert "CARD_CONTENT_MISSING" in codes(check(case))


# --------------------------------------------------------------------------------------
# v2 drafts (Markdown-first pipeline)
# --------------------------------------------------------------------------------------


def test_markdown_v2_draft_passes_with_policy_v2(markdown_case):
    report = check(markdown_case)
    assert report["status"] == "PASS", report
    assert report["policy_version"] == "subject-card-validation-v2"
    assert report["report_mode"] == "CURRENT"
    assert report["draft_pipeline"] == "markdown"
    assert report["draft_schema_version"] == 2
    assert report["eligible_for_theme_generation"]
    assert report["reading_verified"] is True
    assert report["reading_status"] == "VERIFIED"
    # Neither a pass nor a programme check may claim scientific correctness.
    assert report["scientific_correctness_verified"] is False
    assert report["production_eligible"] is False
    assert report["warnings"][0]["code"] == "CARD_TEXT_SHORT"


def test_markdown_v2_body_must_point_at_a_verified_page(markdown_case):
    """A page the program never verified cannot be cited as if it had been."""

    markdown_case[1]["card_body_markdown"] = "# Fixed paper\n\nFixture result（第 3 页）.\n"
    report = check(markdown_case)
    assert report["status"] == "FAIL"
    errors = [e for e in report["errors"] if e["code"] == "CARD_PAGE_CITATION"]
    assert errors and errors[0]["page"] == 3
    assert not report["eligible_for_theme_generation"]


def test_markdown_v2_body_may_point_at_a_figure_only_page(markdown_case):
    """A page with nothing to quote is not a citation failure."""

    markdown_case[1]["card_body_markdown"] = (
        "# Fixed paper\n\nFigure 2 maps the catchments（第 4 页）.\n"
    )
    report = check(markdown_case)
    assert "CARD_PAGE_CITATION" not in codes(report)


def test_markdown_v2_body_must_cite_some_page(markdown_case):
    markdown_case[1]["card_body_markdown"] = "# Fixed paper\n\n没有页码的一段叙述。\n"
    report = check(markdown_case)
    assert "CARD_PAGE_CITATION" in codes(report)


def test_markdown_v2_body_takes_no_machine_ids(markdown_case):
    """``F001`` in the body is no longer a citation, so it cannot rescue one."""

    markdown_case[1]["card_body_markdown"] = "# Fixed paper\n\nF001: no page given.\n"
    report = check(markdown_case)
    assert "CARD_PAGE_CITATION" in codes(report)


def test_legacy_v1_report_is_marked_read_only(case):
    report = check(case)
    assert report["status"] == "PASS"
    assert report["policy_version"] == "subject-card-validation-v1"
    assert report["report_mode"] == "LEGACY_READ_ONLY"
    assert report["draft_pipeline"] == "legacy"

@pytest.mark.parametrize("field", ["reading", "method", "markdown_sha256", "converter_id", "page_count"])
def test_markdown_v2_missing_or_wrong_receipt_fields_fail(markdown_case, field):
    access = markdown_case[1]["source_access"]
    if field == "page_count":
        access[field] = access[field] + 1
    else:
        access[field] = "" if field in {"method", "markdown_sha256", "converter_id"} else None
    report = check(markdown_case)
    assert {"CARD_READING_RECORD_INVALID"} & codes(report)
    assert not report["eligible_for_theme_generation"]


def test_markdown_v2_pdf_sha_must_match_source_and_input(markdown_case):
    markdown_case[1]["source_access"]["source_pdf_sha256"] = "0" * 64
    assert "CARD_SOURCE_MISMATCH" in codes(check(markdown_case))
    markdown_case[1]["source_access"]["source_pdf_sha256"] = markdown_case[1]["source"]["pdf_sha256"]
    markdown_case[1]["source"]["pdf_sha256"] = "1" * 64
    assert "CARD_SOURCE_MISMATCH" in codes(check(markdown_case))


@pytest.mark.parametrize("key,value,code", [
    ("verified", False, "CARD_READING_NOT_VERIFIED"),
    ("canaries_ok", False, "CARD_READING_NOT_VERIFIED"),
    ("scientific_correctness_verified", True, "CARD_READING_RECORD_INVALID"),
    ("quote_coverage", 1.5, "CARD_READING_RECORD_INVALID"),
])
def test_markdown_v2_rejects_unverified_or_overclaiming_readings(markdown_case, key, value, code):
    reading = markdown_case[1]["source_access"]["reading"]
    reading[key] = value
    markdown_case[1]["reading_record"]["reading"][key] = value
    report = check(markdown_case)
    assert code in codes(report)
    assert not report["eligible_for_theme_generation"]
    if key in {"verified", "canaries_ok"}:
        assert report["reading_verified"] is False
        assert report["reading_status"] == "PARTIAL"


def test_markdown_v2_reading_record_must_match_source_access(markdown_case):
    markdown_case[1]["reading_record"]["markdown_sha256"] = "c" * 64
    assert "CARD_READING_RECORD_INVALID" in codes(check(markdown_case))


@pytest.mark.parametrize("field", ["runner_id", "converter_id", "template_sha256", "output_schema_sha256"])
def test_markdown_v2_provenance_is_required(markdown_case, field):
    del markdown_case[1]["provenance"][field]
    report = check(markdown_case)
    assert {"CARD_PROVENANCE_MISSING", "CARD_VERSION_MISMATCH"} & codes(report)
    assert not report["eligible_for_theme_generation"]


def test_markdown_v2_template_version_must_match_shipped_assets(markdown_case):
    markdown_case[1]["provenance"]["template_sha256"] = "d" * 64
    assert "CARD_VERSION_MISMATCH" in codes(check(markdown_case))


def test_markdown_v2_pipeline_label_is_required(markdown_case):
    markdown_case[1]["pipeline"] = "legacy"
    # Without the label the draft is read as v1 and the version check rejects it.
    assert "CARD_DRAFT_VERSION" in codes(check(markdown_case))


def test_markdown_v2_file_validation_and_theme_boundary(markdown_case):
    markdown_case[3].write_text(json.dumps(markdown_case[1]), encoding="utf-8")
    original = markdown_case[3].read_bytes()
    report = gate.validate_subject_card_file(markdown_case[0], markdown_case[3], markdown_case[4])
    assert report["ok"], report
    assert report["policy_version"] == "subject-card-validation-v2"
    assert markdown_case[3].read_bytes() == original
    accepted = themes.load_subject_card_sources(markdown_case[0], [select(markdown_case, report)])
    assert accepted[0]["card"] == markdown_case[1]["card_body_markdown"]
    assert accepted[0]["validation"]["status"] == "PASS"
