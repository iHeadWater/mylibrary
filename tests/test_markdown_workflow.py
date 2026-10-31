"""End-to-end behaviour of the Markdown-first single-paper workflow.

The tests convert a real (generated) PDF with the real converter and cache, then
hand the prepared paper to a scripted runner. No model is invoked. The scripted
answers are built *from the produced* ``paper.md`` so a passing test means the
grounding gate accepted genuine quotes, not that the fixture knew the answer.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest

from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.adapters.pdf.pymupdf_converter import PymupdfConverter
from hydrolitagent.cards.adapters.storage.paper_store import PaperStore
from hydrolitagent.cards.adapters.runners.scripted import ScriptedRunner
from hydrolitagent.cards.application.card_workflow import generate_markdown_card_draft
from hydrolitagent.cards.config import load_config
from hydrolitagent.cards.domain.grounding import expected_canaries, markdown_sha256
from hydrolitagent.cards.domain.source_access import MARKDOWN_PREPARED
from hydrolitagent.cards.ports.runner import CardRunError

from test_config import write_config

PARENT_KEY = "PARENT01"
ATTACHMENT_KEY = "ATTACH01"
TEMPLATE_ID = "original-research"

PAGE_WIDTH = 595
PAGE_HEIGHT = 842
BODY = (
    "Rainfall-runoff processes in small catchments are controlled by soil moisture, "
    "storm intensity and antecedent conditions. This study combines field observations "
    "with a simple bucket model to quantify those controls over three seasons. "
)

PAGE_PATTERN = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")


# --------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------


def _write_pdf(path: Path, *, text: bool = True) -> Path:
    doc = pymupdf.open()
    # Each page must be filled right after it is created: PyMuPDF invalidates a
    # Page object once the document grows a new page.
    first = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    if text:
        first.insert_text((72, 90), "Rainfall-Runoff Controls in Small Catchments", fontsize=18)
        first.insert_text((72, 130), "Abstract", fontsize=14)
        first.insert_textbox(pymupdf.Rect(72, 145, 523, 385), BODY * 2, fontsize=10)
    second = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    if text:
        second.insert_text((72, 90), "Introduction", fontsize=14)
        second.insert_textbox(pymupdf.Rect(72, 105, 523, 345), BODY * 3, fontsize=10)
    third = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    if text:
        third.insert_text((72, 90), "References", fontsize=14)
        third.insert_textbox(
            pymupdf.Rect(72, 105, 523, 345),
            "Anderson, M. G. (2020). Hydrology in practice. Journal of Hydrology. " * 3,
            fontsize=9,
        )
    doc.save(str(path))
    doc.close()
    return path


def _record(pdf: Path) -> dict:
    return {
        "schema_version": 1,
        "ok": True,
        "operation": "paper_input",
        "status": "READY",
        "reason_code": "PDF_READY",
        "library": {"type": "user", "id": 0},
        "requested_item_key": ATTACHMENT_KEY,
        "item": {"item_key": PARENT_KEY, "title": "Fixed Markdown fixture paper"},
        "pdf_attachment_count": 1,
        "pdf": {
            "attachment_key": ATTACHMENT_KEY,
            "parent_key": PARENT_KEY,
            "file_size_bytes": pdf.stat().st_size,
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "local_path": str(pdf.resolve()),
            "fulltext_indexed": False,
        },
    }


@pytest.fixture
def app_config(tmp_path):
    base = load_config(write_config(tmp_path / "app", {"zotero": {"group_id": None}}))
    assets = {
        "evidence_card_templates_dir": ASSETS_DIR / "templates/evidence-cards",
        "evidence_card_template_catalog_file": ASSETS_DIR / "templates/evidence-cards/_catalog.json",
        "evidence_card_generation_prompt_file": ASSETS_DIR / "prompts/evidence-card-generation-v8.md",
    }
    return replace(
        base,
        card_generator=replace(
            base.card_generator,
            runtime_dir=tmp_path / "runtime",
            generation_timeout_seconds=5,
            model=None,
            reasoning_effort=None,
        ),
        paths=replace(base.paths, **assets),
    )


class WorkspaceRunner(ScriptedRunner):
    """Scripted runner whose answer is derived from the staged Markdown."""

    def __init__(self, builder):
        super().__init__()
        self.builder = builder

    def run(self, request):
        self.output = self.builder(request)
        return super().run(request)


def _sequence(*builders):
    """Answer with the first builder, then the second, then keep the last."""

    state = {"index": 0}

    def builder(request):
        chosen = builders[min(state["index"], len(builders) - 1)]
        state["index"] += 1
        return chosen(request)

    return builder


def page_section(markdown: str, number: int) -> str:
    markers = list(PAGE_PATTERN.finditer(markdown))
    selected = next(marker for marker in markers if int(marker.group(1)) == number)
    later = [marker for marker in markers if marker.start() > selected.start()]
    end = later[0].start() if later else len(markdown)
    return markdown[selected.end():end]


def first_prose_quote(markdown: str, number: int) -> str:
    for line in page_section(markdown, number).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("<!--"):
            continue
        if len(stripped) >= 40:
            return stripped
    raise AssertionError(f"第 {number} 页没有足够长的正文可用于 fixture 引文")


def machine_fields(quote_page: int) -> dict:
    statement = {
        "statement": "Synthetic fixture result; not a scientific claim.",
        "statement_role": "original_statement",
        "information_status": "reported",
        "source_locations": [
            {"pdf_page": quote_page, "section": None, "figure": None, "table": None}
        ],
    }
    fields = {"schema_version": 1}
    for key in (
        "research_questions",
        "study_objects_and_scales",
        "data_and_methods",
        "comparison_baselines",
        "findings",
        "boundaries",
        "missing_information",
    ):
        fields[key] = [deepcopy(statement)]
    fields["findings"][0]["finding_id"] = "F001"
    return fields


def grounded_output(request, *, quote_page: int = 2, locations=None, **overrides) -> dict:
    markdown = (Path(request.workspace) / "paper.md").read_text(encoding="utf-8")
    if locations is None:
        # A reading has to cover the pages that carry prose, so the default
        # answer quotes the abstract page as well as the body page it is about.
        locations = [
            {
                "anchor": f"P{page}",
                "quote": first_prose_quote(markdown, page),
                "pdf_page": page,
                "section": None,
                "figure": None,
                "table": None,
            }
            for page in dict.fromkeys((1, quote_page))
        ]
    output = {
        "schema_version": 2,
        "source_read_status": "FULL_PDF_REVIEWED",
        "source_page_count": request.paper.page_count,
        "visual_content_status": "NOT_PRESENT",
        "source_read_evidence": "Read paper.md pages 1-3 in full; no figures in this fixture.",
        "template_id": TEMPLATE_ID,
        "classification_confidence": 0.9,
        "classification_reason": "fixture",
        "card_body_markdown": (
            f"# Fixed Markdown fixture paper\n\nfixture result（第 {quote_page} 页）.\n"
        ),
        "machine_fields": machine_fields(quote_page),
        "reading_receipt": {
            "markdown_sha256": markdown_sha256(markdown),
            "read_mode": "file",
            "model_claimed_status": "FULL_MARKDOWN_REVIEWED",
            "model_claimed_pages": list(range(1, request.paper.page_count + 1)),
            "canaries_seen": list(expected_canaries(markdown)),
            "self_report": "fixture read the whole Markdown",
        },
        "source_locations": locations,
    }
    output.update(overrides)
    return output


def run_workflow(
    app_config, record, runner, *, converter=None, store=None, tmp_path=None, **kwargs
):
    converter = converter or PymupdfConverter()
    store = store or PaperStore(tmp_path / "cache")
    return generate_markdown_card_draft(
        app_config,
        record,
        converter=converter,
        store=store,
        runner=runner,
        output_root=tmp_path / "literature",
        **kwargs,
    )


def draft_paths(result) -> list[Path]:
    return sorted(Path(result["literature_root"]).rglob("draft.json"))


# --------------------------------------------------------------------------------------
# happy path
# --------------------------------------------------------------------------------------


def test_markdown_pipeline_saves_a_grounded_unvalidated_draft(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    runner = WorkspaceRunner(grounded_output)

    result = run_workflow(app_config, _record(pdf), runner, tmp_path=tmp_path)

    assert result["ok"], result
    assert result["status"] == "DRAFT_PENDING_VALIDATION"
    assert result["pipeline"] == "markdown"
    assert result["model_invoked"] is True
    assert result["reading_status"] == "VERIFIED"
    assert result["production_eligible"] is False

    drafts = draft_paths(result)
    assert len(drafts) == 1
    draft = json.loads(drafts[0].read_text(encoding="utf-8"))
    assert draft["schema_version"] == 2
    assert draft["pipeline"] == "markdown"
    assert draft["status"] == "DRAFT_PENDING_VALIDATION"
    assert draft["content_validation_performed"] is False
    assert draft["scientific_correctness_verified"] is False

    access = draft["source_access"]
    assert access["method"] == MARKDOWN_PREPARED
    assert access["page_count"] == 3
    assert access["converter_id"] == "pymupdf"
    assert access["source_pdf_sha256"] == _record(pdf)["pdf"]["sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", access["markdown_sha256"])
    reading = access["reading"]
    assert reading["verified"] is True
    assert reading["canaries_ok"] is True
    assert reading["full_read_verified"] is True
    assert reading["scientific_correctness_verified"] is False
    # Page 1 carries the abstract, page 2 the body; page 3 is a reference list
    # and does not count towards coverage.
    assert reading["verified_pages"] == [1, 2]
    assert reading["quote_coverage"] == 1.0
    # The legacy reader field must carry the same receipt.
    assert draft["reading_record"] == access

    gates = draft["process_audit"]["gates"]
    assert gates["markdown_grounded"] is True
    assert gates["content_validation_performed"] is False
    assert gates["scientific_correctness_verified"] is False
    assert draft["provenance"]["runner_id"] == "scripted"
    assert draft["provenance"]["converter_version"]

    card = drafts[0].parent / "card.md"
    assert card.read_text(encoding="utf-8").startswith("> 待校验主体卡草稿")
    # The staged copy is disposable once the draft exists.
    leftovers = list((tmp_path / "runtime").glob("markdown-*"))
    assert leftovers == []


def test_runner_request_carries_no_pdf_path(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    captured = {}

    def builder(request):
        # Read the staged request while the workspace still exists: a successful
        # run deletes it right after the draft is saved.
        captured["request_json"] = (
            Path(request.workspace) / "request.json"
        ).read_text(encoding="utf-8")
        captured["request"] = request
        return grounded_output(request)

    result = run_workflow(app_config, _record(pdf), WorkspaceRunner(builder), tmp_path=tmp_path)

    assert result["ok"], result
    request = captured["request"]
    assert str(pdf.resolve()) not in request.prompt
    assert str(pdf) not in request.prompt
    assert not re.search(r"\.pdf\b", request.prompt, re.IGNORECASE)
    assert not re.search(r"\.pdf\b", captured["request_json"], re.IGNORECASE)
    assert request.paper.source.pdf_sha256 == _record(pdf)["pdf"]["sha256"]
    assert not hasattr(request.paper, "pdf_path")


def test_workspace_contains_only_prepared_material(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")

    def builder(request):
        # An empty quote list fails grounding, so the workspace is kept and can
        # be inspected exactly as the runner saw it.
        return {**grounded_output(request), "source_locations": []}

    result = run_workflow(app_config, _record(pdf), WorkspaceRunner(builder), tmp_path=tmp_path)

    assert not result["ok"]
    assert result["error"]["code"] == "QUOTE_NOT_FOUND"
    workspace = Path(result["error"]["diagnostic"]["workspace"])
    names = sorted(path.name for path in workspace.rglob("*") if path.is_file())
    assert "paper.md" in names
    assert "request.json" in names
    assert "output.schema.json" in names
    assert not any(name.lower().endswith(".pdf") for name in names)


# --------------------------------------------------------------------------------------
# fail-closed paths
# --------------------------------------------------------------------------------------


def _no_drafts(tmp_path: Path) -> bool:
    return not list((tmp_path / "literature").rglob("draft.json"))


def test_fabricated_quote_is_rejected_and_nothing_is_saved(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")

    def builder(request):
        return grounded_output(
            request,
            locations=[
                {
                    "anchor": "P2",
                    "quote": "Peak error fell by 92 percent under every tested scenario.",
                    "pdf_page": 2,
                    "section": None,
                    "figure": None,
                    "table": None,
                }
            ],
        )

    result = run_workflow(app_config, _record(pdf), WorkspaceRunner(builder), tmp_path=tmp_path)

    assert result["ok"] is False
    assert result["error"]["code"] == "QUOTE_NOT_FOUND"
    assert result["failed_stage"] == "grounding"
    assert _no_drafts(tmp_path)


def test_missing_canary_is_rejected(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")

    def builder(request):
        output = grounded_output(request)
        receipt = dict(output["reading_receipt"])
        receipt["canaries_seen"] = receipt["canaries_seen"][:-1]
        return {**output, "reading_receipt": receipt}

    result = run_workflow(app_config, _record(pdf), WorkspaceRunner(builder), tmp_path=tmp_path)

    assert result["ok"] is False
    assert result["error"]["code"] == "INCOMPLETE_MARKDOWN_READ"
    assert _no_drafts(tmp_path)


def test_a_reading_that_covers_too_few_pages_is_rejected(app_config, tmp_path):
    """Coverage is a requirement of the card, not a note attached to it."""

    pdf = _write_pdf(tmp_path / "paper.pdf")

    def builder(request):
        return grounded_output(request, quote_page=1)

    result = run_workflow(app_config, _record(pdf), WorkspaceRunner(builder), tmp_path=tmp_path)

    assert result["ok"] is False
    assert result["error"]["code"] == "CARD_READING_NOT_VERIFIED"
    assert result["failed_stage"] in ("validation", "grounding")
    coverage = result["error"]["diagnostic"]["coverage"]
    assert coverage["satisfied"] is False
    assert coverage["missing_pages"] == [2]
    assert _no_drafts(tmp_path)


def test_runner_failure_is_reported_without_a_draft(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    runner = ScriptedRunner(
        ok=False, error=CardRunError("MARKDOWN_RUNNER_TIMEOUT", "runner 调用超时")
    )

    result = run_workflow(app_config, _record(pdf), runner, tmp_path=tmp_path)

    assert result["ok"] is False
    # The call reached the runner, so it did invoke the model; the failure is a
    # timeout, not a "never started" error.
    assert result["model_invoked"] is True
    assert result["error"]["code"] == "MARKDOWN_RUNNER_TIMEOUT"
    assert _no_drafts(tmp_path)


class FlakyRunner(WorkspaceRunner):
    """Fails the first ``failures`` calls, then answers normally."""

    def __init__(self, builder, *, failures, code="RUNNER_OUTPUT_INVALID"):
        super().__init__(builder)
        self.failures = failures
        self.code = code

    def run(self, request):
        if self.failures > 0:
            self.failures -= 1
            self.ok = False
            self.error = CardRunError(self.code, "模型输出不是有效 JSON（制卡）")
            try:
                return super().run(request)
            finally:
                self.ok = True
        return super().run(request)


def test_a_truncated_answer_is_retried_instead_of_failing_the_paper(
    app_config, tmp_path
):
    """Nothing was learnt about the card, so asking again is not a repair."""

    pdf = _write_pdf(tmp_path / "paper.pdf")
    runner = FlakyRunner(grounded_output, failures=1)

    result = run_workflow(app_config, _record(pdf), runner, tmp_path=tmp_path)

    assert result["ok"], result
    assert [attempt["ok"] for attempt in result["attempts"]] == [False, True]
    assert result["attempts"][0]["error_code"] == "RUNNER_OUTPUT_INVALID"
    assert len(runner.requests) == 2
    # The retry asks for the same task again, and says how to make it usable.
    assert "只输出一个完整的 JSON 对象" in runner.requests[1].prompt
    assert len(draft_paths(result)) == 1


def test_transient_retries_are_capped(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    runner = FlakyRunner(grounded_output, failures=9)

    result = run_workflow(app_config, _record(pdf), runner, tmp_path=tmp_path)

    assert result["ok"] is False
    assert result["error"]["code"] == "RUNNER_OUTPUT_INVALID"
    # One call plus two retries, then the run stops instead of burning the night.
    assert len(runner.requests) == 3
    assert len(result["attempts"]) == 3
    assert _no_drafts(tmp_path)


def test_a_rejected_key_is_not_retried(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    runner = FlakyRunner(grounded_output, failures=1, code="RUNNER_AUTH_FAILED")

    result = run_workflow(app_config, _record(pdf), runner, tmp_path=tmp_path)

    assert result["ok"] is False
    assert result["error"]["code"] == "RUNNER_AUTH_FAILED"
    assert len(runner.requests) == 1


def test_conversion_failure_never_calls_the_runner(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "scanned.pdf", text=False)
    runner = ScriptedRunner({})

    result = run_workflow(app_config, _record(pdf), runner, tmp_path=tmp_path)

    assert result["ok"] is False
    assert result["error"]["code"] == "CONVERTER_LOW_TEXT"
    assert result["model_invoked"] is False
    assert runner.requests == []


def test_grounding_and_wire_problems_are_reported_together(app_config, tmp_path):
    """One failing answer, one list: a quote problem must not hide a shape problem.

    The repair step gets a single budget, so discovering the machine-field
    mistakes only after fixing the quote would waste a whole round.
    """
    pdf = _write_pdf(tmp_path / "paper.pdf")

    def builder(request):
        output = grounded_output(request)
        output["source_locations"] = [
            {
                "anchor": "P2",
                "quote": "Peak error fell by 92 percent under every tested scenario.",
                "pdf_page": 2,
                "section": None,
                "figure": None,
                "table": None,
            }
        ]
        # A required protocol key is missing; nothing outside the schema is used.
        output["machine_fields"].pop("boundaries")
        return output

    result = run_workflow(
        app_config, _record(pdf), WorkspaceRunner(builder), tmp_path=tmp_path
    )

    assert result["ok"] is False
    assert result["failed_stage"] == "grounding"
    diagnostic = result["error"]["diagnostic"]
    codes = [item["code"] for item in diagnostic["violations"]]
    paths = [item["path"] for item in diagnostic["violations"]]
    assert "QUOTE_NOT_FOUND" in codes
    assert "CARD_DRAFT_OUTPUT_INVALID" in codes
    assert "source_locations[0]" in paths
    assert "machine_fields.boundaries" in paths
    # The contract and the coverage shortfall travel with the rejection.
    assert "findings" in diagnostic["machine_fields_contract"]
    assert diagnostic["coverage"]["failed_quotes"] == 1
    assert diagnostic["coverage"]["satisfied"] is False
    assert _no_drafts(tmp_path)


def test_model_page_count_must_match_the_prepared_pages(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")

    def builder(request):
        return grounded_output(request, source_page_count=99)

    result = run_workflow(app_config, _record(pdf), WorkspaceRunner(builder), tmp_path=tmp_path)

    assert result["ok"] is False
    assert result["error"]["code"] == "MARKDOWN_PAGE_COUNT_MISMATCH"


# --------------------------------------------------------------------------------------
# repair loop (#32)
# --------------------------------------------------------------------------------------


def _broken_wire(request):
    output = grounded_output(request)
    output["machine_fields"].pop("boundaries")
    return output


def test_a_rejected_answer_is_handed_back_and_the_second_attempt_is_saved(
    app_config, tmp_path
):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    runner = WorkspaceRunner(_sequence(_broken_wire, grounded_output))

    result = run_workflow(app_config, _record(pdf), runner, tmp_path=tmp_path)

    assert result["ok"], result
    assert [attempt["ok"] for attempt in result["attempts"]] == [False, True]
    first, second = result["attempts"]
    assert first["error_code"] == "CARD_DRAFT_OUTPUT_INVALID"
    assert any(
        violation["path"] == "machine_fields.boundaries"
        for violation in first["violations"]
    )
    assert second["violations"] == []
    assert len(draft_paths(result)) == 1


def test_repair_stops_at_the_cap_and_saves_nothing(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    runner = WorkspaceRunner(_broken_wire)

    result = run_workflow(
        app_config, _record(pdf), runner, tmp_path=tmp_path, max_repairs=1
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "CARD_DRAFT_OUTPUT_INVALID"
    assert [attempt["ok"] for attempt in result["attempts"]] == [False, False]
    assert all(attempt["violation_count"] > 0 for attempt in result["attempts"])
    assert _no_drafts(tmp_path)


def test_the_repair_prompt_carries_the_previous_answer_and_the_contract(
    app_config, tmp_path
):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    runner = WorkspaceRunner(_sequence(_broken_wire, grounded_output))

    result = run_workflow(app_config, _record(pdf), runner, tmp_path=tmp_path)

    assert result["ok"], result
    repair_prompt = runner.requests[1].prompt
    # The task itself is unchanged: the base prompt is still the prefix.
    assert repair_prompt.startswith(runner.requests[0].prompt.rstrip())
    assert "上一次的回答" in repair_prompt
    assert "machine_fields.boundaries" in repair_prompt
    # The contract is quoted from the schema, so the model sees the key names.
    assert "research_questions" in repair_prompt
    assert "missing_information" in repair_prompt


def test_repair_does_not_loosen_grounding(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")

    def invented_quote(request):
        return grounded_output(
            request,
            locations=[
                {
                    "anchor": "P2",
                    "quote": (
                        "For a storm event with average rainfall of R 561 mm the model "
                        "overestimated peak flow by 40 percent."
                    ),
                    "pdf_page": 2,
                    "section": None,
                    "figure": None,
                    "table": None,
                }
            ],
        )

    runner = WorkspaceRunner(invented_quote)
    result = run_workflow(
        app_config, _record(pdf), runner, tmp_path=tmp_path, max_repairs=2
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "QUOTE_NOT_FOUND"
    # Every attempt was rejected by the same gate; nothing was waved through.
    assert all(attempt["ok"] is False for attempt in result["attempts"])
    assert len(result["attempts"]) == 3
    assert _no_drafts(tmp_path)


def test_the_repair_prompt_quotes_back_the_rejected_text(app_config, tmp_path):
    """A rejected quote must come back verbatim, with "do not paraphrase"."""

    pdf = _write_pdf(tmp_path / "paper.pdf")
    invented = (
        "For a storm event with average rainfall of R 561 mm the model "
        "overestimated peak flow by 40 percent."
    )

    def bad_quote(request):
        return grounded_output(
            request,
            locations=[
                {
                    "anchor": "P2",
                    "quote": invented,
                    "pdf_page": 2,
                    "section": None,
                    "figure": None,
                    "table": None,
                }
            ],
        )

    runner = WorkspaceRunner(_sequence(bad_quote, grounded_output))
    result = run_workflow(app_config, _record(pdf), runner, tmp_path=tmp_path)

    assert result["ok"], result
    repair_prompt = runner.requests[1].prompt
    assert "average rainfall of R 561 mm" in repair_prompt
    assert "不要改写之后继续用" in repair_prompt


def _uncited_body(request):
    """A verified reading whose body points at no page: validator-only failure."""

    output = grounded_output(request)
    output["card_body_markdown"] = "# Fixed paper\n\n本文给出了结果，但没有标注页码。\n"
    return output


def test_the_validator_is_part_of_the_repair_loop(app_config, tmp_path):
    """A card that grounds every quote can still fail evidence-validate.

    The body must point at pages the program verified; that rule lives in the
    validator, not in the generation-time gate, so it has to be repairable too.
    """
    pdf = _write_pdf(tmp_path / "paper.pdf")
    runner = WorkspaceRunner(_sequence(_uncited_body, grounded_output))

    result = run_workflow(app_config, _record(pdf), runner, tmp_path=tmp_path)

    assert result["ok"], result
    first = result["attempts"][0]
    assert first["ok"] is False
    assert first["error_code"] == "CARD_PAGE_CITATION"
    assert any(
        "没有标注任何页码" in violation["message"]
        for violation in first["violations"]
    )
    assert [attempt["ok"] for attempt in result["attempts"]] == [False, True]
    assert len(draft_paths(result)) == 1


def test_validator_failures_stop_at_the_cap_too(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    runner = WorkspaceRunner(_uncited_body)

    result = run_workflow(
        app_config, _record(pdf), runner, tmp_path=tmp_path, max_repairs=1
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "CARD_PAGE_CITATION"
    assert result["failed_stage"] == "validation"
    assert [attempt["ok"] for attempt in result["attempts"]] == [False, False]
    assert _no_drafts(tmp_path)


def test_a_partial_reading_is_gated_too(app_config, tmp_path):
    """A short reading fails before a draft exists, so no half-card is saved."""

    pdf = _write_pdf(tmp_path / "paper.pdf")
    runner = WorkspaceRunner(lambda request: grounded_output(request, quote_page=1))

    result = run_workflow(app_config, _record(pdf), runner, tmp_path=tmp_path)

    assert result["ok"] is False
    assert result["error"]["code"] == "CARD_READING_NOT_VERIFIED"
    assert _no_drafts(tmp_path)


def test_max_repairs_zero_keeps_a_single_attempt(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    runner = WorkspaceRunner(_broken_wire)

    result = run_workflow(
        app_config, _record(pdf), runner, tmp_path=tmp_path, max_repairs=0
    )

    assert result["ok"] is False
    assert len(result["attempts"]) == 1
    assert len(runner.requests) == 1


def test_a_runner_failure_is_not_retried(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    runner = ScriptedRunner(
        ok=False, error=CardRunError("MARKDOWN_RUNNER_TIMEOUT", "runner 调用超时")
    )

    result = run_workflow(app_config, _record(pdf), runner, tmp_path=tmp_path)

    assert result["ok"] is False
    assert result["error"]["code"] == "MARKDOWN_RUNNER_TIMEOUT"
    assert len(runner.requests) == 1


def test_an_out_of_range_repair_budget_is_refused(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")

    with pytest.raises(ValueError):
        run_workflow(
            app_config,
            _record(pdf),
            WorkspaceRunner(grounded_output),
            tmp_path=tmp_path,
            max_repairs=99,
        )


# --------------------------------------------------------------------------------------
# preparation cache
# --------------------------------------------------------------------------------------


def test_the_same_pdf_is_converted_once(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    record = _record(pdf)

    class CountingConverter(PymupdfConverter):
        calls = 0

        def convert(self, request):
            CountingConverter.calls += 1
            return super().convert(request)

    converter = CountingConverter()
    store = PaperStore(tmp_path / "cache")
    for _ in range(2):
        result = run_workflow(
            app_config,
            record,
            WorkspaceRunner(grounded_output),
            converter=converter,
            store=store,
            tmp_path=tmp_path,
        )
        assert result["ok"], result
    assert CountingConverter.calls == 1
    assert len(draft_paths(result)) == 2
