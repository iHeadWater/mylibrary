from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


CATALOG_SCHEMA_VERSION = 1
SHA1_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SEMVER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
TEMPLATE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PLACEHOLDER_PATTERN = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")

REQUIRED_TEMPLATE_FIELDS = {
    "template_id": None,
    "template_version": None,
    "template_source_commit": None,
    "evidence_id": "{{EVIDENCE_ID}}",
    "card_state": "{{CARD_STATE}}",
    "title": "{{TITLE}}",
    "zotero_group_id": "{{ZOTERO_GROUP_ID}}",
    "zotero_parent_key": "{{ZOTERO_PARENT_KEY}}",
    "zotero_attachment_key": "{{ZOTERO_ATTACHMENT_KEY}}",
    "source_pdf_sha256": "{{PDF_SHA256}}",
    "classification_confidence": "{{CLASSIFICATION_CONFIDENCE}}",
    "classification_reason": "{{CLASSIFICATION_REASON}}",
    "reading_scope": "{{READING_SCOPE}}",
    "generated_at": "{{GENERATED_AT}}",
    "updated_at": "{{GENERATED_AT}}",
}


class EvidenceTemplateError(ValueError):
    """Raised when the evidence-card template catalog is unsafe or invalid."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _non_empty_string(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_CATALOG_INVALID",
            f"{name} 必须是非空字符串",
        )
    return value.strip()


def _read_catalog(catalog_file: Path) -> dict[str, Any]:
    try:
        data = json.loads(catalog_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_CATALOG_NOT_FOUND",
            f"模板目录清单不存在：{catalog_file}",
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_CATALOG_INVALID",
            f"模板目录清单不是有效 JSON：{catalog_file}（{exc}）",
        ) from exc
    if not isinstance(data, dict):
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_CATALOG_INVALID",
            "模板目录清单根节点必须是 JSON 对象",
        )
    if data.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_CATALOG_INVALID",
            f"当前仅支持模板目录 schema_version={CATALOG_SCHEMA_VERSION}",
        )
    return data


def _read_front_matter(template_file: Path, content: str) -> dict[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_INVALID",
            f"模板缺少开头 YAML front matter：{template_file.name}",
        )
    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration as exc:
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_INVALID",
            f"模板 front matter 没有结束标记：{template_file.name}",
        ) from exc

    metadata: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:closing_index], start=2):
        if not line.strip():
            continue
        if ":" not in line:
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_INVALID",
                f"模板 front matter 第 {line_number} 行无法解析：{template_file.name}",
            )
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if value.startswith(('"', "'")) and value.endswith(value[:1]) and len(value) >= 2:
            value = value[1:-1]
        if not key or key in metadata:
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_INVALID",
                f"模板 front matter 字段为空或重复：{template_file.name}",
            )
        metadata[key] = value
    return metadata


def _resolve_template_file(templates_dir: Path, relative_file: str) -> Path:
    candidate = (templates_dir / relative_file).resolve()
    if not candidate.is_relative_to(templates_dir):
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_PATH_INVALID",
            f"模板文件不得离开模板目录：{relative_file}",
        )
    if candidate.suffix.casefold() != ".md":
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_PATH_INVALID",
            f"证据卡模板必须是 Markdown 文件：{relative_file}",
        )
    return candidate


def _validate_template_content(
    template_file: Path,
    *,
    content: str,
    template_id: str,
    local_version: str,
    source_commit: str,
) -> list[str]:
    metadata = _read_front_matter(template_file, content)
    expected_fields = {
        **REQUIRED_TEMPLATE_FIELDS,
        "template_id": template_id,
        "template_version": local_version,
        "template_source_commit": source_commit,
    }
    for name, expected in expected_fields.items():
        if name not in metadata:
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_INVALID",
                f"模板缺少必填字段 {name}：{template_file.name}",
            )
        if expected is not None and metadata[name] != expected:
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_INVALID",
                f"模板字段 {name} 与目录清单不一致：{template_file.name}",
            )
    if not any(line.startswith("# ") for line in content.splitlines()):
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_INVALID",
            f"模板缺少一级标题：{template_file.name}",
        )
    return sorted(set(PLACEHOLDER_PATTERN.findall(content)))


def validate_evidence_templates(
    templates_dir: str | Path,
    catalog_file: str | Path,
) -> dict[str, Any]:
    templates_root = Path(templates_dir).resolve()
    catalog_path = Path(catalog_file).resolve()
    if not catalog_path.is_relative_to(templates_root):
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_PATH_INVALID",
            "模板目录清单必须位于证据卡模板目录内",
        )

    catalog = _read_catalog(catalog_path)
    catalog_version = _non_empty_string(
        catalog.get("catalog_version"), name="catalog_version"
    )
    if not SEMVER_PATTERN.fullmatch(catalog_version):
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_CATALOG_INVALID",
            "catalog_version 必须使用 x.y.z 格式",
        )

    source = catalog.get("source")
    if not isinstance(source, dict):
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_CATALOG_INVALID",
            "source 必须是 JSON 对象",
        )
    source_repository = _non_empty_string(
        source.get("repository"), name="source.repository"
    )
    source_commit = _non_empty_string(source.get("commit"), name="source.commit")
    if not SHA1_PATTERN.fullmatch(source_commit):
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_CATALOG_INVALID",
            "source.commit 必须是 40 位小写 Git SHA-1",
        )
    _non_empty_string(source.get("license_status"), name="source.license_status")
    _non_empty_string(
        source.get("authorization_basis"), name="source.authorization_basis"
    )

    raw_templates = catalog.get("templates")
    if not isinstance(raw_templates, list) or not raw_templates:
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_CATALOG_INVALID",
            "templates 必须是非空数组",
        )
    raw_required_ids = catalog.get("required_template_ids")
    if not isinstance(raw_required_ids, list) or not raw_required_ids:
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_CATALOG_INVALID",
            "required_template_ids 必须是非空数组",
        )
    required_ids: set[str] = set()
    for index, raw_template_id in enumerate(raw_required_ids):
        required_id = _non_empty_string(
            raw_template_id,
            name=f"required_template_ids[{index}]",
        )
        if not TEMPLATE_ID_PATTERN.fullmatch(required_id):
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_CATALOG_INVALID",
                f"模板 ID 必须使用小写 kebab-case：{required_id}",
            )
        if required_id in required_ids:
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_DUPLICATE",
                f"required_template_ids 中的模板 ID 重复：{required_id}",
            )
        required_ids.add(required_id)

    seen_ids: set[str] = set()
    seen_files: set[Path] = set()
    validated_templates: list[dict[str, Any]] = []
    for index, raw_template in enumerate(raw_templates):
        prefix = f"templates[{index}]"
        if not isinstance(raw_template, dict):
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_CATALOG_INVALID",
                f"{prefix} 必须是 JSON 对象",
            )
        template_id = _non_empty_string(
            raw_template.get("template_id"), name=f"{prefix}.template_id"
        )
        if not TEMPLATE_ID_PATTERN.fullmatch(template_id):
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_CATALOG_INVALID",
                f"模板 ID 必须使用小写 kebab-case：{template_id}",
            )
        if template_id in seen_ids:
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_DUPLICATE",
                f"模板 ID 重复：{template_id}",
            )
        seen_ids.add(template_id)

        local_version = _non_empty_string(
            raw_template.get("local_version"), name=f"{prefix}.local_version"
        )
        if not SEMVER_PATTERN.fullmatch(local_version):
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_CATALOG_INVALID",
                f"模板 {template_id} 的 local_version 必须使用 x.y.z 格式",
            )
        if not isinstance(raw_template.get("enabled"), bool):
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_CATALOG_INVALID",
                f"模板 {template_id} 的 enabled 必须是布尔值",
            )

        relative_file = _non_empty_string(
            raw_template.get("file"), name=f"{prefix}.file"
        )
        template_file = _resolve_template_file(templates_root, relative_file)
        if template_file in seen_files:
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_DUPLICATE",
                f"多个模板指向同一文件：{relative_file}",
            )
        seen_files.add(template_file)
        try:
            content = template_file.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_NOT_FOUND",
                f"模板文件不存在：{relative_file}",
            ) from exc
        except UnicodeDecodeError as exc:
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_INVALID",
                f"模板文件必须使用 UTF-8 编码：{relative_file}",
            ) from exc

        source_path = _non_empty_string(
            raw_template.get("source_path"), name=f"{prefix}.source_path"
        )
        source_blob_sha = _non_empty_string(
            raw_template.get("source_blob_sha"), name=f"{prefix}.source_blob_sha"
        )
        if not SHA1_PATTERN.fullmatch(source_blob_sha):
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_CATALOG_INVALID",
                f"模板 {template_id} 的 source_blob_sha 必须是 40 位小写 Git SHA-1",
            )
        content_sha256 = _non_empty_string(
            raw_template.get("content_sha256"), name=f"{prefix}.content_sha256"
        )
        if not SHA256_PATTERN.fullmatch(content_sha256):
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_CATALOG_INVALID",
                f"模板 {template_id} 的 content_sha256 必须是 64 位小写 SHA-256",
            )
        actual_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual_sha256 != content_sha256:
            raise EvidenceTemplateError(
                "EVIDENCE_TEMPLATE_HASH_MISMATCH",
                f"模板内容已变化但目录清单未更新：{relative_file}",
            )

        placeholders = _validate_template_content(
            template_file,
            content=content,
            template_id=template_id,
            local_version=local_version,
            source_commit=source_commit,
        )
        validated_templates.append(
            {
                "template_id": template_id,
                "local_version": local_version,
                "enabled": raw_template["enabled"],
                "file": relative_file,
                "source_path": source_path,
                "source_blob_sha": source_blob_sha,
                "content_sha256": content_sha256,
                "placeholders": placeholders,
            }
        )

    if seen_ids != required_ids:
        missing = sorted(required_ids - seen_ids)
        undeclared = sorted(seen_ids - required_ids)
        details: list[str] = []
        if missing:
            details.append(f"缺少：{', '.join(missing)}")
        if undeclared:
            details.append(f"未声明：{', '.join(undeclared)}")
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_CATALOG_INVALID",
            "templates 与 required_template_ids 不一致（" + "；".join(details) + "）",
        )

    enabled_count = sum(1 for item in validated_templates if item["enabled"])
    if enabled_count == 0:
        raise EvidenceTemplateError(
            "EVIDENCE_TEMPLATE_CATALOG_INVALID",
            "至少需要启用一个证据卡模板",
        )

    return {
        "schema_version": 1,
        "ok": True,
        "component": "evidence_templates",
        "catalog_version": catalog_version,
        "source_repository": source_repository,
        "source_commit": source_commit,
        "template_count": len(validated_templates),
        "enabled_count": enabled_count,
        "templates": validated_templates,
        "templates_dir": str(templates_root),
        "catalog_path": str(catalog_path),
    }
