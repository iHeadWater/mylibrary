from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hydrolitagent.cards.config import (
    LEGACY_SINGLE_AGENT_PROTOCOL_VERSION,
    LOCAL_PATH_PROTOCOL_VERSION,
    MULTI_AGENT_PROTOCOL_VERSION,
    SINGLE_AGENT_PROTOCOL_VERSION,
)
from hydrolitagent.cards.domain.source_access import (
    BOUND_LOCAL_PDF_MCP,
    LOCAL_PDF_PATH,
    source_access_acceptable,
)
from hydrolitagent.cards.tasks import build_task_id


PLACEHOLDER_CARD = "# 待生成证据卡\n\n状态：PLACEHOLDER\n"
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9]+$")
_HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_TASK_ID_PATTERN = re.compile(r"^TASK-[0-9a-f]{64}$")
_CARD_STATUSES = frozenset({"PLACEHOLDER", "ROUGH"})


class EvidencePackageError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _safe_key(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not _KEY_PATTERN.fullmatch(value):
        raise EvidencePackageError(
            "EVIDENCE_TASK_INVALID",
            f"{name} 必须是只包含字母和数字的 Zotero Key",
        )
    return value


def validate_evidence_task(task: Any, group_id: int) -> dict[str, Any]:
    if not isinstance(task, dict):
        raise EvidencePackageError("EVIDENCE_TASK_INVALID", "任务记录必须是 JSON 对象")
    if task.get("group_id") != group_id:
        raise EvidencePackageError("EVIDENCE_TASK_INVALID", "任务群组与目标群组不一致")

    parent_key = _safe_key(task.get("parent_key"), name="parent_key")
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not _TASK_ID_PATTERN.fullmatch(task_id):
        raise EvidencePackageError("EVIDENCE_TASK_INVALID", f"任务 {parent_key} 缺少有效 task_id")

    input_data = task.get("input")
    if not isinstance(input_data, dict):
        raise EvidencePackageError("EVIDENCE_TASK_INVALID", f"任务 {parent_key} 缺少输入指纹")
    attachment_key = _safe_key(input_data.get("attachment_key"), name="attachment_key")
    pdf_sha256 = input_data.get("pdf_sha256")
    if not isinstance(pdf_sha256, str) or not _HASH_PATTERN.fullmatch(pdf_sha256):
        raise EvidencePackageError(
            "EVIDENCE_TASK_INVALID",
            f"任务 {parent_key} 缺少有效 PDF SHA-256",
        )
    normalized_hash = pdf_sha256.lower()
    expected_task_id = build_task_id(
        group_id,
        parent_key,
        attachment_key,
        normalized_hash,
    )
    if task_id != expected_task_id:
        raise EvidencePackageError(
            "EVIDENCE_TASK_INVALID",
            f"任务 {parent_key} 的 task_id 与输入指纹不一致",
        )

    title = task.get("title")
    normalized_title = title.strip() if isinstance(title, str) and title.strip() else "Untitled"
    return {
        "task_id": task_id,
        "group_id": group_id,
        "parent_key": parent_key,
        "attachment_key": attachment_key,
        "pdf_sha256": normalized_hash,
        "title": normalized_title,
    }


def load_evidence_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidencePackageError(
            "EVIDENCE_MANIFEST_INVALID",
            f"无法读取证据包清单：{path}",
        ) from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise EvidencePackageError(
            "EVIDENCE_MANIFEST_INVALID",
            f"证据包清单结构或版本无效：{path}",
        )
    required_strings = (
        "evidence_id",
        "parent_key",
        "attachment_key",
        "pdf_sha256",
        "source_task_id",
        "title",
        "card_status",
        "created_at",
        "updated_at",
    )
    if any(not isinstance(data.get(name), str) or not data[name] for name in required_strings):
        raise EvidencePackageError(
            "EVIDENCE_MANIFEST_INVALID",
            f"证据包清单缺少必要字段：{path}",
        )
    if (
        isinstance(data.get("group_id"), bool)
        or not isinstance(data.get("group_id"), int)
        or data["group_id"] <= 0
        or not _KEY_PATTERN.fullmatch(data["parent_key"])
        or not _KEY_PATTERN.fullmatch(data["attachment_key"])
        or not _HASH_PATTERN.fullmatch(data["pdf_sha256"])
        or not _TASK_ID_PATTERN.fullmatch(data["source_task_id"])
        or data["card_status"] not in _CARD_STATUSES
    ):
        raise EvidencePackageError(
            "EVIDENCE_MANIFEST_INVALID",
            f"证据包清单字段格式无效：{path}",
        )
    if data["card_status"] == "ROUGH":
        generation = data.get("generation")
        required_generation_strings = (
            "generator_adapter",
            "generator_protocol_version",
            "cli_version",
            "model",
            "reasoning_effort",
            "prompt_version",
            "prompt_sha256",
            "output_schema_sha256",
            "template_catalog_version",
            "template_id",
            "template_version",
            "template_source_commit",
            "template_content_sha256",
            "classification_reason",
            "reading_scope",
            "source_access_method",
            "source_read_status",
            "visual_content_status",
            "source_read_evidence",
            "generated_at",
            "card_sha256",
        )
        if not isinstance(generation, dict) or any(
            not isinstance(generation.get(name), str) or not generation[name]
            for name in required_generation_strings
        ):
            raise EvidencePackageError(
                "EVIDENCE_MANIFEST_INVALID",
                f"已生成证据包缺少必要生成记录：{path}",
            )
        confidence = generation.get("classification_confidence")
        source_page_count = generation.get("source_page_count")
        source_pages_served = generation.get("source_pages_served")
        source_visual_pages_served = generation.get("source_visual_pages_served")
        direct = generation.get("source_access_method") == LOCAL_PDF_PATH
        protocol = generation.get("workflow_protocol_version")
        single = protocol in {SINGLE_AGENT_PROTOCOL_VERSION, LEGACY_SINGLE_AGENT_PROTOCOL_VERSION}
        expected_quality_status = ("PROCESS_VALIDATED" if protocol == SINGLE_AGENT_PROTOCOL_VERSION
                                   else "STRUCTURE_VALIDATED" if single else "VALIDATED")
        if direct:
            access = generation.get("source_access")
            source_ok = (source_access_acceptable(access, expected_sha256=data["pdf_sha256"],
                                                  expected_parent_key=data["parent_key"])
                         and access.get("method") == LOCAL_PDF_PATH and access.get("page_count") == source_page_count
                         and generation.get("source_access_verified") is False
                         and generation.get("source_access_server") is None
                         and generation.get("source_access_receipt_schema_version") is None
                         and source_pages_served is None and source_visual_pages_served is None
                         and generation.get("quality_status") == expected_quality_status
                         and protocol in {LOCAL_PATH_PROTOCOL_VERSION, SINGLE_AGENT_PROTOCOL_VERSION, LEGACY_SINGLE_AGENT_PROTOCOL_VERSION})
        else:
            source_ok = (generation.get("source_access_method") == BOUND_LOCAL_PDF_MCP
                         and generation.get("source_access_verified") is True
                         and isinstance(generation.get("source_access_server"), str) and bool(generation["source_access_server"])
                         and generation.get("source_access_receipt_schema_version") == 1
                         and type(source_pages_served) is int and source_pages_served == source_page_count
                         and type(source_visual_pages_served) is int and source_visual_pages_served == source_page_count)
        if (
            (confidence is not None and (isinstance(confidence, bool)
             or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1))
            or generation.get("output_schema_version") != 2
            or generation.get("reading_scope") != "FULL_PDF"
            or not source_ok
            or isinstance(source_page_count, bool)
            or not isinstance(source_page_count, int)
            or source_page_count < 1
            or generation.get("source_read_status") != "FULL_PDF_REVIEWED"
            or generation.get("visual_content_status") not in {"REVIEWED", "NOT_PRESENT"}
            or not _HASH_PATTERN.fullmatch(generation["prompt_sha256"])
            or not _HASH_PATTERN.fullmatch(generation["output_schema_sha256"])
            or not _HASH_PATTERN.fullmatch(generation["template_content_sha256"])
            or not _HASH_PATTERN.fullmatch(generation["card_sha256"])
            or not re.fullmatch(r"[0-9a-f]{40}", generation["template_source_commit"])
        ):
            raise EvidencePackageError(
                "EVIDENCE_MANIFEST_INVALID",
                f"已生成证据包的生成记录格式无效：{path}",
            )
        if "quality_status" in generation and (
            generation.get("quality_status") != expected_quality_status
            or generation.get("workflow_protocol_version")
            != (protocol if single and direct else LOCAL_PATH_PROTOCOL_VERSION if direct else MULTI_AGENT_PROTOCOL_VERSION)
            or type(generation.get("workflow_role_count")) is not int
            or generation.get("workflow_role_count") != (1 if single else 6)
            or generation.get("quality_audit_file") != "quality-audit.json"
            or not isinstance(generation.get("quality_audit_sha256"), str)
            or not _HASH_PATTERN.fullmatch(generation["quality_audit_sha256"])
        ):
            raise EvidencePackageError(
                "EVIDENCE_MANIFEST_INVALID",
                f"已生成证据包的工作流记录无效：{path}",
            )
    elif "generation" in data:
        raise EvidencePackageError(
            "EVIDENCE_MANIFEST_INVALID",
            f"占位证据包不得包含生成记录：{path}",
        )
    return data


def find_evidence_package(root: Path, parent_key: str) -> Path | None:
    prefix = f"EV-{parent_key}-".casefold()
    matches = [entry for entry in root.iterdir() if entry.name.casefold().startswith(prefix)]
    if len(matches) > 1:
        raise EvidencePackageError(
            "EVIDENCE_PACKAGE_DUPLICATE",
            f"父条目 {parent_key} 对应多个证据包目录，拒绝自动选择",
        )
    if not matches:
        return None
    package_path = matches[0]
    if not package_path.is_dir():
        raise EvidencePackageError(
            "EVIDENCE_PACKAGE_INVALID",
            f"证据包路径不是目录：{package_path}",
        )
    return package_path
