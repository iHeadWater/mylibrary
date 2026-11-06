"""Choosing the cards a theme run consumes: explicit, versioned, never guessed.

The scanner refuses to run when one paper has several valid drafts
(``THEME_DUPLICATE_SOURCE``) because picking one silently would change what a
theme is made of. ``--select`` answers that question before the run starts
(#33): a card reference names the exact saved version, and the run consumes only
those.
"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from hydrolitagent.cards.application.card_version import save_card_version
from hydrolitagent.cards.themes import ThemeError, _collect_sources, _parse_selection
from test_card_version import PARENT_KEY, _draft, _validation

GROUP_ID = 6618088
EVIDENCE_ID = "EV-" + PARENT_KEY


def _config(tmp_path):
    return SimpleNamespace(
        zotero=SimpleNamespace(group_id=GROUP_ID),
        paths=SimpleNamespace(
            literature_root=tmp_path,
            evidence_packs_dir=tmp_path / "evidence-packs",
        ),
    )


def _write_draft(tmp_path, draft):
    directory = tmp_path / "zotero" / f"group-{GROUP_ID}-{PARENT_KEY}" / "drafts" / draft["draft_id"]
    (directory / "validations" / "record").mkdir(parents=True, exist_ok=True)
    (directory / "draft.json").write_text(
        __import__("json").dumps(draft, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (directory / "card.md").write_text("# 测试卡\n\n正文\n", encoding="utf-8")
    (directory / "validations" / "record" / "validation.json").write_text(
        __import__("json").dumps(_validation(draft), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return directory / "draft.json"


def _second_draft():
    draft = deepcopy(_draft(body="## 研究问题\n\n第二份合格草稿。\n"))
    draft["draft_id"] = "e6b7e6cd20ba419a"
    return draft


def test_a_bare_reference_means_the_current_version():
    assert _parse_selection(["EV-7F8QLSNY"]) == [("EV-7F8QLSNY", None)]


def test_an_explicit_version_is_kept():
    assert _parse_selection(["EV-7F8QLSNY@v2"]) == [("EV-7F8QLSNY", "v2")]


def test_surrounding_spaces_are_trimmed():
    assert _parse_selection([" EV-7F8QLSNY "]) == [("EV-7F8QLSNY", None)]


@pytest.mark.parametrize("value", ["EV-7F8QLSNY@latest", "ev-7f8qlsny", "EV-7F8QLSNY@", "EV-7F8QLSNY@v0", "7F8QLSNY"])
def test_a_malformed_reference_is_rejected(value):
    with pytest.raises(ThemeError) as caught:
        _parse_selection([value])
    assert caught.value.code == "THEME_SELECTION_INVALID"


def test_the_same_card_twice_is_rejected():
    with pytest.raises(ThemeError) as caught:
        _parse_selection(["EV-7F8QLSNY@v1", "EV-7F8QLSNY@v2"])
    assert caught.value.code == "THEME_SELECTION_INVALID"


def test_an_empty_selection_is_rejected():
    with pytest.raises(ThemeError) as caught:
        _parse_selection([])
    assert caught.value.code == "THEME_SELECTION_INVALID"


def test_a_bare_string_is_not_a_selection():
    with pytest.raises(ThemeError) as caught:
        _parse_selection("EV-7F8QLSNY")
    assert caught.value.code == "THEME_SELECTION_INVALID"


def test_scanning_still_refuses_two_drafts_of_one_paper(tmp_path):
    config = _config(tmp_path)
    _write_draft(tmp_path, _draft())
    _write_draft(tmp_path, _second_draft())
    with pytest.raises(ThemeError) as caught:
        _collect_sources(config, literature_root=tmp_path)
    assert caught.value.code == "THEME_DUPLICATE_SOURCE"


def test_selection_picks_the_saved_version_instead_of_refusing(tmp_path):
    config = _config(tmp_path)
    first = _write_draft(tmp_path, _draft())
    _write_draft(tmp_path, _second_draft())
    saved = save_card_version(tmp_path, first)

    sources, report = _collect_sources(
        config, literature_root=tmp_path, selected=[f"{saved['card_id']}@{saved['version_id']}"])

    assert list(sources) == [EVIDENCE_ID]
    assert sources[EVIDENCE_ID]["card_version"] == f"{saved['card_id']}@{saved['version_id']}"
    assert sources[EVIDENCE_ID]["directory"] == first.parent
    assert report["selected_cards"] == [sources[EVIDENCE_ID]["card_version"]]
    assert report["duplicate_sources"] == []


def test_a_newer_version_moves_the_bare_reference(tmp_path):
    config = _config(tmp_path)
    first = _write_draft(tmp_path, _draft())
    second = _write_draft(tmp_path, _second_draft())
    save_card_version(tmp_path, first)
    save_card_version(tmp_path, second)

    sources, _ = _collect_sources(config, literature_root=tmp_path, selected=[EVIDENCE_ID])

    assert sources[EVIDENCE_ID]["directory"] == second.parent
    assert sources[EVIDENCE_ID]["card_version"] == f"{EVIDENCE_ID}@v2"

    pinned, _ = _collect_sources(config, literature_root=tmp_path, selected=[f"{EVIDENCE_ID}@v1"])
    assert pinned[EVIDENCE_ID]["directory"] == first.parent


def test_a_selection_that_does_not_describe_a_valid_draft_is_rejected(tmp_path):
    config = _config(tmp_path)
    first = _write_draft(tmp_path, _draft())
    saved = save_card_version(tmp_path, first)
    # The draft changes after the version was saved: the saved version no longer
    # describes a draft the theme step may consume.
    (first.parent / "draft.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ThemeError) as caught:
        _collect_sources(config, literature_root=tmp_path,
                         selected=[f"{saved['card_id']}@{saved['version_id']}"])
    assert caught.value.code == "THEME_SELECTION_NOT_VALIDATED"


def test_an_unknown_card_is_a_structured_error(tmp_path):
    config = _config(tmp_path)
    _write_draft(tmp_path, _draft())
    with pytest.raises(ThemeError) as caught:
        _collect_sources(config, literature_root=tmp_path, selected=["EV-ZZZZZZZZ"])
    assert caught.value.code == "CARD_VERSION_NOT_FOUND"
