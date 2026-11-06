"""A theme needs two papers, and the answer contract must reach the model.

Two rules from the 2026-10-30 theme runs (#33):

* four selected cards came back as three "themes", one of them supported by a
  single paper — that is the card again with a new title, not a synthesis;
* the answer used ``action``/``markdown`` instead of ``kind``/``title``/
  ``candidate_markdown``, because the server refused ``response_format`` and the
  prompt never showed the field names.
"""
from __future__ import annotations

from hydrolitagent.cards import theme_pool as pool
from hydrolitagent.cards.theme_pool_runner import discovery_prompt, reading_prompt

SOURCES = {
    "EV-AAAA1111": {"record": {"evidence_id": "EV-AAAA1111"}},
    "EV-BBBB2222": {"record": {"evidence_id": "EV-BBBB2222"}},
}


def _child(evidence_ids):
    return {
        "title": "测试主题",
        "candidate_markdown": "候选正文",
        "paper_tasks": [
            {"evidence_id": eid, "focus": "看方法", "reuse_reading_id": None, "reuse_reason": None}
            for eid in evidence_ids
        ],
    }


def _output(evidence_ids):
    return {
        "problem_clusters_markdown": "分成一个簇。",
        "actions": [{"kind": "CREATE", "theme_ids": [], "reason": "新问题", "themes": [_child(evidence_ids)]}],
    }


def test_two_sources_make_a_theme():
    planned = pool.plan_actions(_output(["EV-AAAA1111", "EV-BBBB2222"]), {"themes": {}}, SOURCES, "CHANGE-x", {})
    assert len(planned) == 1
    assert len(planned[0]["themes"][0]["paper_tasks"]) == 2


def test_one_source_is_not_a_theme():
    dropped: list[dict] = []
    planned = pool.plan_actions(_output(["EV-AAAA1111"]), {"themes": {}}, SOURCES, "CHANGE-x", {},
                                dropped=dropped)
    # A paper with no partner does not form a theme, and the run is not failed
    # over it: it is recorded and the other themes still go ahead (#33).
    assert planned == []
    assert dropped[0]["title"] == "测试主题"
    assert dropped[0]["evidence_ids"] == ["EV-AAAA1111"]
    assert dropped[0]["source_count"] == 1


def test_a_single_paper_cluster_does_not_take_the_other_themes_down():
    output = {
        "problem_clusters_markdown": "两个簇。",
        "actions": [
            {"kind": "CREATE", "theme_ids": [], "reason": "新问题",
             "themes": [_child(["EV-AAAA1111"])]},
            {"kind": "CREATE", "theme_ids": [], "reason": "另一个问题",
             "themes": [_child(["EV-AAAA1111", "EV-BBBB2222"])]},
        ],
    }
    dropped: list[dict] = []
    planned = pool.plan_actions(output, {"themes": {}}, SOURCES, "CHANGE-x", {}, dropped=dropped)

    assert len(planned) == 1
    assert len(planned[0]["themes"][0]["paper_tasks"]) == 2
    assert [item["title"] for item in dropped] == ["测试主题"]


def test_the_dropped_cluster_is_written_down_not_silently_lost():
    text = pool.unclustered_markdown(
        [{"title": "社交媒体洪水图像识别", "evidence_ids": ["EV-AAAA1111"], "source_count": 1}],
        min_sources=2,
    )

    assert "未构成主题" in text
    assert "社交媒体洪水图像识别" in text
    assert "EV-AAAA1111" in text
    assert "至少 2 篇" in text
    assert "不强行凑成主题" in text


def test_the_discovery_prompt_carries_the_field_contract():
    assets = {
        "discovery.md": "主题组织要求",
        "pool-discovery.md": "池演化要求",
        "pool-discovery.schema.json": '{"required": ["problem_clusters_markdown", "actions"]}',
    }
    prompt = discovery_prompt(assets, {})
    assert '"required": ["problem_clusters_markdown", "actions"]' in prompt
    assert "不要自造字段名" in prompt


def test_the_reading_prompt_carries_its_own_contract():
    assets = {
        "focused-reading-markdown.md": "精读要求",
        "focused-reading-markdown.schema.json": '{"required": ["reading_markdown"]}',
    }
    prompt = reading_prompt(
        assets, candidate="候选", focus="看方法", evidence_id="EV-AAAA1111",
        rough_card="粗卡", reading_parameters={})
    assert '"required": ["reading_markdown"]' in prompt
