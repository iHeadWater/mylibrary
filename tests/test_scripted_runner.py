"""Behaviour of the deterministic test runner.

``ScriptedRunner`` is the third implementation of ``ports.runner.CardRunner``
(alongside ``in_session`` and ``direct``). It must answer the same request shape
without a process, a network call or a key, so the workflow tests exercise the
real contract instead of a mock objects package.
"""
from __future__ import annotations

from pathlib import Path

from hydrolitagent.cards.adapters.runners.scripted import ScriptedRunner
from hydrolitagent.cards.domain.paper import (
    MARKDOWN_FILENAME,
    PageAnchor,
    PreparedPaper,
    SourceIdentity,
)
from hydrolitagent.cards.ports.runner import CardRunError, CardRunRequest

MARKDOWN = (
    "<!-- page: 1 -->\n"
    "<!-- reading-canary: c-00000001 -->\n"
    "# A study of runoff\n\n"
    "We find that the proposed model reduces peak error by 18 percent overall.\n"
)

ANSWER = {"schema_version": 2, "card_body_markdown": "# Fixture card\n"}


def request_for(tmp_path: Path) -> CardRunRequest:
    import hashlib

    store = tmp_path / "store"
    store.mkdir(parents=True, exist_ok=True)
    markdown_path = store / MARKDOWN_FILENAME
    markdown_path.write_text(MARKDOWN, encoding="utf-8")
    paper = PreparedPaper(
        source=SourceIdentity(
            pdf_sha256="a" * 64, size_bytes=10, page_count=1, parent_key="PARENT01"
        ),
        markdown_path=markdown_path,
        markdown_sha256=hashlib.sha256(MARKDOWN.encode("utf-8")).hexdigest(),
        manifest_path=store / "manifest.json",
        page_anchors=(
            PageAnchor(
                page=1,
                char_start=0,
                char_end=len(MARKDOWN),
                heading="A study of runoff",
                role="body",
                canary="c-00000001",
            ),
        ),
        figures=(),
        converter_id="pymupdf",
        converter_version="test",
        text_coverage=1.0,
        warnings=(),
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / MARKDOWN_FILENAME).write_text(MARKDOWN, encoding="utf-8")
    return CardRunRequest(
        run_id="run-1",
        paper=paper,
        prompt="read paper.md and answer",
        output_schema={"type": "object"},
        workspace=workspace,
        timeout_seconds=5,
        model=None,
        reasoning_effort=None,
    )


def test_it_replays_the_preset_answer_and_records_the_request(tmp_path):
    runner = ScriptedRunner(ANSWER)

    result = runner.run(request_for(tmp_path))

    assert result.ok is True
    assert result.runner_id == "scripted"
    assert result.output == ANSWER
    assert result.model_invoked is True
    assert len(runner.requests) == 1
    # The request carries a prepared paper, never a PDF path.
    assert runner.requests[0].paper is not None


def test_the_answer_is_copied_so_a_caller_cannot_mutate_the_preset(tmp_path):
    runner = ScriptedRunner(ANSWER)

    result = runner.run(request_for(tmp_path))
    result.output["mutated"] = True

    assert "mutated" not in runner.output


def test_it_can_return_a_structured_failure(tmp_path):
    runner = ScriptedRunner(ok=False, error=CardRunError("SCRIPTED_FAILED", "预设失败"))

    result = runner.run(request_for(tmp_path))

    assert result.ok is False
    assert result.error.code == "SCRIPTED_FAILED"
    assert result.model_invoked is True


def test_a_runner_without_a_preset_answer_fails_closed(tmp_path):
    runner = ScriptedRunner(None)

    result = runner.run(request_for(tmp_path))

    assert result.ok is False
    assert result.error.code == "SCRIPTED_RUNNER_OUTPUT_MISSING"


def test_doctor_needs_no_external_program():
    doctor = ScriptedRunner(ANSWER).doctor()

    assert doctor.runner_id == "scripted"
    assert doctor.available is True
