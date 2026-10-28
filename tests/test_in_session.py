"""Behaviour of the file-based, two-phase runner.

The platform never calls a model in this mode: ``prepare`` writes a directory,
an external agent writes ``response.json``, and ``finalize`` verifies the wire
contract before the ordinary grounding and draft path runs. These tests use the
real converter and cache (no model), so a green result means the staged paper,
the digest echo and the canary echo were all checked for real.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydrolitagent.cards.adapters.pdf.pymupdf_converter import PymupdfConverter
from hydrolitagent.cards.adapters.runners.in_session import (
    AWAITING_SESSION_OUTPUT,
    InSessionRunner,
)
from hydrolitagent.cards.adapters.storage.paper_store import PaperStore
from hydrolitagent.cards.application.card_workflow import (
    finalize_session_run,
    prepare_session_run,
)
from hydrolitagent.cards.domain.grounding import expected_canaries, markdown_sha256
from hydrolitagent.cards.domain.paper import SourceIdentity
from hydrolitagent.cards.domain.source_access import MARKDOWN_PREPARED
from hydrolitagent.cards.ports.paper import ConversionOptions
from hydrolitagent.cards.ports.runner import CardRunRequest

from test_markdown_workflow import (  # noqa: F401 - imported fixture
    _record,
    _write_pdf,
    app_config,
    grounded_output,
)


def _pipeline(tmp_path: Path) -> dict:
    return {
        "converter": PymupdfConverter(),
        "store": PaperStore(tmp_path / "cache"),
        "runner": InSessionRunner(),
        "options": ConversionOptions(),
    }


def _prepare(app_config, record, tmp_path: Path, run_dir: Path) -> dict:
    return prepare_session_run(
        app_config,
        record,
        run_dir=run_dir,
        output_root=tmp_path / "literature",
        **_pipeline(tmp_path),
    )


def _staged_request(run_dir: Path) -> SimpleNamespace:
    """A stand-in for ``CardRunRequest`` accepted by the test response builder."""

    payload = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    return SimpleNamespace(
        workspace=run_dir,
        paper=SimpleNamespace(page_count=payload["page_count"]),
    )


def _write_response(run_dir: Path, response: dict) -> None:
    (run_dir / "response.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _finalize(app_config, record, tmp_path: Path, run_dir: Path) -> dict:
    return finalize_session_run(
        app_config,
        record,
        run_dir=run_dir,
        output_root=tmp_path / "literature",
        **_pipeline(tmp_path),
    )


def _drafts(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "literature").rglob("draft.json"))


# --------------------------------------------------------------------------------------
# phase 1: prepare
# --------------------------------------------------------------------------------------


def test_prepare_writes_a_complete_run_directory_without_calling_a_model(
    app_config, tmp_path
):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    run_dir = tmp_path / "run1"

    result = _prepare(app_config, _record(pdf), tmp_path, run_dir)

    assert result["ok"], result
    assert result["status"] == "AWAITING_SESSION_OUTPUT"
    assert result["model_invoked"] is False
    for name in ("paper.md", "request.json", "output.schema.json", "README.md"):
        assert (run_dir / name).is_file(), name
    assert (run_dir / "figures").is_dir()
    assert not (run_dir / "response.json").exists()
    assert not any(path.suffix.lower() == ".pdf" for path in run_dir.rglob("*"))

    markdown = (run_dir / "paper.md").read_text(encoding="utf-8")
    payload = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    assert payload["markdown_sha256"] == markdown_sha256(markdown)
    assert payload["reading_canaries"] == list(expected_canaries(markdown))
    assert payload["page_count"] == 3
    assert payload["outline"], payload
    assert all({"page", "heading", "role"} <= set(item) for item in payload["outline"])
    assert payload["response_file"] == "response.json"
    assert payload["output_schema_file"] == "output.schema.json"
    assert payload["prompt"] and payload["source_pdf_sha256"]
    assert result["canaries"] == payload["reading_canaries"]
    assert Path(result["schema_path"]).is_file()
    assert Path(result["instructions_path"]).is_file()


def test_prepare_failure_is_structured_when_the_run_dir_is_a_file(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    run_dir = tmp_path / "run1"
    run_dir.write_text("not a directory", encoding="utf-8")

    result = _prepare(app_config, _record(pdf), tmp_path, run_dir)

    assert result["ok"] is False
    assert result["error"]["code"] == "IN_SESSION_RUN_DIR_INVALID"
    assert result["failed_stage"] == "workspace"
    assert result["error"]["diagnostic"]["run_dir"] == str(run_dir)


# --------------------------------------------------------------------------------------
# phase 2: finalize
# --------------------------------------------------------------------------------------


def test_finalize_turns_a_grounded_response_into_a_draft(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    record = _record(pdf)
    run_dir = tmp_path / "run1"
    assert _prepare(app_config, record, tmp_path, run_dir)["ok"]
    _write_response(run_dir, grounded_output(_staged_request(run_dir)))

    result = _finalize(app_config, record, tmp_path, run_dir)

    assert result["ok"], result
    assert result["status"] == "DRAFT_PENDING_VALIDATION"
    assert result["model_invoked"] is False
    assert result["reading_status"] == "VERIFIED"
    assert result["runner_id"] == "in_session"

    drafts = _drafts(tmp_path)
    assert len(drafts) == 1
    draft = json.loads(drafts[0].read_text(encoding="utf-8"))
    assert draft["pipeline"] == "markdown"
    assert draft["source_access"]["method"] == MARKDOWN_PREPARED
    assert draft["source_access"]["reading"]["verified"] is True
    assert draft["source_access"]["reading"]["canaries_ok"] is True
    assert draft["provenance"]["runner_id"] == "in_session"
    # The platform did not call a model; the draft must not imply otherwise.
    assert draft["process_audit"]["model_invoked"] is False


def test_finalize_keeps_the_prepared_run_identity_in_the_draft(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    record = _record(pdf)
    run_dir = tmp_path / "run1"
    assert _prepare(app_config, record, tmp_path, run_dir)["ok"]
    request_payload = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    _write_response(run_dir, grounded_output(_staged_request(run_dir)))

    result = _finalize(app_config, record, tmp_path, run_dir)

    assert result["ok"], result
    draft = json.loads(_drafts(tmp_path)[0].read_text(encoding="utf-8"))
    # The draft points back to the directory the agent actually read.
    assert draft["draft_id"] == request_payload["run_id"]
    assert draft["provenance"]["combined_prompt_sha256"]
    assert draft["source_access"]["markdown_sha256"] == request_payload["markdown_sha256"]


def test_finalize_rejects_a_run_directory_prepared_for_another_paper(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    record = _record(pdf)
    run_dir = tmp_path / "run1"
    assert _prepare(app_config, record, tmp_path, run_dir)["ok"]
    payload = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    payload["markdown_sha256"] = "0" * 64
    (run_dir / "request.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    result = _finalize(app_config, record, tmp_path, run_dir)

    assert result["ok"] is False
    assert result["error"]["code"] == "MARKDOWN_SHA_MISMATCH"
    assert result["failed_stage"] == "generation"
    assert _drafts(tmp_path) == []


def test_finalize_rejects_a_response_without_a_markdown_digest(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    record = _record(pdf)
    run_dir = tmp_path / "run1"
    assert _prepare(app_config, record, tmp_path, run_dir)["ok"]
    response = grounded_output(_staged_request(run_dir))
    response["reading_receipt"].pop("markdown_sha256")
    _write_response(run_dir, response)

    result = _finalize(app_config, record, tmp_path, run_dir)

    assert result["ok"] is False
    assert result["error"]["code"] == "IN_SESSION_MARKDOWN_SHA_MISSING"
    assert result["failed_stage"] == "generation"
    assert _drafts(tmp_path) == []
    # The unvalidated answer is kept for inspection.
    assert (run_dir / "response.json").is_file()
    assert result["error"]["diagnostic"]["response_path"].endswith("response.json")


def test_finalize_rejects_a_response_missing_a_canary(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    record = _record(pdf)
    run_dir = tmp_path / "run1"
    assert _prepare(app_config, record, tmp_path, run_dir)["ok"]
    response = grounded_output(_staged_request(run_dir))
    receipt = dict(response["reading_receipt"])
    receipt["canaries_seen"] = receipt["canaries_seen"][:-1]
    response["reading_receipt"] = receipt
    _write_response(run_dir, response)

    result = _finalize(app_config, record, tmp_path, run_dir)

    assert result["ok"] is False
    assert result["error"]["code"] == "IN_SESSION_CANARY_MISSING"
    assert _drafts(tmp_path) == []


def test_finalize_reports_a_missing_response_without_a_traceback(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    record = _record(pdf)
    run_dir = tmp_path / "run1"
    assert _prepare(app_config, record, tmp_path, run_dir)["ok"]

    result = _finalize(app_config, record, tmp_path, run_dir)

    assert result["ok"] is False
    assert result["error"]["code"] == "IN_SESSION_RESPONSE_MISSING"
    assert _drafts(tmp_path) == []


# --------------------------------------------------------------------------------------
# run(): neither phase invokes a model
# --------------------------------------------------------------------------------------


def _prepared_paper(pdf: Path, record: dict, tmp_path: Path):
    return PaperStore(tmp_path / "cache").get_or_prepare(
        pdf,
        source=SourceIdentity(
            pdf_sha256=record["pdf"]["sha256"],
            size_bytes=record["pdf"]["file_size_bytes"],
            page_count=3,
            parent_key=record["item"]["item_key"],
            attachment_key=record["pdf"]["attachment_key"],
        ),
        converter=PymupdfConverter(),
        options=ConversionOptions(),
    )


def test_run_awaits_session_output_and_never_invokes_a_model(app_config, tmp_path):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    record = _record(pdf)
    run_dir = tmp_path / "run1"
    assert _prepare(app_config, record, tmp_path, run_dir)["ok"]

    paper = _prepared_paper(pdf, record, tmp_path)
    request = CardRunRequest(
        run_id="session-run",
        paper=paper,
        prompt="read the staged paper",
        output_schema={"type": "object"},
        workspace=run_dir,
        timeout_seconds=5,
    )
    runner = InSessionRunner()

    waiting = runner.run(request)
    assert waiting.ok is False
    assert waiting.error is not None
    assert waiting.error.code == AWAITING_SESSION_OUTPUT
    assert waiting.model_invoked is False

    _write_response(run_dir, grounded_output(SimpleNamespace(workspace=run_dir, paper=paper)))
    finalized = runner.run(request)
    assert finalized.ok is True
    assert finalized.model_invoked is False
    assert finalized.runner_id == "in_session"
    assert finalized.unvalidated_output_path == str(run_dir / "response.json")


if __name__ == "__main__":  # pragma: no cover - manual invocation convenience
    raise SystemExit(pytest.main([__file__]))
