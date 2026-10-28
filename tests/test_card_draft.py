"""The live pieces of the single-paper draft path.

``read_paper_input`` proves the local PDF still matches the READY record,
``check_wire`` decodes the fixed machine-field shape and ``save_draft`` writes
the append-only draft. None of them calls a model; the executor is somebody
else's job.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from hydrolitagent.cards.application import card_draft
from hydrolitagent.cards.application.card_draft import (
    SINGLE_SOURCE_TEMPLATES,
    check_wire,
    read_paper_input,
    save_draft,
)
from hydrolitagent.cards.domain.errors import CardGenerationError
from card_fixtures import PARENT_KEY, machine_fields, paper_input_record, write_pdf


@pytest.fixture
def record(tmp_path):
    return paper_input_record(write_pdf(tmp_path / "paper.pdf"))


def test_ready_record_resolves_to_the_local_pdf(record, tmp_path):
    original = deepcopy(record)

    parsed, path = read_paper_input(record)

    assert parsed == original
    assert path == Path(record["pdf"]["local_path"]).resolve()
    assert record == original  # the record is copied, never mutated


@pytest.mark.parametrize("change", [
    {"status": "WAITING"}, {"status": "SELECTION_REQUIRED"}, {"ok": False},
    {"requested_item_key": "OTHER123"}, {"schema_version": True},
    {"operation": "paper_input_batch"}, {"pdf_attachment_count": 2},
    {"library": {"type": "group", "id": 0}}, {"library": {"type": "user", "id": True}},
])
def test_not_ready_or_ambiguous_record_is_rejected(record, change):
    record.update(change)
    with pytest.raises(CardGenerationError) as caught:
        read_paper_input(record)
    assert caught.value.code == "CARD_DRAFT_INPUT_INVALID"


@pytest.mark.parametrize("field,value,code", [
    ("parent_key", "OTHER123", "CARD_DRAFT_INPUT_INVALID"),
    ("attachment_key", "../wrong", "CARD_DRAFT_INPUT_INVALID"),
    ("local_path", "relative.pdf", "CARD_DRAFT_INPUT_INVALID"),
    ("sha256", "0" * 64, "PDF_INPUT_CHANGED"),
    ("file_size_bytes", 1, "PDF_INPUT_CHANGED"),
])
def test_input_identity_and_hash_are_bound(record, field, value, code):
    record["pdf"][field] = value
    with pytest.raises(CardGenerationError) as caught:
        read_paper_input(record)
    assert caught.value.code == code


def test_missing_pdf_is_not_a_draft(record):
    Path(record["pdf"]["local_path"]).unlink()
    with pytest.raises(CardGenerationError) as caught:
        read_paper_input(record)
    assert caught.value.code == "CARD_DRAFT_PDF_UNREADABLE"


def _schema():
    return json.loads(card_draft.SCHEMA.read_text(encoding="utf-8"))["properties"]["machine_fields"]


def test_wire_accepts_the_fixture_shape():
    check_wire(machine_fields(), _schema())


@pytest.mark.parametrize("bad", [None, [], {}, {"schema_version": 1}, "not JSON"])
def test_wire_rejects_unparseable_machine_fields(bad):
    with pytest.raises(CardGenerationError) as caught:
        check_wire(bad, _schema())
    assert caught.value.code == "CARD_DRAFT_OUTPUT_INVALID"


def test_wire_rejects_wrong_field_type():
    fields = machine_fields()
    fields["findings"][0]["source_locations"][0]["pdf_page"] = True
    with pytest.raises(CardGenerationError) as caught:
        check_wire(fields, _schema())
    assert caught.value.code == "CARD_DRAFT_OUTPUT_INVALID"


def test_wire_does_not_judge_content():
    # Empty categories and dangling finding ids are the validator's problem,
    # not the wire decoder's.
    fields = machine_fields()
    fields["research_questions"] = []
    fields["findings"][0]["finding_id"] = ""
    fields["findings"][0]["source_locations"][0]["pdf_page"] = 10**400
    check_wire(fields, _schema())


def _draft(record, draft_id="a" * 16):
    return {
        "schema_version": 2,
        "draft_id": draft_id,
        "status": "DRAFT_PENDING_VALIDATION",
        "source": {
            "library": record["library"],
            "parent_key": PARENT_KEY,
            "attachment_key": record["pdf"]["attachment_key"],
            "pdf_sha256": record["pdf"]["sha256"],
            "pdf_size_bytes": record["pdf"]["file_size_bytes"],
            "item": record["item"],
        },
        "card_body_markdown": "# Fixed paper\n\nF001: fixture result.\n",
    }


def test_save_is_append_only_and_marks_the_draft_pending(record, tmp_path):
    root = tmp_path / "cloud"
    root.mkdir()
    first = save_draft(root, _draft(record, "a" * 16))
    second = save_draft(root, _draft(record, "b" * 16))

    assert first["draft_path"] != second["draft_path"]
    assert Path(first["literature_root"]) == root.resolve()
    saved = json.loads(Path(first["draft_path"]).read_text(encoding="utf-8"))
    assert saved["status"] == "DRAFT_PENDING_VALIDATION"
    assert Path(first["card_path"]).read_text(encoding="utf-8").endswith(
        saved["card_body_markdown"]
    )
    # Re-saving the same result is a no-op, not a crash.
    again = save_draft(root, _draft(record, "a" * 16))
    assert again["created"] is False
    assert again["draft_path"] == first["draft_path"]
    # A different result under the same draft id is a conflict, never an overwrite.
    conflicting = _draft(record, "a" * 16)
    conflicting["card_body_markdown"] = "# Fixed paper\n\nF001: another result.\n"
    with pytest.raises(CardGenerationError) as caught:
        save_draft(root, conflicting)
    assert caught.value.code == "CARD_DRAFT_ALREADY_EXISTS"


def test_save_uses_group_and_user_paths(record, tmp_path):
    root = tmp_path / "cloud"
    root.mkdir()
    user = save_draft(root, _draft(record))
    record["library"] = {"type": "group", "id": 42}
    group = save_draft(root, _draft(record, "c" * 16))
    assert f"user-0-{PARENT_KEY}" in user["draft_path"]
    assert f"group-42-{PARENT_KEY}" in group["draft_path"]


def test_synthesis_templates_are_not_single_source():
    from hydrolitagent.cards.application.prompts import load_template_bundle
    from hydrolitagent.cards._paths import ASSETS_DIR

    _, templates = load_template_bundle(
        ASSETS_DIR / "templates/evidence-cards",
        ASSETS_DIR / "templates/evidence-cards/_catalog.json",
    )
    assert "platform-decision-synthesis" not in SINGLE_SOURCE_TEMPLATES
    assert SINGLE_SOURCE_TEMPLATES <= set(templates)
