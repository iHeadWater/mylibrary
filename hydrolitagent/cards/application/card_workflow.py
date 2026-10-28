"""Orchestrate one Markdown-first subject-card draft.

Pipeline (every arrow is a port or a pure function):

    input record → prepare_paper → staged workspace → runner.run
                 → grounding.verify_reading → output validation → atomic save

The application layer owns the artifact shape: the ``source_access`` receipt,
the draft envelope, the provenance hashes and the append-only write. It never
converts a PDF itself, never calls a model directly and never decides which
concrete converter or runner is installed -- those arrive as ports.

Two entry points share the same preparation and completion halves:

* ``generate_markdown_card_draft`` -- one call for a runner that invokes a model;
* ``prepare_session_run`` / ``finalize_session_run`` -- the two-phase,
  file-based protocol for an agent the platform does not call.

A failure at any step means no draft on disk. There is no retry and no silent
downgrade of a hard grounding failure to a warning.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hydrolitagent._config import PathConfigError, resolve_literature_root
from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.application.prepare_paper import prepare_paper
from hydrolitagent.cards.application.workspace import (
    REQUEST_FILENAME,
    SCHEMA_FILENAME,
    runtime_dir,
    stage_paper_workspace,
)
from hydrolitagent.cards.application.card_draft import (
    SINGLE_SOURCE_TEMPLATES,
    check_wire,
    read_paper_input,
    save_draft,
)
from hydrolitagent.cards.application.prompts import (
    build_template_prompt,
    load_template_bundle,
    read_prompt,
)
from hydrolitagent.cards.domain.card_output import validate_model_output
from hydrolitagent.cards.domain.errors import CardGenerationError
from hydrolitagent.cards.domain.grounding import expected_canaries, verify_reading
from hydrolitagent.cards.domain.paper import FIGURES_DIRNAME, MARKDOWN_FILENAME, PreparedPaper
from hydrolitagent.cards.domain.protocol import MARKDOWN_CARD_PROTOCOL_VERSION
from hydrolitagent.cards.domain.reading import (
    GroundingError,
    ReadingReceipt,
    VerifiedReading,
)
from hydrolitagent.cards.domain.source_access import (
    MARKDOWN_PREPARED,
    source_access_acceptable,
)
from hydrolitagent.cards.evidence_templates import EvidenceTemplateError
from hydrolitagent.cards.ports.paper import (
    ConversionFailure,
    ConversionOptions,
    PaperConverter,
    PaperStore,
)
from hydrolitagent.cards.ports.runner import CardRunRequest, CardRunResult, CardRunner
from hydrolitagent.cards.ports.session import SessionRunner
from hydrolitagent.cards.progress import ProgressCallback, report_progress

READING_PROMPT = ASSETS_DIR / "prompts/markdown-reading-v1.md"
OUTPUT_SCHEMA = ASSETS_DIR / "schemas/subject-card-draft-output-v3.schema.json"
DRAFT_SCHEMA_VERSION = 2


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _group_id(record: dict[str, Any]) -> int | None:
    library = record["library"]
    return library["id"] if library["type"] == "group" else None


# --------------------------------------------------------------------------------------
# Shared preparation (input → prepared paper → prompt bundle)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Preparation:
    """Everything a runner needs, produced once per run."""

    record: dict[str, Any]
    pdf_path: Path
    prepared: PreparedPaper
    markdown: str
    canaries: tuple[str, ...]
    base_prompt: dict[str, Any]
    supplement: dict[str, Any]
    catalog: dict[str, Any]
    templates: dict[str, Any]
    schema_text: str
    schema: dict[str, Any]
    run_id: str
    context: dict[str, Any]
    prompt: str
    root: Path


class _Stage:
    """Mutable stage marker for the failure envelope (``failed_stage``)."""

    def __init__(self, value: str = "input") -> None:
        self.value = value


def _prepare_card(
    app_config: Any,
    paper_input: Any,
    *,
    converter: PaperConverter,
    store: PaperStore,
    options: ConversionOptions | None,
    output_root: Any,
    stage: _Stage,
) -> _Preparation:
    record, pdf_path = read_paper_input(paper_input)
    stage.value = "prepare"
    prepared = prepare_paper(
        pdf_path,
        converter=converter,
        store=store,
        options=options,
        group_id=_group_id(record),
        parent_key=record["item"]["item_key"],
        attachment_key=record["pdf"]["attachment_key"],
    )
    markdown = prepared.markdown_path.read_text(encoding="utf-8")
    if _sha256_text(markdown) != prepared.markdown_sha256:
        raise CardGenerationError(
            "MARKDOWN_SHA_MISMATCH", "转换产物在落盘后发生了变化，拒绝使用"
        )
    canaries = expected_canaries(markdown)
    if not canaries:
        raise CardGenerationError(
            "CONVERTER_NO_CANARIES",
            "转换结果缺少完整性 canary，无法证明模型读到了全文",
        )

    stage.value = "assets"
    root = resolve_literature_root(root=output_root)
    base_prompt = read_prompt(app_config.paths.evidence_card_generation_prompt_file)
    supplement = read_prompt(READING_PROMPT)
    catalog, all_templates = load_template_bundle(
        app_config.paths.evidence_card_templates_dir,
        app_config.paths.evidence_card_template_catalog_file,
    )
    templates = {
        key: value
        for key, value in all_templates.items()
        if key in SINGLE_SOURCE_TEMPLATES
    }
    if not templates:
        raise CardGenerationError(
            "CARD_DRAFT_TEMPLATE_INVALID", "没有启用适用于单篇来源的模板"
        )
    schema_text = OUTPUT_SCHEMA.read_text(encoding="utf-8")
    schema = json.loads(schema_text)

    run_id = uuid.uuid4().hex[:16]
    pdf = record["pdf"]
    parent = record["item"]["item_key"]
    # Deliberately no PDF path and no absolute host path: the runner can only
    # see the staged workspace, so a leaked path would be a lie about access.
    context = {
        "run_id": run_id,
        "library": record["library"],
        "item": record["item"],
        "zotero_parent_key": parent,
        "zotero_attachment_key": pdf["attachment_key"],
        "source_pdf_sha256": pdf["sha256"],
        "markdown_sha256": prepared.markdown_sha256,
        "markdown_file": MARKDOWN_FILENAME,
        "figures_dir": FIGURES_DIRNAME,
        "page_count": prepared.page_count,
        "converter_id": prepared.converter_id,
        "converter_version": prepared.converter_version,
        "reading_scope": "FULL_MARKDOWN",
        "card_state": "DRAFT_PENDING_VALIDATION",
        "enabled_template_ids": sorted(templates),
        "reading_canaries": list(canaries),
        "page_anchors": [
            {"page": anchor.page, "role": anchor.role, "heading": anchor.heading}
            for anchor in prepared.page_anchors
        ],
        "figures": [
            {
                "figure_id": figure.figure_id,
                "page": figure.page,
                "file": f"{FIGURES_DIRNAME}/{figure.path.name}",
                "caption": figure.caption,
            }
            for figure in prepared.figures
        ],
        "converter_warnings": list(prepared.warnings),
    }
    prompt = (
        build_template_prompt(base_prompt, context, templates)
        + "\n"
        + supplement["content"]
    )
    return _Preparation(
        record=record,
        pdf_path=pdf_path,
        prepared=prepared,
        markdown=markdown,
        canaries=canaries,
        base_prompt=base_prompt,
        supplement=supplement,
        catalog=catalog,
        templates=templates,
        schema_text=schema_text,
        schema=schema,
        run_id=run_id,
        context=context,
        prompt=prompt,
        root=root,
    )


def _card_run_request(
    prep: _Preparation,
    workspace: Path,
    app_config: Any,
    progress: ProgressCallback | None,
) -> CardRunRequest:
    card_generator = app_config.card_generator
    return CardRunRequest(
        run_id=prep.run_id,
        paper=prep.prepared,
        prompt=prep.prompt,
        output_schema=prep.schema,
        workspace=workspace,
        timeout_seconds=card_generator.generation_timeout_seconds,
        role="card_writer",
        model=card_generator.model,
        reasoning_effort=card_generator.reasoning_effort,
        reading_mode="file",
        progress=progress,
    )


# --------------------------------------------------------------------------------------
# Shared completion (runner output → grounding → validated, saved draft)
# --------------------------------------------------------------------------------------


def _markdown_source_access(prepared, reading: VerifiedReading) -> dict[str, Any]:
    """The on-disk receipt for a Markdown reading (``method=markdown_prepared``)."""

    return {
        "method": MARKDOWN_PREPARED,
        "source_pdf_sha256": prepared.source.pdf_sha256,
        "markdown_sha256": prepared.markdown_sha256,
        "parent_key": prepared.source.parent_key,
        "page_count": prepared.page_count,
        "converter_id": prepared.converter_id,
        "converter_version": prepared.converter_version,
        "reading": reading.as_dict(),
    }


def _process_audit(prepared, reading: VerifiedReading, run: CardRunResult) -> dict[str, Any]:
    """What the program checked -- explicitly not a scientific review."""

    return {
        "schema_version": 1,
        "protocol_version": MARKDOWN_CARD_PROTOCOL_VERSION,
        "status": "PROCESS_VALIDATED",
        "runner_id": run.runner_id,
        "model_invoked": run.model_invoked,
        "duration_seconds": run.duration_seconds,
        "source_pdf_sha256": prepared.source.pdf_sha256,
        "markdown_sha256": prepared.markdown_sha256,
        "converter_id": prepared.converter_id,
        "converter_version": prepared.converter_version,
        "gates": {
            "source_identity": True,
            "markdown_grounded": reading.verified,
            "canaries_echoed": reading.canaries_ok,
            "nonempty_output": True,
            "content_validation_performed": False,
            "independent_review": False,
            "scientific_correctness_verified": False,
        },
        "scope": (
            "仅校验来源身份、运行目录隔离、Markdown 接地与非空结果；"
            "不检查正文结构、编号、措辞或科研正确性。"
        ),
    }


def _complete_draft(
    prep: _Preparation,
    run: CardRunResult,
    output: dict[str, Any],
    *,
    stage: _Stage,
) -> dict[str, Any]:
    """Ground, validate and save one runner answer; the shared tail of every path."""

    stage.value = "grounding"
    reading = verify_reading(
        ReadingReceipt.from_output(output),
        prep.markdown,
        prep.prepared.page_anchors,
    )
    pdf = prep.record["pdf"]
    parent = prep.record["item"]["item_key"]
    access = _markdown_source_access(prep.prepared, reading)
    if reading.verified and not source_access_acceptable(
        access, expected_sha256=pdf["sha256"], expected_parent_key=parent
    ):
        raise CardGenerationError(
            "CARD_DRAFT_SOURCE_MISMATCH", "阅读回执与输入论文身份不符"
        )

    stage.value = "output"
    validated = validate_model_output(
        output,
        prep.templates,
        draft_path=run.unvalidated_output_path,
    )
    if validated["source_page_count"] != prep.prepared.page_count:
        raise CardGenerationError(
            "MARKDOWN_PAGE_COUNT_MISMATCH", "模型页数与已转换 Markdown 的页锚点数不一致"
        )
    fields = output.get("machine_fields")
    check_wire(fields, prep.schema["properties"]["machine_fields"])
    template = prep.templates[validated["template_id"]]

    warnings = [*run.warnings]
    if reading.status != "VERIFIED":
        warnings.append("GROUNDING_COVERAGE_PARTIAL")
    if prep.prepared.warnings:
        warnings.append("CONVERTER_WARNINGS_PRESENT")

    audit = _process_audit(prep.prepared, reading, run)
    draft = {
        "schema_version": DRAFT_SCHEMA_VERSION,
        "draft_id": prep.run_id,
        "status": "DRAFT_PENDING_VALIDATION",
        "created_at": _now(),
        "pipeline": "markdown",
        "content_validation_performed": False,
        "production_eligible": False,
        "scientific_correctness_verified": False,
        "source": {
            "library": prep.record["library"],
            "parent_key": parent,
            "requested_item_key": prep.record["requested_item_key"],
            "attachment_key": pdf["attachment_key"],
            "pdf_sha256": pdf["sha256"],
            "pdf_size_bytes": pdf["file_size_bytes"],
            "pdf_page_count": prep.prepared.page_count,
            "item": prep.record["item"],
        },
        "card_body_markdown": validated["card_body_markdown"],
        "machine_fields": fields,
        "provenance": {
            "prompt_version": prep.base_prompt["version"],
            "prompt_sha256": prep.base_prompt["sha256"],
            "draft_prompt_version": prep.supplement["version"],
            "draft_prompt_sha256": prep.supplement["sha256"],
            "combined_prompt_sha256": _sha256_text(prep.prompt),
            "output_schema_sha256": _sha256_text(prep.schema_text),
            "template_id": validated["template_id"],
            "template_version": template["local_version"],
            "template_sha256": template["content_sha256"],
            "catalog_version": prep.catalog["catalog_version"],
            "converter_id": prep.prepared.converter_id,
            "converter_version": prep.prepared.converter_version,
            "runner_id": run.runner_id,
            "model": run.model,
            "reasoning_effort": run.reasoning_effort,
            "generation_protocol_version": MARKDOWN_CARD_PROTOCOL_VERSION,
        },
        # ``reading_record`` stays the reader used by the existing validator;
        # ``source_access`` is the name the Markdown contract uses. Both hold
        # the same object so neither can drift.
        "reading_record": access,
        "source_access": access,
        "process_audit": audit,
        "usage": run.usage,
        "warnings": warnings,
    }
    stage.value = "save"
    saved = save_draft(prep.root, draft)
    return {
        **saved,
        "status": draft["status"],
        "draft_id": draft["draft_id"],
        "source": draft["source"],
        "source_access": access,
        "reading_status": reading.status,
        "runner_id": run.runner_id,
    }


# --------------------------------------------------------------------------------------
# Failure envelope shared by every entry point
# --------------------------------------------------------------------------------------


def _base_result(operation: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": operation,
        "ok": False,
        "status": "FAILED",
        "pipeline": "markdown",
        "model_invoked": False,
        "content_validation_performed": False,
        "production_eligible": False,
    }


def _error_payload(exc: BaseException) -> dict[str, Any] | None:
    """Map a known failure type to the JSON error block; ``None`` re-raises."""

    if isinstance(exc, GroundingError):
        return {
            "code": exc.code,
            "message": str(exc),
            "diagnostic": {"stage": "grounding", **exc.detail},
        }
    if isinstance(exc, (CardGenerationError, EvidenceTemplateError)):
        payload: dict[str, Any] = {"code": exc.code, "message": str(exc)}
        if getattr(exc, "diagnostic", None):
            payload["diagnostic"] = exc.diagnostic
        return payload
    if isinstance(exc, ConversionFailure):
        return {
            "code": exc.error.code,
            "message": exc.error.message,
            "fix": exc.error.fix,
        }
    if isinstance(exc, PathConfigError):
        return {"code": "CARD_DRAFT_PATH_INVALID", "message": str(exc)}
    if isinstance(exc, OSError):
        return {
            "code": "CARD_DRAFT_IO_ERROR",
            "message": "Markdown 制卡阶段 IO 失败",
        }
    if isinstance(exc, (ValueError, TypeError)):
        return {
            "code": "CARD_DRAFT_INPUT_INVALID",
            "message": f"Markdown 制卡阶段输入无效：{type(exc).__name__}",
        }
    # Port-level failures (a session runner's staging error, for example) carry
    # their own machine-readable code without the application importing the
    # adapter's exception class.
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        payload = {"code": code, "message": str(exc)}
        detail = getattr(exc, "detail", None)
        if isinstance(detail, dict) and detail:
            payload["diagnostic"] = dict(detail)
        return payload
    return None


def _record_failure(result: dict[str, Any], exc: BaseException, stage: _Stage) -> None:
    payload = _error_payload(exc)
    if payload is None:
        raise exc
    if payload["code"] == "CARD_DRAFT_IO_ERROR":
        payload["message"] = f"Markdown 制卡阶段 {stage.value} 失败：OSError"
    elif payload["code"] == "CARD_DRAFT_INPUT_INVALID":
        payload["message"] = (
            f"Markdown 制卡阶段 {stage.value} 失败：{type(exc).__name__}"
        )
    result["error"] = payload
    result["failed_stage"] = stage.value


# --------------------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------------------


def generate_markdown_card_draft(
    app_config: Any,
    paper_input: Any,
    *,
    converter: PaperConverter,
    store: PaperStore,
    runner: CardRunner,
    output_root=None,
    progress: ProgressCallback | None = None,
    options: ConversionOptions | None = None,
) -> dict:
    """Return a DRAFT_PENDING_VALIDATION or a structured failure; never retry."""

    result = _base_result("subject_card_draft")
    stage = _Stage()
    workspace: Path | None = None
    run: CardRunResult | None = None
    try:
        prep = _prepare_card(
            app_config,
            paper_input,
            converter=converter,
            store=store,
            options=options,
            output_root=output_root,
            stage=stage,
        )
        stage.value = "workspace"
        workspace = stage_paper_workspace(
            prep.prepared,
            run_id=prep.run_id,
            root=runtime_dir(app_config),
            context=prep.context,
            schema_text=prep.schema_text,
        )
        request = _card_run_request(prep, workspace, app_config, progress)
        stage.value = "generation"
        report_progress(
            progress, "phase", message="已把 paper.md 与图资产放入只读运行目录，等待模型读取"
        )
        run = runner.run(request)
        result["model_invoked"] = run.model_invoked is True
        if not run.ok:
            error = run.error
            raise CardGenerationError(
                error.code if error else "CARD_DRAFT_GENERATION_FAILED",
                error.message if error else "Markdown 制卡运行器失败",
                diagnostic={"runner_id": run.runner_id,
                            "duration_seconds": run.duration_seconds,
                            **(dict(error.detail) if error and error.detail else {})},
            )
        output = run.output
        if not isinstance(output, dict):
            raise CardGenerationError(
                "MARKDOWN_RUNNER_OUTPUT_INVALID", "运行器没有返回 JSON 对象"
            )
        completed = _complete_draft(prep, run, output, stage=stage)
        # The draft now holds everything the run produced; the staged copy of the
        # paper is disposable. A failed run keeps its workspace for diagnosis.
        shutil.rmtree(workspace, ignore_errors=True)
        workspace = None
        return {**result, **completed, "ok": True}
    except Exception as exc:  # noqa: BLE001 - mapped below, unknowns re-raised
        _record_failure(result, exc, stage)
    if workspace is not None:
        # Kept on purpose: a failed run leaves paper.md and the raw response in
        # the runtime area so the operator can see what the model actually got.
        result.setdefault("error", {}).setdefault("diagnostic", {})[
            "workspace"
        ] = str(workspace)
    if run is not None and run.unvalidated_output_path and not result["ok"]:
        result.setdefault("error", {}).setdefault("diagnostic", {})[
            "unvalidated_model_output_path"
        ] = run.unvalidated_output_path
    return result


def prepare_session_run(
    app_config: Any,
    paper_input: Any,
    *,
    converter: PaperConverter,
    store: PaperStore,
    runner: SessionRunner,
    run_dir: Path,
    output_root=None,
    options: ConversionOptions | None = None,
) -> dict:
    """Stage a run directory for an external agent; never invokes a model."""

    result = _base_result("session_prepare")
    stage = _Stage()
    try:
        prep = _prepare_card(
            app_config,
            paper_input,
            converter=converter,
            store=store,
            options=options,
            output_root=output_root,
            stage=stage,
        )
        stage.value = "workspace"
        request = _card_run_request(prep, Path(run_dir), app_config, None)
        prepared = runner.prepare(request)
        return {
            **result,
            "ok": True,
            "status": "AWAITING_SESSION_OUTPUT",
            "run_dir": str(prepared.run_dir),
            "markdown_sha256": prepared.markdown_sha256,
            "page_count": prepared.page_count,
            "canaries": list(prepared.canaries),
            "figures": [
                {
                    "figure_id": figure.figure_id,
                    "page": figure.page,
                    "file": f"{FIGURES_DIRNAME}/{figure.path.name}",
                    "caption": figure.caption,
                }
                for figure in prepared.figures
            ],
            "schema_path": str(prepared.schema_path),
            "instructions_path": str(prepared.instructions_path),
            "request_path": str(prepared.request_path),
            "response_path": str(prepared.response_path),
            "literature_root": str(prep.root),
        }
    except Exception as exc:  # noqa: BLE001 - mapped below, unknowns re-raised
        _record_failure(result, exc, stage)
    result.setdefault("error", {}).setdefault("diagnostic", {})[
        "run_dir"
    ] = str(run_dir)
    return result


def _adopt_session_request(prep: _Preparation, run_dir: Path) -> _Preparation:
    """Align the draft's provenance with the request the agent actually read.

    The run directory was staged by a previous ``prepare`` call with its own run
    id and prompt. Finalizing regenerates both from configuration, so reading
    the recorded values keeps ``draft_id`` traceable to the directory and makes
    ``combined_prompt_sha256`` describe the prompt the agent saw. The recorded
    Markdown digest also proves the directory belongs to this input paper.
    """

    path = Path(run_dir) / REQUEST_FILENAME
    if not path.is_file():
        raise CardGenerationError(
            "IN_SESSION_REQUEST_MISSING",
            f"运行目录缺少 {REQUEST_FILENAME}；请先用 cards run prepare 准备",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CardGenerationError(
            "IN_SESSION_REQUEST_INVALID", f"{REQUEST_FILENAME} 不是有效 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise CardGenerationError(
            "IN_SESSION_REQUEST_INVALID", f"{REQUEST_FILENAME} 必须是 JSON 对象"
        )
    recorded_sha = payload.get("markdown_sha256")
    if recorded_sha != prep.prepared.markdown_sha256:
        raise CardGenerationError(
            "MARKDOWN_SHA_MISMATCH", "运行目录的 request.json 与输入论文不一致"
        )
    run_id = payload.get("run_id")
    prompt = payload.get("prompt")
    if not isinstance(run_id, str) or not run_id.strip():
        raise CardGenerationError("IN_SESSION_REQUEST_INVALID", "request.json 缺少 run_id")
    if not isinstance(prompt, str) or not prompt.strip():
        raise CardGenerationError("IN_SESSION_REQUEST_INVALID", "request.json 缺少 prompt")
    return replace(prep, run_id=run_id, prompt=prompt)


def finalize_session_run(
    app_config: Any,
    paper_input: Any,
    *,
    converter: PaperConverter,
    store: PaperStore,
    runner: SessionRunner,
    run_dir: Path,
    output_root=None,
    options: ConversionOptions | None = None,
) -> dict:
    """Read ``response.json`` from a prepared run directory and save a draft."""

    result = _base_result("session_finalize")
    stage = _Stage()
    run: CardRunResult | None = None
    try:
        prep = _prepare_card(
            app_config,
            paper_input,
            converter=converter,
            store=store,
            options=options,
            output_root=output_root,
            stage=stage,
        )
        stage.value = "generation"
        prep = _adopt_session_request(prep, run_dir)
        run = runner.finalize(Path(run_dir), paper=prep.prepared)
        result["model_invoked"] = run.model_invoked is True
        if not run.ok:
            error = run.error
            raise CardGenerationError(
                error.code if error else "IN_SESSION_FINALIZE_FAILED",
                error.message if error else "in_session 收口失败",
                diagnostic={
                    "runner_id": run.runner_id,
                    "duration_seconds": run.duration_seconds,
                    **(dict(error.detail) if error and error.detail else {}),
                },
            )
        output = run.output
        if not isinstance(output, dict):
            raise CardGenerationError(
                "MARKDOWN_RUNNER_OUTPUT_INVALID", "response.json 没有给出 JSON 对象"
            )
        completed = _complete_draft(prep, run, output, stage=stage)
        return {**result, **completed, "ok": True}
    except Exception as exc:  # noqa: BLE001 - mapped below, unknowns re-raised
        _record_failure(result, exc, stage)
    result.setdefault("error", {}).setdefault("diagnostic", {})[
        "run_dir"
    ] = str(run_dir)
    response = Path(run_dir) / "response.json"
    if response.is_file():
        # The unvalidated answer is kept for post-mortem inspection; finalize
        # never deletes or rewrites it.
        result.setdefault("error", {}).setdefault("diagnostic", {})[
            "response_path"
        ] = str(response)
    return result


__all__ = [
    "DRAFT_SCHEMA_VERSION",
    "OUTPUT_SCHEMA",
    "READING_PROMPT",
    "finalize_session_run",
    "generate_markdown_card_draft",
    "prepare_session_run",
]
