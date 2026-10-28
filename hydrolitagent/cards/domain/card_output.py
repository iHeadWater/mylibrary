"""Validate one model answer against the card output protocol.

This is the wire contract shared by every executor: a Markdown draft produced
by ``cards run finalize``, by the direct HTTP runner or by an older artifact
must carry the same fields and the same honesty flags before anything is saved.

It judges presence and shape only. ``structure_validation`` deliberately reports
``NOT_CHECKED``: template wording and body Markdown are model instructions, not
publication gates, so the program must not imply that a card passed content
review.
"""
from __future__ import annotations

from typing import Any

from hydrolitagent.cards.domain.errors import CardGenerationError

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
    required_fields = MODEL_OUTPUT_FIELDS - {
        "classification_confidence",
        "classification_reason",
    }
    if not isinstance(output, dict) or not required_fields.issubset(output):
        raise CardGenerationError(
            "CARD_GENERATION_OUTPUT_INVALID",
            "模型输出字段与制卡协议不一致",
        )
    if output.get("schema_version") != OUTPUT_SCHEMA_VERSION:
        raise CardGenerationError(
            "CARD_GENERATION_OUTPUT_INVALID",
            "模型输出 schema_version 无效",
        )
    source_read_status = output.get("source_read_status")
    if source_read_status != SOURCE_READ_STATUS:
        raise CardGenerationError(
            "CARD_PDF_READ_UNVERIFIED",
            "模型未确认已经检查完整原始文献，拒绝写入证据卡",
        )
    source_page_count = output.get("source_page_count")
    if (
        isinstance(source_page_count, bool)
        or not isinstance(source_page_count, int)
        or not 1 <= source_page_count <= 100000
    ):
        raise CardGenerationError(
            "CARD_PDF_READ_UNVERIFIED",
            "模型没有返回有效的原始 PDF 页数",
        )
    visual_content_status = output.get("visual_content_status")
    if visual_content_status not in ACCEPTED_VISUAL_CONTENT_STATUSES:
        raise CardGenerationError(
            "CARD_PDF_VISUALS_UNVERIFIED",
            "模型未确认已经检查原始 PDF 的图、表和公式，拒绝写入证据卡",
        )
    source_read_evidence = output.get("source_read_evidence")
    if (
        not isinstance(source_read_evidence, str)
        or not source_read_evidence.strip()
    ):
        raise CardGenerationError(
            "CARD_PDF_READ_UNVERIFIED",
            "模型没有返回可追溯的完整文献阅读回执",
        )
    template_id = output.get("template_id")
    if not isinstance(template_id, str) or template_id not in templates:
        raise CardGenerationError(
            "CARD_GENERATION_TEMPLATE_INVALID",
            "模型返回了非法或未启用的模板 ID",
        )
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
    body = output.get("card_body_markdown")
    if not isinstance(body, str) or not body.strip():
        raise CardGenerationError(
            "CARD_GENERATION_OUTPUT_INVALID",
            "模型没有返回证据卡 Markdown 正文",
        )
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
        "source_read_status": source_read_status,
        "source_page_count": source_page_count,
        "visual_content_status": visual_content_status,
        "source_read_evidence": source_read_evidence.strip(),
        "template_id": template_id,
        "classification_confidence": float(confidence) if confidence is not None else None,
        "classification_reason": reason.strip(),
        "card_body_markdown": body,
        "structure_validation": structure_validation,
    }


__all__ = [
    "ACCEPTED_VISUAL_CONTENT_STATUSES",
    "MODEL_OUTPUT_FIELDS",
    "OUTPUT_SCHEMA_VERSION",
    "SOURCE_READ_STATUS",
    "validate_model_output",
    "validate_model_output_fields",
]
