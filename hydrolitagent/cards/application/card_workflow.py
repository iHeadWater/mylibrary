"""Orchestrate one Markdown-first subject-card draft.

Pipeline (every arrow is a port or a pure function):

    input record → prepare_paper → staged workspace → runner.run
                 → grounding.verify_reading → output validation → atomic save

The application layer owns the artifact shape: the ``source_access`` receipt,
the draft envelope, the provenance hashes and the append-only write. It never
converts a PDF itself, never calls a model directly and never decides which
concrete converter or runner is installed -- those arrive as ports.

A failure at any step means no draft on disk. There is no retry and no silent
downgrade of a hard grounding failure to a warning.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hydrolitagent._config import PathConfigError, resolve_literature_root
from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.application.prepare_paper import prepare_paper
from hydrolitagent.cards.card_draft import (
    SINGLE_SOURCE_TEMPLATES,
    _check_wire as check_wire,
    _input as read_paper_input,
    _save as save_draft,
)
from hydrolitagent.cards.card_generation import (
    CardGenerationError,
    _load_template_bundle,
    _read_prompt,
    _validate_model_output,
    build_template_prompt,
)
from hydrolitagent.cards.domain.grounding import expected_canaries, verify_reading
from hydrolitagent.cards.domain.paper import FIGURES_DIRNAME, MARKDOWN_FILENAME
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
from hydrolitagent.cards.ports.runner import CardRunRequest, CardRunner
from hydrolitagent.cards.progress import ProgressCallback, report_progress

READING_PROMPT = ASSETS_DIR / "prompts/markdown-reading-v1.md"
OUTPUT_SCHEMA = ASSETS_DIR / "schemas/subject-card-draft-output-v3.schema.json"
REQUEST_FILENAME = "request.json"
SCHEMA_FILENAME = "output.schema.json"
DRAFT_SCHEMA_VERSION = 2


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _runtime_dir(app_config: Any) -> Path:
    configured = getattr(app_config.card_generator, "runtime_dir", None) or getattr(
        app_config.paths, "runtime_dir", None
    )
    return Path(configured) if configured else Path(tempfile.gettempdir())


def _group_id(record: dict[str, Any]) -> int | None:
    library = record["library"]
    return library["id"] if library["type"] == "group" else None


def _stage_workspace(
    prepared,
    *,
    run_id: str,
    runtime_dir: Path,
    context: dict[str, Any],
    schema_text: str,
) -> Path:
    """Create the directory a runner can read, containing no source PDF.

    The Markdown and the figure images are copied rather than referenced so the
    runner's view is exactly the preparation that grounding will verify against.
    """

    runtime_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(
        tempfile.mkdtemp(prefix=f"markdown-{run_id[:8]}-", dir=str(runtime_dir))
    )
    shutil.copyfile(prepared.markdown_path, workspace / MARKDOWN_FILENAME)
    for figure in prepared.figures:
        target = workspace / FIGURES_DIRNAME / figure.path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(figure.path, target)
    (workspace / REQUEST_FILENAME).write_text(
        json.dumps(context, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (workspace / SCHEMA_FILENAME).write_text(schema_text, encoding="utf-8", newline="\n")
    return workspace


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


def _process_audit(prepared, reading: VerifiedReading, run) -> dict[str, Any]:
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

    result: dict[str, Any] = {
        "schema_version": 1,
        "operation": "subject_card_draft",
        "ok": False,
        "status": "FAILED",
        "pipeline": "markdown",
        "model_invoked": False,
        "content_validation_performed": False,
        "production_eligible": False,
    }
    stage = "input"
    workspace: Path | None = None
    run = None
    try:
        record, pdf_path = read_paper_input(paper_input)
        stage = "prepare"
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

        stage = "assets"
        root = resolve_literature_root(root=output_root)
        base_prompt = _read_prompt(app_config.paths.evidence_card_generation_prompt_file)
        supplement = _read_prompt(READING_PROMPT)
        catalog, all_templates = _load_template_bundle(
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

        stage = "workspace"
        workspace = _stage_workspace(
            prepared,
            run_id=run_id,
            runtime_dir=_runtime_dir(app_config),
            context=context,
            schema_text=schema_text,
        )
        card_generator = app_config.card_generator
        request = CardRunRequest(
            run_id=run_id,
            paper=prepared,
            prompt=prompt,
            output_schema=schema,
            workspace=workspace,
            timeout_seconds=card_generator.generation_timeout_seconds,
            role="card_writer",
            model=card_generator.model,
            reasoning_effort=card_generator.reasoning_effort,
            reading_mode="file",
            progress=progress,
        )
        stage = "generation"
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

        stage = "grounding"
        reading = verify_reading(
            ReadingReceipt.from_output(output),
            markdown,
            prepared.page_anchors,
        )
        access = _markdown_source_access(prepared, reading)
        if reading.verified and not source_access_acceptable(
            access, expected_sha256=pdf["sha256"], expected_parent_key=parent
        ):
            raise CardGenerationError(
                "CARD_DRAFT_SOURCE_MISMATCH", "阅读回执与输入论文身份不符"
            )

        stage = "output"
        validated = _validate_model_output(
            output,
            templates,
            title=record["item"]["title"],
            draft_path=run.unvalidated_output_path,
        )
        if validated["source_page_count"] != prepared.page_count:
            raise CardGenerationError(
                "MARKDOWN_PAGE_COUNT_MISMATCH", "模型页数与已转换 Markdown 的页锚点数不一致"
            )
        fields = output.get("machine_fields")
        check_wire(fields, schema["properties"]["machine_fields"])
        template = templates[validated["template_id"]]

        warnings = [*run.warnings]
        if reading.status != "VERIFIED":
            warnings.append("GROUNDING_COVERAGE_PARTIAL")
        if prepared.warnings:
            warnings.append("CONVERTER_WARNINGS_PRESENT")

        audit = _process_audit(prepared, reading, run)
        draft = {
            "schema_version": DRAFT_SCHEMA_VERSION,
            "draft_id": run_id,
            "status": "DRAFT_PENDING_VALIDATION",
            "created_at": _now(),
            "pipeline": "markdown",
            "content_validation_performed": False,
            "production_eligible": False,
            "scientific_correctness_verified": False,
            "source": {
                "library": record["library"],
                "parent_key": parent,
                "requested_item_key": record["requested_item_key"],
                "attachment_key": pdf["attachment_key"],
                "pdf_sha256": pdf["sha256"],
                "pdf_size_bytes": pdf["file_size_bytes"],
                "pdf_page_count": prepared.page_count,
                "item": record["item"],
            },
            "card_body_markdown": validated["card_body_markdown"],
            "machine_fields": fields,
            "provenance": {
                "prompt_version": base_prompt["version"],
                "prompt_sha256": base_prompt["sha256"],
                "draft_prompt_version": supplement["version"],
                "draft_prompt_sha256": supplement["sha256"],
                "combined_prompt_sha256": _sha256_text(prompt),
                "output_schema_sha256": _sha256_text(schema_text),
                "template_id": validated["template_id"],
                "template_version": template["local_version"],
                "template_sha256": template["content_sha256"],
                "catalog_version": catalog["catalog_version"],
                "converter_id": prepared.converter_id,
                "converter_version": prepared.converter_version,
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
        stage = "save"
        saved = save_draft(root, draft)
        # The draft now holds everything the run produced; the staged copy of the
        # paper is disposable. A failed run keeps its workspace for diagnosis.
        shutil.rmtree(workspace, ignore_errors=True)
        workspace = None
        return {
            **result,
            **saved,
            "ok": True,
            "status": draft["status"],
            "draft_id": draft["draft_id"],
            "source": draft["source"],
            "source_access": access,
            "reading_status": reading.status,
            "runner_id": run.runner_id,
        }
    except GroundingError as exc:
        result["error"] = {
            "code": exc.code,
            "message": str(exc),
            "diagnostic": {"stage": "grounding", **exc.detail},
        }
    except (CardGenerationError, EvidenceTemplateError) as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
        if getattr(exc, "diagnostic", None):
            result["error"]["diagnostic"] = exc.diagnostic
    except ConversionFailure as exc:
        result["error"] = {
            "code": exc.error.code,
            "message": exc.error.message,
            "fix": exc.error.fix,
        }
    except PathConfigError as exc:
        result["error"] = {"code": "CARD_DRAFT_PATH_INVALID", "message": str(exc)}
    except (OSError, ValueError, TypeError) as exc:
        result["error"] = {
            "code": "CARD_DRAFT_IO_ERROR" if isinstance(exc, OSError) else "CARD_DRAFT_INPUT_INVALID",
            "message": f"Markdown 制卡阶段 {stage} 失败：{type(exc).__name__}",
        }
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
    result["failed_stage"] = stage
    return result


__all__ = [
    "DRAFT_SCHEMA_VERSION",
    "OUTPUT_SCHEMA",
    "READING_PROMPT",
    "generate_markdown_card_draft",
]
