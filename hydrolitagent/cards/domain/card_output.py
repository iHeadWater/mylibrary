"""Validate one model answer against the card output protocol.

This is the wire contract shared by every executor: a Markdown draft produced
by ``cards run finalize``, by the direct HTTP runner or by an older artifact
must carry the same fields and the same honesty flags before anything is saved.

It judges presence and shape only. ``structure_validation`` deliberately reports
``NOT_CHECKED``: template wording and body Markdown are model instructions, not
publication gates, so the program must not imply that a card passed content
review.

A failing answer is reported as a *list* of :class:`Violation` (see
``collect_model_output_violations``) rather than one vague exception: the caller
may be a repair step that has to tell the model exactly which fields to touch.
"""
from __future__ import annotations

from typing import Any

from hydrolitagent.cards.domain.errors import CardGenerationError
from hydrolitagent.cards.domain.violations import (
    MISSING,
    Violation,
    describe_value,
    violation_dicts,
)

OUTPUT_SCHEMA_VERSION = 2
SOURCE_READ_STATUS = "FULL_PDF_REVIEWED"
# ``NOT_REVIEWED`` is the honest status for a text-only runner: it received the
# Markdown (and can quote it) but no page images, so it may not claim it looked
# at a figure. ``UNREADABLE`` stays rejected: it means the source could not be
# read at all.
ACCEPTED_VISUAL_CONTENT_STATUSES = frozenset(
    {"REVIEWED", "NOT_PRESENT", "NOT_REVIEWED"}
)
MODEL_OUTPUT_FIELDS = frozenset(
    {
        "schema_version",
        "source_read_status",
        "source_page_count",
        "visual_content_status",
        "source_read_evidence",
        "template_id",
        "classification_confidence",
        "classification_reason",
        "card_body_markdown",
    }
)
_OPTIONAL_MODEL_OUTPUT_FIELDS = frozenset(
    {"classification_confidence", "classification_reason"}
)


def collect_model_output_violations(
    output: Any,
    templates: dict[str, dict[str, Any]],
) -> list[Violation]:
    """Every wire problem in one answer, not just the first one found."""

    if not isinstance(output, dict):
        return [
            Violation(
                "CARD_GENERATION_OUTPUT_INVALID",
                "answer",
                "模型输出不是 JSON 对象",
                "JSON 对象",
                describe_value(output),
            )
        ]

    violations: list[Violation] = []
    for field in sorted(MODEL_OUTPUT_FIELDS - _OPTIONAL_MODEL_OUTPUT_FIELDS):
        if field not in output:
            violations.append(
                Violation(
                    "CARD_GENERATION_OUTPUT_INVALID",
                    field,
                    "模型输出缺少必需字段",
                    "该字段存在",
                    "未提供",
                )
            )

    schema_version = output.get("schema_version", MISSING)
    if schema_version is not MISSING and schema_version != OUTPUT_SCHEMA_VERSION:
        violations.append(
            Violation(
                "CARD_GENERATION_OUTPUT_INVALID",
                "schema_version",
                "schema_version 必须等于协议版本",
                str(OUTPUT_SCHEMA_VERSION),
                describe_value(schema_version),
            )
        )

    source_read_status = output.get("source_read_status", MISSING)
    if source_read_status is not MISSING and source_read_status != SOURCE_READ_STATUS:
        violations.append(
            Violation(
                "CARD_PDF_READ_UNVERIFIED",
                "source_read_status",
                "模型未确认已经检查完整原始文献，拒绝写入证据卡",
                SOURCE_READ_STATUS,
                describe_value(source_read_status),
            )
        )

    source_page_count = output.get("source_page_count", MISSING)
    if source_page_count is not MISSING and not _is_page_count(source_page_count):
        violations.append(
            Violation(
                "CARD_PDF_READ_UNVERIFIED",
                "source_page_count",
                "模型没有返回有效的原始 PDF 页数",
                "1 到 100000 之间的整数",
                describe_value(source_page_count),
            )
        )

    visual_content_status = output.get("visual_content_status", MISSING)
    if (
        visual_content_status is not MISSING
        and visual_content_status not in ACCEPTED_VISUAL_CONTENT_STATUSES
    ):
        violations.append(
            Violation(
                "CARD_PDF_VISUALS_UNVERIFIED",
                "visual_content_status",
                "模型未确认已经检查原始 PDF 的图、表和公式，拒绝写入证据卡",
                "、".join(sorted(ACCEPTED_VISUAL_CONTENT_STATUSES)),
                describe_value(visual_content_status),
            )
        )

    source_read_evidence = output.get("source_read_evidence", MISSING)
    if source_read_evidence is not MISSING and not _is_nonblank_str(source_read_evidence):
        violations.append(
            Violation(
                "CARD_PDF_READ_UNVERIFIED",
                "source_read_evidence",
                "模型没有返回可追溯的完整文献阅读回执",
                "非空字符串",
                describe_value(source_read_evidence),
            )
        )

    template_id = output.get("template_id", MISSING)
    if template_id is not MISSING and not (
        isinstance(template_id, str) and template_id in templates
    ):
        violations.append(
            Violation(
                "CARD_GENERATION_TEMPLATE_INVALID",
                "template_id",
                "模型返回了非法或未启用的模板 ID",
                "已启用的模板 ID：" + "、".join(sorted(templates)),
                describe_value(template_id),
            )
        )

    body = output.get("card_body_markdown", MISSING)
    if body is not MISSING and not _is_nonblank_str(body):
        violations.append(
            Violation(
                "CARD_GENERATION_OUTPUT_INVALID",
                "card_body_markdown",
                "模型没有返回证据卡 Markdown 正文",
                "非空字符串",
                describe_value(body),
            )
        )

    return violations


def normalize_model_output(
    output: dict[str, Any],
    templates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Decode an answer that already has no violations into the saved fields."""

    confidence = output.get("classification_confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        confidence = None  # Unknown metadata is not a reason to discard usable Markdown.
    reason = output.get("classification_reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = "模型未提供分类理由"
    # Keep this legacy result key explicit so existing consumers cannot read it
    # as PASS: the program checked the wire shape, nothing else.
    structure_validation = {
        "policy_version": "workflow-only-v1",
        "status": "NOT_CHECKED",
        "content_validation_performed": False,
        "scientific_correctness_verified": False,
        "note": "正文按模型输出保存；程序不检查模板结构、标签、编号、占位词或内容质量",
    }
    return {
        "source_read_status": output["source_read_status"],
        "source_page_count": output["source_page_count"],
        "visual_content_status": output["visual_content_status"],
        "source_read_evidence": output["source_read_evidence"].strip(),
        "template_id": output["template_id"],
        "classification_confidence": float(confidence) if confidence is not None else None,
        "classification_reason": reason.strip(),
        "card_body_markdown": output["card_body_markdown"],
        "structure_validation": structure_validation,
    }


def validate_model_output(
    output: Any,
    templates: dict[str, dict[str, Any]],
    *,
    draft_path: str | None = None,
) -> dict[str, Any]:
    """Return the normalised fields, or raise with a stable error code."""

    try:
        return validate_model_output_fields(output, templates)
    except CardGenerationError as exc:
        if draft_path:
            exc.diagnostic = {
                **(exc.diagnostic or {}),
                "stage": "card_output_validation",
                "draft_path": draft_path,
            }
        raise


def validate_model_output_fields(
    output: Any,
    templates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    violations = collect_model_output_violations(output, templates)
    if violations:
        raise _violation_error(violations)
    return normalize_model_output(output, templates)


def _violation_error(violations: list[Violation]) -> CardGenerationError:
    """One exception carrying the whole list; single problems keep their wording."""

    message = (
        violations[0].message
        if len(violations) == 1
        else f"模型输出不符合制卡协议：{len(violations)} 处问题"
    )
    return CardGenerationError(
        violations[0].code,
        message,
        diagnostic={"violations": violation_dicts(violations)},
    )


def _is_page_count(value: Any) -> bool:
    return type(value) is int and 1 <= value <= 100000


def _is_nonblank_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = [
    "ACCEPTED_VISUAL_CONTENT_STATUSES",
    "MODEL_OUTPUT_FIELDS",
    "OUTPUT_SCHEMA_VERSION",
    "SOURCE_READ_STATUS",
    "collect_model_output_violations",
    "normalize_model_output",
    "validate_model_output",
    "validate_model_output_fields",
]
