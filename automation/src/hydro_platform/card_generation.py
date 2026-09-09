from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from hydro_platform.card_generators.base import CardGeneratorAdapter
from hydro_platform.card_generators.codex_cli import GENERATION_PROTOCOL_VERSION
from hydro_platform.source_access import source_access_acceptable
from hydro_platform.config import (
    REQUIRED_CARD_WORKFLOW_ROLES,
    LOCAL_PATH_PROTOCOL_VERSION,
    SINGLE_AGENT_PROTOCOL_VERSION,
    LEGACY_SINGLE_AGENT_PROTOCOL_VERSION,
    MULTI_AGENT_PROTOCOL_VERSION,
    PdfGateConfig,
    TaskConfig,
    ZoteroConfig,
)
from hydro_platform.evidence_packages import (
    PLACEHOLDER_CARD,
    EvidencePackageError,
    find_evidence_package,
    load_evidence_manifest,
    validate_evidence_task,
)
from hydro_platform.evidence_templates import (
    EvidenceTemplateError,
    validate_evidence_templates,
)
from hydro_platform.pdf_delivery import (
    PdfDelivery,
    PdfDeliveryError,
    prepare_pdf_delivery,
)
from hydro_platform.pdf_gate import ITEM_KEY_PATTERN
from hydro_platform.tasks import (
    RuntimeLock,
    TaskStoreError,
    claim_task,
    finish_task,
    load_task_registry,
)
from hydro_platform.zotero import ZoteroClient
from hydro_platform.publication import prepare_publication, recover_publication, validate_saved_package


CARD_STATE = "ROUGH"
READING_SCOPE = "FULL_PDF"
OUTPUT_SCHEMA_VERSION = 2
QUALITY_AUDIT_FILENAME = "quality-audit.json"
SOURCE_READ_STATUS = "FULL_PDF_REVIEWED"
ACCEPTED_VISUAL_CONTENT_STATUSES = frozenset({"REVIEWED", "NOT_PRESENT"})
PROMPT_VERSION_PATTERN = re.compile(
    r'^---\s*\r?\nprompt_version:\s*["\']([^"\']+)["\']\s*\r?\n---',
    re.MULTILINE,
)
TABLE_SEPARATOR_PATTERN = re.compile(
    r"^\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*$"
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


class CardGenerationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        diagnostic: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.diagnostic = diagnostic


def _timestamp(value: datetime | None = None) -> str:
    moment = value or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CardGenerationError(
            "CARD_GENERATION_FILE_UNREADABLE",
            f"无法读取制卡协议文件：{path}",
        ) from exc
    return digest.hexdigest()


def _normalize_parent_key(parent_key: str) -> str:
    normalized = parent_key.strip().upper()
    if not ITEM_KEY_PATTERN.fullmatch(normalized):
        raise CardGenerationError(
            "INVALID_ITEM_KEY",
            "父条目 Key 必须是 8 位字母或数字",
        )
    return normalized


def _read_prompt(path: Path) -> dict[str, str]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CardGenerationError(
            "CARD_GENERATION_PROMPT_INVALID",
            f"无法读取 UTF-8 制卡提示词：{path}",
        ) from exc
    match = PROMPT_VERSION_PATTERN.search(content)
    if match is None or not match.group(1).strip():
        raise CardGenerationError(
            "CARD_GENERATION_PROMPT_INVALID",
            "制卡提示词缺少 prompt_version",
        )
    return {
        "version": match.group(1).strip(),
        "sha256": _sha256_text(content),
        "content": content,
    }


def _template_body(content: str, template_file: Path) -> str:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise CardGenerationError(
            "EVIDENCE_TEMPLATE_INVALID",
            f"模板缺少 front matter：{template_file.name}",
        )
    try:
        closing = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise CardGenerationError(
            "EVIDENCE_TEMPLATE_INVALID",
            f"模板 front matter 未闭合：{template_file.name}",
        ) from exc
    body = "\n".join(lines[closing + 1 :]).strip()
    if not body:
        raise CardGenerationError(
            "EVIDENCE_TEMPLATE_INVALID",
            f"模板正文为空：{template_file.name}",
        )
    return body + "\n"


def _load_template_bundle(
    templates_dir: Path,
    catalog_file: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        catalog = validate_evidence_templates(templates_dir, catalog_file)
    except EvidenceTemplateError as exc:
        raise CardGenerationError(exc.code, str(exc)) from exc

    templates: dict[str, dict[str, Any]] = {}
    for entry in catalog["templates"]:
        if not entry["enabled"]:
            continue
        template_file = (templates_dir / entry["file"]).resolve()
        try:
            content = template_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise CardGenerationError(
                "EVIDENCE_TEMPLATE_INVALID",
                f"无法读取 UTF-8 模板：{template_file}",
            ) from exc
        templates[entry["template_id"]] = {
            **entry,
            "body": _template_body(content, template_file),
        }
    if not templates:
        raise CardGenerationError(
            "EVIDENCE_TEMPLATE_CATALOG_INVALID",
            "没有可供制卡器选择的已启用模板",
        )
    return catalog, templates


def _manifest_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        name: manifest.get(name)
        for name in (
            "evidence_id",
            "group_id",
            "parent_key",
            "attachment_key",
            "pdf_sha256",
            "source_task_id",
        )
    }


def _inspect_target(
    group_id: int,
    parent_key: str,
    task_config: TaskConfig,
    task_path: Path,
    lock_path: Path,
    evidence_packs_dir: Path,
) -> dict[str, Any]:
    with RuntimeLock(lock_path, stale_seconds=task_config.lock_stale_seconds):
        registry = load_task_registry(task_path, group_id)
        raw_task = registry["tasks"].get(parent_key)
        if not isinstance(raw_task, dict):
            raise CardGenerationError(
                "CARD_GENERATION_TASK_NOT_FOUND",
                f"任务清单中找不到父条目：{parent_key}",
            )
        try:
            task = validate_evidence_task(raw_task, group_id)
            package_path = find_evidence_package(evidence_packs_dir, parent_key)
        except EvidencePackageError as exc:
            raise CardGenerationError(exc.code, str(exc)) from exc
        if package_path is None:
            raise CardGenerationError(
                "CARD_GENERATION_PACKAGE_MISSING",
                f"父条目 {parent_key} 尚无证据包骨架，请先运行 packages-sync",
            )
        manifest_path = package_path / "manifest.json"
        card_path = package_path / "card.md"
        if not manifest_path.is_file() or not card_path.is_file():
            raise CardGenerationError(
                "EVIDENCE_PACKAGE_INCOMPLETE",
                f"证据包缺少 manifest.json 或 card.md：{package_path}",
            )
        try:
            manifest = load_evidence_manifest(manifest_path)
            card_content = card_path.read_text(encoding="utf-8")
        except EvidencePackageError as exc:
            raise CardGenerationError(exc.code, str(exc)) from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise CardGenerationError(
                "EVIDENCE_CARD_INVALID",
                f"无法读取证据卡：{card_path}",
            ) from exc

        expected_identity = {
            "evidence_id": f"EV-{task['parent_key']}",
            "group_id": task["group_id"],
            "parent_key": task["parent_key"],
            "attachment_key": task["attachment_key"],
            "pdf_sha256": task["pdf_sha256"],
            "source_task_id": task["task_id"],
        }
        if _manifest_identity(manifest) != expected_identity:
            raise CardGenerationError(
                "EVIDENCE_INPUT_MISMATCH",
                "证据包 manifest 与当前任务输入不一致，拒绝制卡",
            )
        try:
            if recover_publication(package_path, lock_path, manifest):
                manifest = load_evidence_manifest(manifest_path)
                card_content = card_path.read_text(encoding="utf-8")
            completed = validate_saved_package(package_path)
        except EvidencePackageError as exc:
            raise CardGenerationError(exc.code, str(exc)) from exc
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise CardGenerationError("EVIDENCE_CARD_INVALID", "无法完整核对正文及生成记录；保留现有文件，不当作完成") from exc
        if completed is not None:
            return {
                "skip": True,
                "task": task,
                "task_state": raw_task.get("state"),
                "manifest": completed,
                "package_path": package_path,
                "card_path": card_path,
            }
        if raw_task.get("state") == "COMPLETED":
            raise CardGenerationError(
                "EVIDENCE_PACKAGE_INCONSISTENT",
                "任务标为完成，但证据包仍是占位卡；保留记录，不自动覆盖或重跑",
            )
        return {
            "skip": False,
            "task": task,
            "task_state": raw_task.get("state"),
            "manifest": manifest,
            "package_path": package_path,
            "card_path": card_path,
        }


def _build_prompt(
    prompt_info: dict[str, str],
    target: dict[str, Any],
    delivery: PdfDelivery,
    templates: dict[str, dict[str, Any]],
    *,
    generated_at: str,
) -> str:
    manifest = target["manifest"]
    context = {
        "evidence_id": manifest["evidence_id"],
        "title": manifest["title"],
        "zotero_group_id": manifest["group_id"],
        "zotero_parent_key": manifest["parent_key"],
        "zotero_attachment_key": manifest["attachment_key"],
        "source_pdf_sha256": manifest["pdf_sha256"],
        "source_pdf_absolute_path": str(delivery.pdf_path),
        "reading_scope": READING_SCOPE,
        "card_state": CARD_STATE,
        "generated_at": generated_at,
        "enabled_template_ids": sorted(templates),
    }
    sections = [
        prompt_info["content"].rstrip(),
        "\n## 本次任务身份\n",
        "```json\n" + json.dumps(context, ensure_ascii=False, indent=2) + "\n```",
        "\n## 已启用模板正文",
    ]
    for template_id in sorted(templates):
        sections.extend(
            [
                f'\n<evidence-card-template id="{template_id}">',
                templates[template_id]["body"].rstrip(),
                "</evidence-card-template>",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


def _headings(markdown: str) -> list[str]:
    headings = []
    fence = None
    for line in markdown.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            token, rest = marker.groups()
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not rest.strip():
                fence = None
            continue
        if fence is None and re.match(r"^#{1,6}\s+\S", line):
            # Match the attribution validator's whitespace-equivalent AI label.
            # Normalize only for checking; the saved Markdown is never rewritten.
            line = re.sub(r"^(#{1,6})[^\S\r\n]+AI[^\S\r\n]*推理[^\S\r\n]*$",
                          r"\1 AI 推理", line)
            headings.append(line.rstrip())
    return headings


def _table_count(markdown: str) -> int:
    return sum(
        1
        for line in markdown.splitlines()
        if TABLE_SEPARATOR_PATTERN.fullmatch(line)
    )


def _validate_template_structure(body: str, expected_body: str) -> dict[str, Any]:
    """Historical v1 inspection only; not invoked by current generation/export/recovery."""
    expected = _headings(expected_body)
    actual = _headings(body)
    required = [heading for heading in expected if heading.startswith("## ")]
    missing = [heading for heading in required if heading not in actual]
    if missing:
        raise CardGenerationError(
            "CARD_GENERATION_STRUCTURE_INVALID",
            "证据卡缺少必需的主要章节：" + "、".join(missing),
            diagnostic={"missing_sections": missing},
        )
    notes = []
    added = [heading for heading in actual if heading not in expected]
    omitted = [heading for heading in expected if heading not in actual]
    if added:
        notes.append({"code": "ADDITIONAL_HEADINGS", "headings": added})
    if omitted:
        notes.append({"code": "OPTIONAL_HEADINGS_CHANGED", "headings": omitted})
    if [heading for heading in actual if heading in required] != required:
        notes.append({"code": "SECTION_ORDER_OR_REPETITION_CHANGED"})
    expected_tables, actual_tables = _table_count(expected_body), _table_count(body)
    if actual_tables != expected_tables:
        notes.append({"code": "TABLE_COUNT_CHANGED", "expected": expected_tables,
                      "actual": actual_tables})
    return {
        "policy_version": "template-major-sections-v1",
        "status": "PASS_WITH_NOTES" if notes else "PASS",
        "required_section_count": len(required),
        "notes": notes,
        "scientific_correctness_verified": False,
    }


def _audit_with_structure(
    audit: dict[str, Any], output: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    enriched = {**audit, "structure_validation": output["structure_validation"]}
    return enriched, json.dumps(enriched, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _validate_model_output(
    output: Any,
    templates: dict[str, dict[str, Any]],
    *,
    title: str,
    draft_path: str | None = None,
) -> dict[str, Any]:
    try:
        return _validate_model_output_fields(output, templates, title=title)
    except CardGenerationError as exc:
        if draft_path:
            exc.diagnostic = {**(exc.diagnostic or {}), "stage": "card_output_validation",
                              "draft_path": draft_path}
        raise


def _validate_model_output_fields(
    output: Any,
    templates: dict[str, dict[str, Any]],
    *,
    title: str,
) -> dict[str, Any]:
    required_fields = MODEL_OUTPUT_FIELDS - {"classification_confidence", "classification_reason"}
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
            "CODEX_PDF_READ_UNVERIFIED",
            "Codex 未确认已经检查完整原始 PDF，拒绝写入证据卡",
        )
    source_page_count = output.get("source_page_count")
    if (
        isinstance(source_page_count, bool)
        or not isinstance(source_page_count, int)
        or not 1 <= source_page_count <= 100000
    ):
        raise CardGenerationError(
            "CODEX_PDF_READ_UNVERIFIED",
            "Codex 没有返回有效的原始 PDF 页数",
        )
    visual_content_status = output.get("visual_content_status")
    if visual_content_status not in ACCEPTED_VISUAL_CONTENT_STATUSES:
        raise CardGenerationError(
            "CODEX_PDF_VISUALS_UNVERIFIED",
            "Codex 未确认已经检查原始 PDF 的图、表和公式，拒绝写入证据卡",
        )
    source_read_evidence = output.get("source_read_evidence")
    if (
        not isinstance(source_read_evidence, str)
        or not source_read_evidence.strip()
    ):
        raise CardGenerationError(
            "CODEX_PDF_READ_UNVERIFIED",
            "Codex 没有返回可追溯的完整 PDF 阅读回执",
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
    # Template wording and Markdown are model instructions, not publication gates.
    # Keep this legacy result key explicit so existing consumers cannot read it as PASS.
    structure_validation = {"policy_version": "workflow-only-v1", "status": "NOT_CHECKED",
                            "content_validation_performed": False, "scientific_correctness_verified": False,
                            "note": "正文按模型输出保存；程序不检查模板结构、标签、编号、占位词或内容质量"}
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


def _validate_workflow_result(
    generator_result: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    workflow_report = generator_result.get("workflow")
    quality_audit = generator_result.get("quality_audit")
    if isinstance(workflow_report, dict) and workflow_report.get("protocol_version") in {SINGLE_AGENT_PROTOCOL_VERSION, LEGACY_SINGLE_AGENT_PROTOCOL_VERSION}:
        process_only = workflow_report["protocol_version"] == SINGLE_AGENT_PROTOCOL_VERSION
        access = generator_result.get("source_access")
        gates = workflow_report.get("gates", {})
        roles = quality_audit.get("roles", {}) if isinstance(quality_audit, dict) else {}
        writer = roles.get("card_writer", {}) if isinstance(roles, dict) else {}
        if (workflow_report.get("status") != ("PROCESS_VALIDATED" if process_only else "STRUCTURE_VALIDATED")
            or type(workflow_report.get("completed_role_count")) is not int
            or workflow_report["completed_role_count"] != 1
            or workflow_report.get("required_roles") != ["card_writer"]
            or not isinstance(gates, dict)
            or any(gates.get(k) is not True for k in
                   ("isolated_session", "source_identity", "reading_report_accepted",
                    "nonempty_output" if process_only else "attribution_contract"))
            or (process_only and gates.get("content_validation_performed") is not False)
            or gates.get("independent_review") is not False
            or gates.get("scientific_correctness_verified") is not False
            or not source_access_acceptable(access) or access.get("method") != "local_pdf_path"
            or not isinstance(quality_audit, dict) or quality_audit.get("quality_report") != workflow_report
            or not isinstance(roles, dict) or set(roles) != {"card_writer"} or not isinstance(writer, dict)
            or not isinstance(writer.get("execution"), dict)
            or writer.get("execution", {}).get("isolated") is not True
            or writer.get("execution", {}).get("source_access") != access
            or not isinstance(generator_result.get("output"), dict)
            or writer.get("output") != generator_result.get("output")
            or quality_audit.get("source_pdf_sha256") != access["source_sha256"]):
            raise CardGenerationError("CARD_QUALITY_UNVERIFIED", "单 Agent 生成记录不完整或错误声称独立复核")
        body = generator_result["output"].get("card_body_markdown")
        if not isinstance(body, str) or not body.strip():
            raise CardGenerationError("CARD_GENERATION_OUTPUT_INVALID", "模型没有返回可保存的 Markdown 正文")
        return workflow_report, quality_audit, json.dumps(quality_audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    required_quality_gates = {
        "isolated_required_roles",
        "dual_fact_extraction",
        "source_grounded_adjudication",
        "critical_analysis_grounded",
        "adversarial_review_passed",
        "fail_closed",
    }
    direct = isinstance(workflow_report, dict) and workflow_report.get("protocol_version") == LOCAL_PATH_PROTOCOL_VERSION
    required_quality_gates.update(
        {"source_identity_each_role", "reading_report_each_role"} if direct else {"full_pdf_access_each_role"})
    reported_gates = (
        workflow_report.get("gates")
        if isinstance(workflow_report, dict)
        else None
    )
    if (
        not isinstance(workflow_report, dict)
        or workflow_report.get("protocol_version") not in {MULTI_AGENT_PROTOCOL_VERSION, LOCAL_PATH_PROTOCOL_VERSION}
        or workflow_report.get("status") != "VALIDATED"
        or workflow_report.get("completed_role_count")
        != len(REQUIRED_CARD_WORKFLOW_ROLES)
        or workflow_report.get("required_roles")
        != list(REQUIRED_CARD_WORKFLOW_ROLES)
        or not isinstance(reported_gates, dict)
        or any(reported_gates.get(name) is not True for name in required_quality_gates)
        or not isinstance(quality_audit, dict)
        or quality_audit.get("quality_report") != workflow_report
    ):
        raise CardGenerationError(
            "CARD_QUALITY_UNVERIFIED",
            "制卡结果没有通过强制多 Agent 质量门禁，拒绝写入证据卡",
        )
    if direct:
        roles = quality_audit.get("roles")
        source_access = generator_result.get("source_access")
        if (not source_access_acceptable(source_access) or source_access.get("method") != "local_pdf_path"
            or reported_gates.get("full_pdf_access_each_role") is not False
            or not isinstance(roles, dict) or set(roles) != set(REQUIRED_CARD_WORKFLOW_ROLES)
            or quality_audit.get("source_pdf_sha256") != source_access["source_sha256"]):
            raise CardGenerationError("CARD_QUALITY_UNVERIFIED", "路径制卡缺少六角色来源审计或错误声明独立全文验证")
        for role in roles.values():
            execution = role.get("execution", {}) if isinstance(role, dict) else {}
            access = execution.get("source_access")
            if (execution.get("isolated") is not True
                or not source_access_acceptable(access, expected_sha256=source_access["source_sha256"],
                                                 expected_parent_key=source_access["parent_key"])
                or access.get("method") != "local_pdf_path" or access.get("page_count") != source_access["page_count"]):
                raise CardGenerationError("CARD_QUALITY_UNVERIFIED", "六角色来源或独立会话审计不一致")
    elif isinstance(generator_result.get("source_access"), dict) and generator_result["source_access"].get("method") == "local_pdf_path":
        raise CardGenerationError("CARD_QUALITY_UNVERIFIED", "路径读取结果必须使用 v2 六角色协议，不得伪装成旧 MCP 质量记录")
    quality_audit_content = (
        json.dumps(
            quality_audit,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return workflow_report, quality_audit, quality_audit_content


def _yaml_string(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _render_card(
    manifest: dict[str, Any],
    template: dict[str, Any],
    validated_output: dict[str, Any],
    catalog: dict[str, Any],
    *,
    generated_at: str,
) -> str:
    confidence_value = validated_output["classification_confidence"]
    confidence = (format(confidence_value, ".4f").rstrip("0").rstrip(".")
                  if confidence_value is not None else "unknown")
    front_matter = [
        "---",
        "schema_version: 1",
        f"template_id: {_yaml_string(validated_output['template_id'])}",
        f"template_version: {_yaml_string(template['local_version'])}",
        f"template_source_commit: {_yaml_string(catalog['source_commit'])}",
        f"evidence_id: {_yaml_string(manifest['evidence_id'])}",
        f"card_state: {_yaml_string(CARD_STATE)}",
        f"title: {_yaml_string(manifest['title'])}",
        f"zotero_group_id: {_yaml_string(manifest['group_id'])}",
        f"zotero_parent_key: {_yaml_string(manifest['parent_key'])}",
        f"zotero_attachment_key: {_yaml_string(manifest['attachment_key'])}",
        f"source_pdf_sha256: {_yaml_string(manifest['pdf_sha256'])}",
        f"source_read_status: {_yaml_string(validated_output['source_read_status'])}",
        f"source_page_count: {validated_output['source_page_count']}",
        f"visual_content_status: {_yaml_string(validated_output['visual_content_status'])}",
        f"source_read_evidence: {_yaml_string(validated_output['source_read_evidence'])}",
        f"classification_confidence: {_yaml_string(confidence)}",
        f"classification_reason: {_yaml_string(validated_output['classification_reason'])}",
        f"reading_scope: {_yaml_string(READING_SCOPE)}",
        f"generated_at: {_yaml_string(generated_at)}",
        f"updated_at: {_yaml_string(generated_at)}",
        "---",
        "",
    ]
    return "\n".join(front_matter) + validated_output["card_body_markdown"]


def _write_temporary(path: Path, content: str) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _write_generated_package(
    target: dict[str, Any],
    card_content: str,
    quality_audit_content: str,
    generated_manifest: dict[str, Any],
    task_config: TaskConfig,
    lock_path: Path,
    *,
    recovery_task_check: tuple[Path, dict[str, Any]] | None = None,
) -> None:
    package_path = target["package_path"]
    card_path = package_path / "card.md"
    manifest_path = package_path / "manifest.json"
    quality_audit_path = package_path / QUALITY_AUDIT_FILENAME
    card_temporary: Path | None = None
    manifest_temporary: Path | None = None
    quality_audit_temporary: Path | None = None
    rollback_temporary: Path | None = None
    quality_audit_written = False
    package_committed = False
    prepared_path: Path | None = None

    with RuntimeLock(lock_path, stale_seconds=task_config.lock_stale_seconds):
        if recovery_task_check is not None:
            recovery_task_path, expected_task = recovery_task_check
            current_task = load_task_registry(recovery_task_path, target["manifest"]["group_id"])["tasks"].get(expected_task["parent_key"])
            if not current_task or any(current_task.get(k) != expected_task.get(k) for k in
                                       ("state", "reason_code", "task_id", "input", "updated_at", "lease")):
                raise CardGenerationError("EVIDENCE_INPUT_MISMATCH", "恢复写入前任务已变化，保留原文件")
        try:
            current_card = card_path.read_text(encoding="utf-8")
            current_manifest = load_evidence_manifest(manifest_path)
        except EvidencePackageError as exc:
            raise CardGenerationError(exc.code, str(exc)) from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise CardGenerationError(
                "EVIDENCE_PACKAGE_WRITE_FAILED",
                "写入前无法复核现有证据包",
            ) from exc
        if current_card != PLACEHOLDER_CARD:
            raise CardGenerationError(
                "EVIDENCE_CARD_ALREADY_EXISTS",
                "card.md 已不再是占位卡，拒绝自动覆盖",
            )
        if _manifest_identity(current_manifest) != _manifest_identity(target["manifest"]):
            raise CardGenerationError(
                "EVIDENCE_INPUT_MISMATCH",
                "写入前 manifest 输入已经变化，拒绝自动覆盖",
            )
        if current_manifest.get("card_status") != "PLACEHOLDER":
            raise CardGenerationError(
                "EVIDENCE_PACKAGE_INCONSISTENT",
                "写入前 manifest 已不再是占位状态",
            )
        if quality_audit_path.exists():
            raise CardGenerationError(
                "EVIDENCE_PACKAGE_INCONSISTENT",
                "占位证据包中已存在质量审计文件，拒绝自动覆盖",
            )

        manifest_content = (
            json.dumps(
                generated_manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        try:
            card_temporary = _write_temporary(card_path, card_content)
            quality_audit_temporary = _write_temporary(
                quality_audit_path,
                quality_audit_content,
            )
            manifest_temporary = _write_temporary(manifest_path, manifest_content)
            try:
                load_evidence_manifest(manifest_temporary)
            except EvidencePackageError as exc:
                raise CardGenerationError(
                    "CARD_GENERATION_MANIFEST_INVALID",
                    "生成后的 manifest 未通过结构校验，未写入证据包",
                ) from exc
            if generated_manifest["generation"]["card_sha256"] != _sha256_text(
                card_content
            ):
                raise CardGenerationError(
                    "CARD_GENERATION_MANIFEST_INVALID",
                    "生成后的 manifest 与证据卡内容指纹不一致",
                )
            try:
                parsed_audit = json.loads(quality_audit_content)
            except json.JSONDecodeError as exc:
                raise CardGenerationError(
                    "CARD_GENERATION_AUDIT_INVALID",
                    "多 Agent 质量审计文件不是有效 JSON",
                ) from exc
            if (
                not isinstance(parsed_audit, dict)
                or parsed_audit.get("quality_report", {}).get("status")
                != generated_manifest["generation"]["quality_status"]
                or generated_manifest["generation"]["quality_audit_sha256"]
                != _sha256_text(quality_audit_content)
            ):
                raise CardGenerationError(
                    "CARD_GENERATION_AUDIT_INVALID",
                    "多 Agent 质量审计没有通过写入前校验",
                )
            try:
                prepared_path = prepare_publication(lock_path, current_manifest, generated_manifest,
                                                    card_content, quality_audit_content)
            except EvidencePackageError as exc:
                raise CardGenerationError(exc.code, str(exc)) from exc
            os.replace(quality_audit_temporary, quality_audit_path)
            quality_audit_temporary = None
            quality_audit_written = True
            os.replace(card_temporary, card_path)
            card_temporary = None
            try:
                os.replace(manifest_temporary, manifest_path)
                manifest_temporary = None
                package_committed = True
            except OSError:
                rollback_temporary = _write_temporary(card_path, PLACEHOLDER_CARD)
                os.replace(rollback_temporary, card_path)
                rollback_temporary = None
                if quality_audit_written:
                    quality_audit_path.unlink(missing_ok=True)
                    quality_audit_written = False
                raise
        except CardGenerationError:
            raise
        except OSError as exc:
            raise CardGenerationError(
                "EVIDENCE_PACKAGE_WRITE_FAILED",
                "无法安全替换证据卡和 manifest；原占位卡已尽量保留",
            ) from exc
        finally:
            if package_committed and prepared_path is not None:
                try:
                    prepared_path.unlink(missing_ok=True)
                except OSError:
                    pass  # a leftover matching record is safely reconciled next time
            if quality_audit_written and not package_committed:
                quality_audit_path.unlink(missing_ok=True)
            for temporary in (
                card_temporary,
                manifest_temporary,
                quality_audit_temporary,
                rollback_temporary,
            ):
                if temporary is not None:
                    temporary.unlink(missing_ok=True)


def _mark_retry(
    group_id: int,
    parent_key: str,
    lease_token: str,
    error: CardGenerationError,
    task_config: TaskConfig,
    task_path: Path,
    lock_path: Path,
) -> None:
    try:
        finish_task(
            group_id,
            parent_key,
            lease_token,
            task_config,
            task_path,
            lock_path,
            completed=False,
            terminal_quality_failure=(error.code.startswith("CARD_QUALITY_")
                                      or error.code == "SINGLE_CARD_CONTRACT_FAILED"),
            reason_code=error.code,
            message=str(error),
        )
    except TaskStoreError as exc:
        raise CardGenerationError(
            "CARD_GENERATION_STATE_UPDATE_FAILED",
            "制卡失败，且任务状态未能安全更新；请先检查任务清单",
        ) from exc


DeliveryPreparer = Callable[..., PdfDelivery]


def generate_evidence_card_trial(
    zotero: ZoteroConfig,
    pdf_gate: PdfGateConfig,
    task_config: TaskConfig,
    task_path: str | Path,
    lock_path: str | Path,
    evidence_packs_dir: str | Path,
    card_trials_dir: str | Path,
    templates_dir: str | Path,
    template_catalog_file: str | Path,
    prompt_file: str | Path,
    output_schema_file: str | Path,
    parent_key: str,
    adapter: CardGeneratorAdapter,
    *,
    client: ZoteroClient | None = None,
    now: datetime | None = None,
    delivery_preparer: DeliveryPreparer = prepare_pdf_delivery,
) -> dict[str, Any]:
    """Run the full quality workflow without changing card, manifest, or task state."""

    if zotero.group_id is None:
        raise CardGenerationError("CONFIG_ERROR", "试运行需要目标 Zotero 群组 ID")
    normalized_key = _normalize_parent_key(parent_key)
    task_path = Path(task_path)
    lock_path = Path(lock_path)
    evidence_packs_dir = Path(evidence_packs_dir)
    card_trials_dir = Path(card_trials_dir).resolve()
    templates_dir = Path(templates_dir).resolve()
    template_catalog_file = Path(template_catalog_file).resolve()
    prompt_file = Path(prompt_file).resolve()
    output_schema_file = Path(output_schema_file).resolve()

    target = _inspect_target(
        zotero.group_id,
        normalized_key,
        task_config,
        task_path,
        lock_path,
        evidence_packs_dir,
    )
    prompt_info = _read_prompt(prompt_file)
    catalog, templates = _load_template_bundle(
        templates_dir,
        template_catalog_file,
    )
    if not output_schema_file.is_file():
        raise CardGenerationError(
            "CARD_GENERATION_SCHEMA_INVALID",
            f"制卡输出结构文件不存在：{output_schema_file}",
        )

    try:
        delivery = delivery_preparer(
            zotero,
            pdf_gate,
            task_config,
            task_path,
            lock_path,
            evidence_packs_dir,
            normalized_key,
            client=client,
            now=now,
            allow_trial_states=True,
        )
    except PdfDeliveryError:
        raise
    generated_at = _timestamp(now)
    prompt = _build_prompt(
        prompt_info,
        target,
        delivery,
        templates,
        generated_at=generated_at,
    )
    generator_result = adapter.generate(
        prompt,
        working_directory=delivery.pdf_path.parent,
        source_pdf_path=delivery.pdf_path,
        zotero_parent_key=normalized_key,
        output_schema_path=output_schema_file,
    )
    if not generator_result.get("ok"):
        raw_error = generator_result.get("error")
        code = (
            raw_error.get("code")
            if isinstance(raw_error, dict) and isinstance(raw_error.get("code"), str)
            else "CARD_GENERATOR_FAILED"
        )
        message = (
            raw_error.get("message")
            if isinstance(raw_error, dict) and isinstance(raw_error.get("message"), str)
            else "多 Agent 证据卡试运行失败"
        )
        diagnostic = generator_result.get("diagnostic")
        raise CardGenerationError(
            code,
            message,
            diagnostic=diagnostic if isinstance(diagnostic, dict) else None,
        )
    source_access = generator_result.get("source_access")
    if not source_access_acceptable(source_access, expected_sha256=delivery.pdf_sha256,
                                    expected_parent_key=normalized_key):
        raise CardGenerationError(
            "CODEX_PDF_NOT_ACCESSED",
            "试运行的 PDF 来源或阅读记录不符合协议",
        )
    workflow_report, quality_audit, quality_audit_content = (
        _validate_workflow_result(generator_result)
    )
    validated_output = _validate_model_output(
        generator_result.get("output"),
        templates,
        title=target["manifest"]["title"],
        draft_path=generator_result.get("draft_path"),
    )
    if validated_output["source_page_count"] != source_access["page_count"]:
        raise CardGenerationError(
            "CODEX_PDF_PAGE_COUNT_MISMATCH",
            "试运行模型页数与本机 PDF 页数不一致",
        )
    template = templates[validated_output["template_id"]]
    quality_audit, quality_audit_content = _audit_with_structure(quality_audit, validated_output)
    card_content = _render_card(
        target["manifest"],
        template,
        validated_output,
        catalog,
        generated_at=generated_at,
    )
    audit_sha256 = _sha256_text(quality_audit_content)
    card_sha256 = _sha256_text(card_content)
    trial_manifest = {
        "schema_version": 1,
        "status": "VALIDATED_TRIAL",
        "structure_validation": validated_output["structure_validation"],
        "created_at": generated_at,
        "group_id": zotero.group_id,
        "parent_key": normalized_key,
        "evidence_id": target["manifest"]["evidence_id"],
        "source_pdf_sha256": target["manifest"]["pdf_sha256"],
        "workflow_protocol_version": workflow_report["protocol_version"],
        "template_id": validated_output["template_id"],
        "template_version": template["local_version"],
        "card_sha256": card_sha256,
        "quality_audit_sha256": audit_sha256,
        "production_files_modified": False,
        "task_state_modified": False,
    }
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    parent_trial_dir = card_trials_dir / normalized_key
    parent_trial_dir.mkdir(parents=True, exist_ok=True)
    trial_dir = parent_trial_dir / f"{stamp}-{audit_sha256[:8]}"
    if trial_dir.exists():
        raise CardGenerationError(
            "CARD_TRIAL_ALREADY_EXISTS",
            f"相同试运行结果目录已存在：{trial_dir}",
        )
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=".card-trial-", dir=parent_trial_dir)
    )
    try:
        (temporary_dir / "card.md").write_text(
            card_content,
            encoding="utf-8",
            newline="\n",
        )
        (temporary_dir / QUALITY_AUDIT_FILENAME).write_text(
            quality_audit_content,
            encoding="utf-8",
            newline="\n",
        )
        (temporary_dir / "trial.json").write_text(
            json.dumps(trial_manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary_dir, trial_dir)
    except OSError as exc:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise CardGenerationError(
            "CARD_TRIAL_WRITE_FAILED",
            "无法安全保存多 Agent 试运行结果",
        ) from exc

    return {
        "schema_version": 1,
        "ok": True,
        "component": "evidence_card",
        "operation": "evidence_generate_trial",
        "action": "VALIDATED_TRIAL_SAVED",
        "structure_validation": validated_output["structure_validation"],
        "production_files_modified": False,
        "task_state_modified": False,
        "group_id": zotero.group_id,
        "parent_key": normalized_key,
        "evidence_id": target["manifest"]["evidence_id"],
        "quality_status": workflow_report["status"],
        "workflow_protocol_version": workflow_report["protocol_version"],
        "template_id": validated_output["template_id"],
        "trial_path": str(trial_dir),
        "card_path": str(trial_dir / "card.md"),
        "quality_audit_path": str(trial_dir / QUALITY_AUDIT_FILENAME),
        "usage": generator_result.get("usage"),
        "quality_report": quality_audit["quality_report"],
    }


def generate_evidence_card(
    zotero: ZoteroConfig,
    pdf_gate: PdfGateConfig,
    task_config: TaskConfig,
    task_path: str | Path,
    lock_path: str | Path,
    evidence_packs_dir: str | Path,
    templates_dir: str | Path,
    template_catalog_file: str | Path,
    prompt_file: str | Path,
    output_schema_file: str | Path,
    parent_key: str,
    adapter: CardGeneratorAdapter,
    *,
    retry_quality_failed: bool = False,
    client: ZoteroClient | None = None,
    now: datetime | None = None,
    delivery_preparer: DeliveryPreparer = prepare_pdf_delivery,
) -> dict[str, Any]:
    if zotero.group_id is None:
        raise CardGenerationError("CONFIG_ERROR", "证据卡生成需要目标 Zotero 群组 ID")
    normalized_key = _normalize_parent_key(parent_key)
    task_path = Path(task_path)
    lock_path = Path(lock_path)
    evidence_packs_dir = Path(evidence_packs_dir)
    templates_dir = Path(templates_dir).resolve()
    template_catalog_file = Path(template_catalog_file).resolve()
    prompt_file = Path(prompt_file).resolve()
    output_schema_file = Path(output_schema_file).resolve()

    target = _inspect_target(
        zotero.group_id,
        normalized_key,
        task_config,
        task_path,
        lock_path,
        evidence_packs_dir,
    )
    if target["skip"]:
        return {
            "schema_version": 1,
            "ok": True,
            "component": "evidence_card",
            "operation": "evidence_generate",
            "action": "SKIPPED_EXISTING_CARD",
            "model_invoked": False,
            "group_id": zotero.group_id,
            "parent_key": normalized_key,
            "evidence_id": target["manifest"]["evidence_id"],
            "card_status": target["manifest"].get("card_status"),
            "task_state": target["task_state"],
            "card_path": str(target["card_path"].resolve()),
        }

    prompt_info = _read_prompt(prompt_file)
    catalog, templates = _load_template_bundle(
        templates_dir,
        template_catalog_file,
    )
    if not output_schema_file.is_file():
        raise CardGenerationError(
            "CARD_GENERATION_SCHEMA_INVALID",
            f"制卡输出结构文件不存在：{output_schema_file}",
        )
    output_schema_sha256 = _sha256_file(output_schema_file)

    try:
        claimed = claim_task(
            zotero.group_id,
            normalized_key,
            task_config,
            task_path,
            lock_path,
            allow_quality_failed=retry_quality_failed,
            now=now,
        )
    except TaskStoreError as exc:
        raise CardGenerationError(exc.code, str(exc)) from exc
    lease_token = claimed["lease_token"]
    package_written = False

    try:
        delivery = delivery_preparer(
            zotero,
            pdf_gate,
            task_config,
            task_path,
            lock_path,
            evidence_packs_dir,
            normalized_key,
            client=client,
            now=now,
        )
        generated_at = _timestamp(now)
        prompt = _build_prompt(
            prompt_info,
            target,
            delivery,
            templates,
            generated_at=generated_at,
        )
        generator_result = adapter.generate(
            prompt,
            working_directory=delivery.pdf_path.parent,
            source_pdf_path=delivery.pdf_path,
            zotero_parent_key=normalized_key,
            output_schema_path=output_schema_file,
        )
        if not generator_result.get("ok"):
            raw_error = generator_result.get("error")
            code = (
                raw_error.get("code")
                if isinstance(raw_error, dict) and isinstance(raw_error.get("code"), str)
                else "CARD_GENERATOR_FAILED"
            )
            message = (
                raw_error.get("message")
                if isinstance(raw_error, dict) and isinstance(raw_error.get("message"), str)
                else "证据卡模型调用失败"
            )
            diagnostic = generator_result.get("diagnostic")
            raise CardGenerationError(
                code,
                message,
                diagnostic=diagnostic if isinstance(diagnostic, dict) else None,
            )

        source_access = generator_result.get("source_access")
        if not source_access_acceptable(source_access, expected_sha256=delivery.pdf_sha256,
                                        expected_parent_key=normalized_key):
            raise CardGenerationError(
                "CODEX_PDF_NOT_ACCESSED",
                "制卡适配器的 PDF 来源或阅读记录不符合协议，拒绝写入证据卡",
            )

        workflow_report, quality_audit, _ = _validate_workflow_result(
            generator_result
        )

        validated_output = _validate_model_output(
            generator_result.get("output"),
            templates,
            title=target["manifest"]["title"],
            draft_path=generator_result.get("draft_path"),
        )
        if validated_output["source_page_count"] != source_access["page_count"]:
            raise CardGenerationError(
                "CODEX_PDF_PAGE_COUNT_MISMATCH",
                "模型返回页数与本机 PDF 页数不一致，拒绝写入证据卡",
            )
        template = templates[validated_output["template_id"]]
        _, quality_audit_content = _audit_with_structure(quality_audit, validated_output)
        quality_audit_sha256 = _sha256_text(quality_audit_content)
        card_content = _render_card(
            target["manifest"],
            template,
            validated_output,
            catalog,
            generated_at=generated_at,
        )
        generated_manifest = deepcopy(target["manifest"])
        generated_manifest["card_status"] = CARD_STATE
        generated_manifest["updated_at"] = generated_at
        generated_manifest["generation"] = {
            "generator_adapter": generator_result.get("adapter"),
            "generator_protocol_version": generator_result.get(
                "generation_protocol_version",
                GENERATION_PROTOCOL_VERSION,
            ),
            "cli_version": generator_result.get("cli_version"),
            "model": generator_result.get("configured_model") or "codex_default",
            "reasoning_effort": (
                generator_result.get("configured_reasoning_effort") or "model_default"
            ),
            "prompt_version": prompt_info["version"],
            "prompt_sha256": prompt_info["sha256"],
            "output_schema_version": OUTPUT_SCHEMA_VERSION,
            "output_schema_sha256": output_schema_sha256,
            "template_catalog_version": catalog["catalog_version"],
            "template_id": validated_output["template_id"],
            "template_version": template["local_version"],
            "template_source_commit": catalog["source_commit"],
            "template_content_sha256": template["content_sha256"],
            "classification_confidence": validated_output[
                "classification_confidence"
            ],
            "classification_reason": validated_output["classification_reason"],
            "reading_scope": READING_SCOPE,
            "source_access_verified": source_access["verified"],
            "source_access_method": source_access["method"],
            "source_access_server": source_access.get("server_name"),
            "source_access_receipt_schema_version": source_access.get(
                "receipt_schema_version"
            ),
            "source_pages_served": source_access.get("pages_served"),
            "source_visual_pages_served": source_access.get("visual_pages_served"),
            "source_read_status": validated_output["source_read_status"],
            "source_page_count": validated_output["source_page_count"],
            "visual_content_status": validated_output["visual_content_status"],
            "source_read_evidence": validated_output["source_read_evidence"],
            "generated_at": generated_at,
            "card_sha256": _sha256_text(card_content),
            "quality_status": workflow_report["status"],
            "workflow_protocol_version": workflow_report["protocol_version"],
            "workflow_role_count": workflow_report["completed_role_count"],
            "quality_audit_file": QUALITY_AUDIT_FILENAME,
            "quality_audit_sha256": quality_audit_sha256,
            "usage": generator_result.get("usage"),
        }
        if source_access["method"] == "local_pdf_path":
            generated_manifest["generation"]["source_access"] = source_access
        _write_generated_package(
            target,
            card_content,
            quality_audit_content,
            generated_manifest,
            task_config,
            lock_path,
        )
        package_written = True
        try:
            completed = finish_task(
                zotero.group_id,
                normalized_key,
                lease_token,
                task_config,
                task_path,
                lock_path,
                completed=True,
                reason_code="CARD_GENERATED",
                message="粗证据卡已通过流程检查并写入证据包；未校验正文内容质量",
                now=now,
            )
        except TaskStoreError as exc:
            raise CardGenerationError(
                "CARD_GENERATION_STATE_UPDATE_FAILED",
                "证据卡已写入，但任务状态未能标记完成；请勿再次制卡",
            ) from exc

        return {
            "schema_version": 1,
            "ok": True,
            "component": "evidence_card",
            "operation": "evidence_generate",
            "action": "GENERATED",
            "structure_validation": validated_output["structure_validation"],
            "model_invoked": True,
            "group_id": zotero.group_id,
            "parent_key": normalized_key,
            "evidence_id": target["manifest"]["evidence_id"],
            "card_status": CARD_STATE,
            "template_id": validated_output["template_id"],
            "template_version": template["local_version"],
            "classification_confidence": validated_output[
                "classification_confidence"
            ],
            "classification_reason": validated_output["classification_reason"],
            "source_read_status": validated_output["source_read_status"],
            "source_page_count": validated_output["source_page_count"],
            "visual_content_status": validated_output["visual_content_status"],
            "task_state": completed["task"]["state"],
            "model": generator_result.get("configured_model") or "codex_default",
            "reasoning_effort": (
                generator_result.get("configured_reasoning_effort") or "model_default"
            ),
            "prompt_version": prompt_info["version"],
            "quality_status": workflow_report["status"],
            "workflow_protocol_version": workflow_report["protocol_version"],
            "card_path": str((target["package_path"] / "card.md").resolve()),
            "manifest_path": str(
                (target["package_path"] / "manifest.json").resolve()
            ),
            "quality_audit_path": str(
                (target["package_path"] / QUALITY_AUDIT_FILENAME).resolve()
            ),
            "usage": generator_result.get("usage"),
        }
    except CardGenerationError as error:
        if package_written:
            raise
        _mark_retry(
            zotero.group_id,
            normalized_key,
            lease_token,
            error,
            task_config,
            task_path,
            lock_path,
        )
        raise
    except (PdfDeliveryError, EvidencePackageError, EvidenceTemplateError) as exc:
        error = CardGenerationError(exc.code, str(exc))
        _mark_retry(
            zotero.group_id,
            normalized_key,
            lease_token,
            error,
            task_config,
            task_path,
            lock_path,
        )
        raise error from exc
