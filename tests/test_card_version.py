"""Immutable card versions: one card_id per paper, one directory per saved result.

The rules under test are the ones #35 states:

* only a card whose newest validation passed may become a version;
* a partial reading is not a version either, because a version is an asset the
  theme step may consume;
* the same content and the same input are one version, not two;
* new content or a new input is a new version, and the old one stays readable;
* a failed write never moves the current-version pointer.
"""
from __future__ import annotations

import json

import pytest

from hydrolitagent.cards.application import card_version
from hydrolitagent.cards.application.card_version import (
    load_card_version,
    save_card_version,
)
from hydrolitagent.cards.card_validation import fingerprint
from hydrolitagent.cards.domain.errors import CardGenerationError

PARENT_KEY = "7F8QLSNY"
DRAFT_ID = "28d86d502bbf446b"
INPUT_SHA = "b" * 64


def _draft(*, body: str = "## 研究问题\n\n洪水与风暴造成的服务中断如何级联。\n") -> dict:
    return {
        "schema_version": 2,
        "draft_id": DRAFT_ID,
        "status": "DRAFT_PENDING_VALIDATION",
        "pipeline": "markdown",
        "source": {
            "library": {"type": "group", "id": 6618088},
            "parent_key": PARENT_KEY,
            "attachment_key": "DZHJDJ3V",
            "pdf_sha256": "c" * 64,
            "pdf_size_bytes": 5115586,
            "pdf_page_count": 17,
            "item": {"item_key": PARENT_KEY, "title": "A paper", "doi": "10.1/x"},
        },
        "card_body_markdown": body,
        "machine_fields": {
            "schema_version": 2,
            "findings": [{"finding_id": "F001", "statement": "s"}],
            "boundaries": [],
        },
        "provenance": {"prompt_version": "markdown-reading-v1", "converter_id": "pymupdf"},
        "process_audit": {"runner_id": "in_session", "model_invoked": False},
        "usage": None,
        "warnings": [],
    }


def _validation(draft: dict, *, status: str = "PASS", reading_verified: bool = True,
                input_sha: str = INPUT_SHA) -> dict:
    passed = status == "PASS"
    return {
        "schema_version": 1,
        "operation": "subject_card_validation",
        "validation_id": "aa68b355586148a2a3f8ac51551fb3d2",
        "validated_at": "2026-10-28T08:40:44.805886+00:00",
        "policy_version": "subject-card-validation-v2",
        "validator_sha256": "d" * 64,
        "ok": passed,
        "status": status,
        "reading_verified": reading_verified,
        "reading_status": "VERIFIED" if reading_verified else "PARTIAL",
        "eligible_for_theme_generation": passed and reading_verified,
        "draft_id": draft["draft_id"],
        "draft_sha256": fingerprint(draft),
        "input_sha256": input_sha,
    }


def _workspace(tmp_path, *, draft: dict | None = None, validation: dict | None = None):
    """Write one draft and one validation record the way the workflow does."""

    draft = draft or _draft()
    validation = validation or _validation(draft)
    directory = tmp_path / "zotero" / f"group-6618088-{PARENT_KEY}" / "drafts" / draft["draft_id"]
    (directory / "validations" / validation["validation_id"]).mkdir(parents=True, exist_ok=True)
    (directory / "draft.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (directory / "validations" / validation["validation_id"] / "validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return tmp_path, directory / "draft.json", validation


def _save(tmp_path, draft_path):
    return save_card_version(tmp_path, draft_path)


def test_a_pass_card_becomes_the_first_version(tmp_path) -> None:
    root, draft_path, _ = _workspace(tmp_path)

    saved = _save(root, draft_path)

    assert saved["created"] is True
    assert saved["card_id"] == f"EV-{PARENT_KEY}"
    assert saved["version_id"] == "v1"
    version = root / "card-versions" / f"EV-{PARENT_KEY}" / "versions" / "v1"
    assert sorted(p.name for p in version.iterdir()) == [
        "card.md", "machine_fields.json", "manifest.json", "source.json", "validation.json"
    ]
    manifest = json.loads((version / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version_number"] == 1
    assert manifest["card_id"] == f"EV-{PARENT_KEY}"
    assert manifest["reading_status"] == "VERIFIED"
    current = json.loads(
        (root / "card-versions" / f"EV-{PARENT_KEY}" / "current.json").read_text(encoding="utf-8")
    )
    assert current["version_id"] == "v1"


def test_the_saved_card_is_the_body_without_the_pending_banner(tmp_path) -> None:
    root, draft_path, _ = _workspace(tmp_path)

    _save(root, draft_path)

    card = (root / "card-versions" / f"EV-{PARENT_KEY}" / "versions" / "v1" / "card.md").read_text(
        encoding="utf-8"
    )
    assert "待校验" not in card
    assert card.startswith("## 研究问题")


def test_changed_content_adds_a_version_and_keeps_the_old_one(tmp_path) -> None:
    root, draft_path, _ = _workspace(tmp_path)
    _save(root, draft_path)
    first = root / "card-versions" / f"EV-{PARENT_KEY}" / "versions" / "v1" / "card.md"
    before = first.read_bytes()

    changed = _draft(body="## 研究问题\n\n改写后的正文，内容已经不同。\n")
    _workspace(tmp_path, draft=changed, validation=_validation(changed))
    saved = save_card_version(root, draft_path)

    assert saved["version_id"] == "v2"
    assert first.read_bytes() == before
    assert (first.parent.parent / "v2" / "card.md").exists()


def test_changed_input_adds_a_version_even_when_the_card_is_identical(tmp_path) -> None:
    root, draft_path, _ = _workspace(tmp_path)
    _save(root, draft_path)

    # Same bytes, but the record now points at a different source PDF.
    draft = _draft()
    _workspace(tmp_path, draft=draft, validation=_validation(draft, input_sha="e" * 64))
    saved = save_card_version(root, draft_path)

    assert saved["version_id"] == "v2"


def test_the_same_result_twice_is_one_version(tmp_path) -> None:
    root, draft_path, _ = _workspace(tmp_path)
    first = _save(root, draft_path)

    second = _save(root, draft_path)

    assert first["version_id"] == second["version_id"] == "v1"
    assert second["created"] is False
    assert len(list((root / "card-versions" / f"EV-{PARENT_KEY}" / "versions").iterdir())) == 1


def test_a_failed_validation_cannot_become_a_version(tmp_path) -> None:
    draft = _draft()
    root, draft_path, _ = _workspace(
        tmp_path, draft=draft, validation=_validation(draft, status="FAIL")
    )

    with pytest.raises(CardGenerationError) as excinfo:
        _save(root, draft_path)

    assert excinfo.value.code == "CARD_VERSION_REQUIRES_PASS"
    assert not (root / "card-versions").exists()


def test_a_partial_reading_cannot_become_a_version(tmp_path) -> None:
    draft = _draft()
    root, draft_path, _ = _workspace(
        tmp_path, draft=draft, validation=_validation(draft, reading_verified=False)
    )

    with pytest.raises(CardGenerationError) as excinfo:
        _save(root, draft_path)

    assert excinfo.value.code == "CARD_VERSION_REQUIRES_VERIFIED_READING"


def test_a_validation_that_no_longer_describes_the_draft_is_rejected(tmp_path) -> None:
    root, draft_path, _ = _workspace(tmp_path)
    # The draft changes after it was validated; the stale PASS must not be reused.
    draft_path.write_text(
        json.dumps(_draft(body="## 研究问题\n\n校验之后又被改过的正文。\n"),
                   ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(CardGenerationError) as excinfo:
        _save(root, draft_path)

    assert excinfo.value.code == "CARD_VERSION_VALIDATION_STALE"


def test_a_failed_write_leaves_the_current_version_alone(tmp_path, monkeypatch) -> None:
    root, draft_path, _ = _workspace(tmp_path)
    _save(root, draft_path)

    changed = _draft(body="## 研究问题\n\n第二次写入，会在落盘时失败。\n")
    _workspace(tmp_path, draft=changed, validation=_validation(changed))

    def explode(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(card_version, "_write_version_files", explode)
    with pytest.raises(CardGenerationError) as excinfo:
        _save(root, draft_path)

    assert excinfo.value.code == "CARD_VERSION_IO_ERROR"
    current = json.loads(
        (root / "card-versions" / f"EV-{PARENT_KEY}" / "current.json").read_text(encoding="utf-8")
    )
    assert current["version_id"] == "v1"
    versions = sorted(p.name for p in (root / "card-versions" / f"EV-{PARENT_KEY}" / "versions").iterdir())
    assert versions == ["v1"], "失败的那次不能留下半成品版本目录"


def test_load_returns_the_machine_fields_and_the_body(tmp_path) -> None:
    root, draft_path, _ = _workspace(tmp_path)
    _save(root, draft_path)

    loaded = load_card_version(root, f"EV-{PARENT_KEY}")

    assert loaded["version_id"] == "v1"
    assert loaded["machine_fields"]["findings"][0]["finding_id"] == "F001"
    assert loaded["card"].startswith("## 研究问题")
    assert loaded["paths"]["manifest"].endswith("manifest.json")


def test_load_an_unknown_version_is_a_structured_error(tmp_path) -> None:
    root, draft_path, _ = _workspace(tmp_path)
    _save(root, draft_path)

    with pytest.raises(CardGenerationError) as excinfo:
        load_card_version(root, f"EV-{PARENT_KEY}", "v9")

    assert excinfo.value.code == "CARD_VERSION_NOT_FOUND"
