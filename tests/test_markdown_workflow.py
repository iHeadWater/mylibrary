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
from hydrolitagent.cards.adapters.runners.markdown import ScriptedRunner
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
    quote = first_prose_quote(markdown, quote_page)
    if locations is None:
        locations = [
            {
                "anchor": f"P{quote_page}",
                "quote": quote,
                "pdf_page": quote_page,
                "section": None,
                "figure": None,
                "table": None,
            }
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
        "card_body_markdown": "# Fixed Markdown fixture paper\n\nF001: fixture result.\n",
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


def run_workflow(app_config, record, runner, *, converter=None, store=None, tmp_path=None):
    converter = converter or PymupdfConverter()
    store = store or PaperStore(tmp_path / "cache")
    return generate_markdown_card_draft(
        app_config,
        record,
        converter=converter,
        store=store,
        runner=runner,
        output_root=tmp_path / "literature",
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
    assert reading["verified_pages"] == [2]
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


def test_quotes_only_on_front_matter_save_a_partial_draft(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")

    def builder(request):
        return grounded_output(request, quote_page=1)

    result = run_workflow(app_config, _record(pdf), WorkspaceRunner(builder), tmp_path=tmp_path)

    assert result["ok"], result
    assert result["reading_status"] == "PARTIAL"
    draft = json.loads(draft_paths(result)[0].read_text(encoding="utf-8"))
    assert draft["source_access"]["reading"]["verified"] is False
    assert draft["source_access"]["reading"]["quote_coverage"] == 0.0
    assert "GROUNDING_COVERAGE_PARTIAL" in draft["warnings"]
    assert draft["production_eligible"] is False


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


def test_conversion_failure_never_calls_the_runner(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "scanned.pdf", text=False)
    runner = ScriptedRunner({})

    result = run_workflow(app_config, _record(pdf), runner, tmp_path=tmp_path)

    assert result["ok"] is False
    assert result["error"]["code"] == "CONVERTER_LOW_TEXT"
    assert result["model_invoked"] is False
    assert runner.requests == []


def test_model_page_count_must_match_the_prepared_pages(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")

    def builder(request):
        return grounded_output(request, source_page_count=99)

    result = run_workflow(app_config, _record(pdf), WorkspaceRunner(builder), tmp_path=tmp_path)

    assert result["ok"] is False
    assert result["error"]["code"] == "MARKDOWN_PAGE_COUNT_MISMATCH"


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


# --------------------------------------------------------------------------------------
# CLI switch stays hidden and legacy by default
# --------------------------------------------------------------------------------------


def test_pipeline_flag_is_hidden_and_legacy_is_the_default():
    from hydrolitagent.cards import cli

    parser = cli._parser()
    assert "--pipeline" not in parser.format_help()
    parsed = parser.parse_args(
        ["evidence-generate", "--paper-input", "input.json", "--pipeline", "markdown"]
    )
    assert parsed.pipeline == "markdown"
    default = parser.parse_args(["evidence-generate", "--paper-input", "input.json"])
    assert default.pipeline is None
