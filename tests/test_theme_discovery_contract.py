"""The discovery answer must carry both halves, and a miss must name what is missing.

A theme run starts by asking the model to cluster the sources and to say what to
do with the pool. The shipped schema requires ``problem_clusters_markdown`` and
``actions``; a 2026-10-30 run answered with ``actions`` only and the failure said
merely "为空", which named neither the field nor the half of the answer (#33).
"""
from __future__ import annotations

import pytest

from hydrolitagent.cards import theme_pool as pool
from hydrolitagent.cards.themes import ThemeError


def _plan(output):
    return pool.plan_actions(output, {}, {}, "CHANGE-test", {})


def test_an_answer_without_the_clusters_text_names_that_field():
    with pytest.raises(ThemeError) as caught:
        _plan({"actions": []})
    assert caught.value.code == "THEME_OUTPUT_EMPTY"
    assert "problem_clusters_markdown" in str(caught.value)


def test_an_answer_without_actions_names_that_field():
    with pytest.raises(ThemeError) as caught:
        _plan({"problem_clusters_markdown": "两篇讲级联失效。"})
    assert caught.value.code == "THEME_OUTPUT_EMPTY"
    assert "actions" in str(caught.value)


def test_both_missing_fields_are_listed():
    with pytest.raises(ThemeError) as caught:
        _plan({})
    message = str(caught.value)
    assert "problem_clusters_markdown" in message and "actions" in message


def test_an_empty_clusters_text_is_still_rejected():
    with pytest.raises(ThemeError) as caught:
        _plan({"problem_clusters_markdown": "   ", "actions": []})
    assert caught.value.code == "THEME_OUTPUT_EMPTY"
