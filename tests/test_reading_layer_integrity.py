"""Reading-layer integrity: fail closed, bind validations, write atomically.

These tests target the failure modes a reader cannot see from the pages alone:
a partial scan silently dropping cards, a validation record outliving the draft
it described, and an interrupted write truncating HOME.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydrolitagent.cards.application import reading_layer
from hydrolitagent.cards.application.reading_layer import build_reading_layer
from test_reading_layer import SHA_A, _add_draft, _draft, _validation, _write_json


def _one_pass_draft(root: Path, *, draft_id: str = "draft-pass",
                    parent_key: str = "AAAA1111") -> Path:
    _add_draft(
        root,
        f"user-0-{parent_key}",
        _draft(
            draft_id=draft_id, parent_key=parent_key, title=f"论文 {parent_key}",
            date="2020", doi="10.1/a", attachment="ATTACH01", sha=SHA_A,
            body="# 卡\n\n正文", created_at="2026-01-02T00:00:00Z",
        ),
        _validation(status="PASS", validated_at="2026-01-03T00:00:00+00:00",
                    reading_verified=True),
    )
    return root / "zotero" / f"user-0-{parent_key}" / "drafts" / draft_id / "draft.json"


def test_a_broken_draft_keeps_the_previous_home(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    draft_path = _one_pass_draft(root)
    first = build_reading_layer(root, runtime_dir=tmp_path / ".runtime")
    assert first["ok"] is True, first
    home = root / "HOME.md"
    before = home.read_bytes()

    # A second, unreadable draft must abort the rebuild instead of writing a
    # HOME that has silently lost the first card.
    broken = root / "zotero" / "user-0-BBBB2222" / "drafts" / "draft-broken" / "draft.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{not json", encoding="utf-8")

    second = build_reading_layer(root, runtime_dir=tmp_path / ".runtime")

    assert second["ok"] is False
    assert second["error"]["code"] == "READING_LAYER_SCAN_DEGRADED"
    assert any(item.startswith("DRAFT_INVALID:") for item in second["errors"])
    assert home.read_bytes() == before
    assert draft_path.is_file()


def test_edited_draft_is_not_advertised_as_pass(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    draft_path = _one_pass_draft(root)

    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    draft["card_body_markdown"] += "\n\n校验之后新增的段落。\n"
    _write_json(draft_path, draft)

    report = build_reading_layer(root, runtime_dir=tmp_path / ".runtime")

    assert any(item.startswith("VALIDATION_STALE:AAAA1111") for item in report["warnings"])
    card = (root / "cards" / "AAAA1111" / "card.md").read_text(encoding="utf-8")
    assert 'status: "PASS"' not in card
    assert 'status: "未校验"' in card


def test_failed_replace_leaves_the_old_home_intact(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    _one_pass_draft(root)
    assert build_reading_layer(root, runtime_dir=tmp_path / ".runtime")["ok"] is True
    home = root / "HOME.md"
    before = home.read_bytes()

    # The next build has one more card, so HOME would change; make only its
    # atomic replace fail and assert the previous page is not truncated.
    _one_pass_draft(root, draft_id="draft-two", parent_key="BBBB2222")
    real = reading_layer.atomic_text

    def flaky(path, text):
        if Path(path).name == "HOME.md":
            raise OSError("disk full")
        return real(path, text)

    monkeypatch.setattr(reading_layer, "atomic_text", flaky)

    with pytest.raises(OSError):
        build_reading_layer(root, runtime_dir=tmp_path / ".runtime")

    assert home.read_bytes() == before
