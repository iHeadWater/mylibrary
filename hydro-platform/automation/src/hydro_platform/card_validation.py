"""Deterministic subject-card gate (#31), not scientific verification or publication."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from hydro_platform.card_draft import KEY, SHA256, PROMPT, SCHEMA, SINGLE_SOURCE_TEMPLATES
from hydro_platform.card_generation import (
    CardGenerationError, _load_template_bundle, _read_prompt, build_template_prompt,
)
from hydro_platform.evidence_templates import EvidenceTemplateError
from hydro_platform.publication import atomic_text

POLICY = "subject-card-validation-v1"
FIELDS = ("research_questions", "study_objects_and_scales", "data_and_methods",
          "comparison_baselines", "findings", "boundaries", "missing_information")
FINDING = re.compile(r"F[0-9]{3,}")
PLACEHOLDERS = {"", "-", "—", "todo", "tbd", "n/a", "待补", "待填写", "待补充", "未填写",
                "未报告", "不适用", "not reported", "not applicable"}


class CardValidationError(RuntimeError):
    def __init__(self, code, message, *, report=None):
        super().__init__(message)
        self.code, self.report = code, report


def fingerprint(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _time(value):
    try:
        return isinstance(value, str) and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _content(value):
    return (_text(value) and value.strip().casefold().rstrip("。.") not in PLACEHOLDERS
            and not re.fullmatch(r"\{\{[A-Za-z_][A-Za-z_0-9]*\}\}", value.strip()))


def _shape(value, schema, path, add):
    types = schema["type"]
    if isinstance(types, list):
        if value is None and "null" in types:
            return
        types = next(t for t in types if t != "null")
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list),
             "string": isinstance(value, str), "integer": type(value) is int}.get(types, False)
    if not valid:
        add("CARD_FIELD_TYPE", path, f"字段必须为 {types}")
        return
    if "enum" in schema and value not in schema["enum"]:
        add("CARD_FIELD_ENUM", path, "字段不属于协议允许的值")
    if types == "object":
        props = schema["properties"]
        for key, child in props.items():
            if key not in value:
                add("CARD_FIELD_MISSING", f"{path}/{key}", "缺少必要字段")
            else:
                _shape(value[key], child, f"{path}/{key}", add)
        for key in sorted(value.keys() - props.keys()):
            add("CARD_FIELD_UNKNOWN", f"{path}/{key}", "存在协议外字段")
    elif types == "array":
        for i, child in enumerate(value):
            _shape(child, schema["items"], f"{path}/{i}", add)


def _input_identity(record, add):
    if not isinstance(record, dict):
        add("CARD_INPUT_INVALID", "/paper_input", "需要 #29 的单篇 READY 记录")
        return None
    if type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        add("CARD_INPUT_VERSION", "/paper_input/schema_version", "仅支持输入协议版本 1")
    if (record.get("operation") != "paper_input" or record.get("ok") is not True
        or record.get("status") != "READY" or type(record.get("pdf_attachment_count")) is not int
        or record["pdf_attachment_count"] != 1):
        add("CARD_INPUT_INVALID", "/paper_input", "输入必须为单篇单 PDF READY 记录")
    library, item, pdf = (record.get(k) for k in ("library", "item", "pdf"))
    if not all(isinstance(v, dict) for v in (library, item, pdf)):
        add("CARD_INPUT_INVALID", "/paper_input", "缺少文库、论文或 PDF 身份")
        return None
    if (library.get("type") not in ("user", "group") or type(library.get("id")) is not int
        or library["id"] < 0 or (library["type"] == "group" and library["id"] == 0)):
        add("CARD_INPUT_INVALID", "/paper_input/library", "文库身份无效")
    parent, attachment, requested = item.get("item_key"), pdf.get("attachment_key"), record.get("requested_item_key")
    if (not all(isinstance(k, str) and KEY.fullmatch(k) for k in (parent, attachment, requested))
        or parent == attachment or pdf.get("parent_key") != parent or requested not in (parent, attachment)
        or not _text(item.get("title")) or not isinstance(pdf.get("sha256"), str)
        or not SHA256.fullmatch(pdf["sha256"]) or type(pdf.get("file_size_bytes")) is not int
        or pdf["file_size_bytes"] < 1 or not _text(pdf.get("local_path"))
        or not Path(pdf["local_path"]).is_absolute()):
        add("CARD_INPUT_INVALID", "/paper_input", "输入身份、大小、哈希或路径无效")
        return None
    return {"library": library, "parent_key": parent, "requested_item_key": requested,
            "attachment_key": attachment, "pdf_sha256": pdf["sha256"],
            "pdf_size_bytes": pdf["file_size_bytes"], "item": item}


def _provenance(config, draft, record, identity, add):
    """Compare recorded versions with the actual configured assets, not a model claim."""
    catalog, templates = _load_template_bundle(config.paths.evidence_card_templates_dir,
                                              config.paths.evidence_card_template_catalog_file)
    templates = {k: v for k, v in templates.items() if k in SINGLE_SOURCE_TEMPLATES}
    base = _read_prompt(config.paths.evidence_card_generation_prompt_file)
    supplement = _read_prompt(PROMPT)
    reading = _read_prompt(config.card_generator.pdf_direct_trial.reading_prompt_file)
    provenance = draft.get("provenance")
    if not isinstance(provenance, dict):
        add("CARD_PROVENANCE_MISSING", "/provenance", "缺少提示词和模板版本信息")
        return
    expected = {
        "prompt_version": base["version"], "prompt_sha256": base["sha256"],
        "draft_prompt_version": supplement["version"], "draft_prompt_sha256": supplement["sha256"],
        "reading_prompt_version": reading["version"], "reading_prompt_sha256": reading["sha256"],
        "output_schema_sha256": hashlib.sha256(SCHEMA.read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
        "catalog_version": catalog["catalog_version"], "generation_protocol_version": "codex-local-pdf-v1",
    }
    tid = provenance.get("template_id")
    template = templates.get(tid) if isinstance(tid, str) else None
    if template is None:
        add("CARD_TEMPLATE_INVALID", "/provenance/template_id", "不是当前启用的单来源模板")
    else:
        expected.update(template_version=template["local_version"], template_sha256=template["content_sha256"])
    if identity is not None:
        context = {
            "library": record["library"], "item": record["item"],
            "zotero_parent_key": identity["parent_key"], "zotero_attachment_key": identity["attachment_key"],
            "source_pdf_sha256": identity["pdf_sha256"],
            "source_pdf_absolute_path": str(Path(record["pdf"]["local_path"]).resolve()),
            "reading_scope": "FULL_PDF", "card_state": "DRAFT_PENDING_VALIDATION",
            "enabled_template_ids": sorted(templates),
        }
        prompt = build_template_prompt(base, context, templates) + "\n" + supplement["content"]
        expected["combined_prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    for key, value in expected.items():
        if key not in provenance:
            add("CARD_PROVENANCE_MISSING", f"/provenance/{key}", "缺少版本或指纹")
        elif provenance[key] != value:
            add("CARD_VERSION_MISMATCH", f"/provenance/{key}", "记录与当前输入或配置的版本不一致")


def validate_subject_card(config, draft, paper_input):
    """Pure with respect to input artifacts: read assets, return a report, never invoke AI."""
    errors, warnings = [], []
    def add(code, path, message, **details):
        errors.append({"code": code, "path": path, "message": message, **details})

    report = {
        "schema_version": 1, "operation": "subject_card_validation",
        "validation_id": uuid.uuid4().hex, "validated_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": POLICY,
        "validator_sha256": hashlib.sha256(Path(__file__).read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
        "ok": False, "status": "FAIL", "eligible_for_theme_generation": False,
        "content_validation_performed": True,
        "scientific_correctness_verified": False, "production_eligible": False,
        "errors": errors, "warnings": warnings,
    }
    try:
        report["draft_sha256"], report["input_sha256"] = fingerprint(draft), fingerprint(paper_input)
    except (ValueError, TypeError, OverflowError, RecursionError):
        add("CARD_JSON_INVALID", "/", "输入必须是可规范化的有限 JSON")
        return report
    identity = _input_identity(paper_input, add)
    if not isinstance(draft, dict):
        add("CARD_DRAFT_INVALID", "/", "主体卡草稿必须为对象")
        return report
    report["draft_id"] = draft.get("draft_id")
    report["draft_schema_version"] = draft.get("schema_version")
    report["input_schema_version"] = paper_input.get("schema_version") if isinstance(paper_input, dict) else None
    if type(draft.get("schema_version")) is not int or draft["schema_version"] != 1:
        add("CARD_DRAFT_VERSION", "/schema_version", "仅支持主体卡草稿协议版本 1")
    if not isinstance(draft.get("draft_id"), str) or not re.fullmatch(r"[a-f0-9]{16}", draft["draft_id"]):
        add("CARD_DRAFT_INVALID", "/draft_id", "缺少有效的草稿版本标识")
    if not _time(draft.get("created_at")):
        add("CARD_DRAFT_INVALID", "/created_at", "缺少带时区的生成时间")
    if (draft.get("status") != "DRAFT_PENDING_VALIDATION"
        or any(draft.get(k) is not False for k in
               ("content_validation_performed", "scientific_correctness_verified", "production_eligible"))):
        add("CARD_DRAFT_STATE", "/status", "校验输入必须是未发布的待校验草稿，不能自行声称通过")
    source = draft.get("source")
    if not isinstance(source, dict):
        source = {}
        add("CARD_SOURCE_MISMATCH", "/source", "缺少来源身份")
    if identity is not None:
        for key, value in identity.items():
            if fingerprint(source.get(key)) != fingerprint(value):
                add("CARD_SOURCE_MISMATCH", f"/source/{key}", "来源与单篇输入记录不一致")
    pages = source.get("pdf_page_count")
    if type(pages) is not int or not 1 <= pages <= 100000:
        add("CARD_LOCATION_INVALID", "/source/pdf_page_count", "PDF 总页数无效")
        pages = 0
    access = draft.get("reading_record")
    if (not isinstance(access, dict) or access.get("source_sha256") != source.get("pdf_sha256")
        or access.get("parent_key") != source.get("parent_key")
        or type(access.get("page_count")) is not int or access["page_count"] != pages
        or access.get("method") != "local_pdf_path"
        or any(access.get(k) is not True for k in ("source_identity_verified", "source_unchanged",
                                                  "model_reading_report_accepted"))):
        add("CARD_READING_RECORD_INVALID", "/reading_record", "阅读记录与草稿来源不一致或未被接受")
    body = draft.get("card_body_markdown")
    visible = re.sub(r"<!--.*?-->|(?m:^[ \t]*#{1,6}[ \t]+[^\r\n]*$)", "", body, flags=re.S) if isinstance(body, str) else ""
    if not _content(visible):
        add("CARD_CONTENT_MISSING", "/card_body_markdown", "缺少可读正文或仅有占位内容")
    elif len(visible.strip()) < 300:
        warnings.append({"code": "CARD_TEXT_SHORT", "path": "/card_body_markdown",
                         "message": "正文较短，请关注信息覆盖；字数不决定是否通过"})
    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))["properties"]["machine_fields"]
        fields = draft.get("machine_fields")
        _shape(fields, schema, "/machine_fields", add)
        fields = fields if isinstance(fields, dict) else {}
        ids = set()
        for category in FIELDS:
            rows = fields.get(category)
            path = f"/machine_fields/{category}"
            if not isinstance(rows, list) or not rows:
                add("CARD_CONTENT_MISSING", path, "必须提供内容；未报告或不适用时提供原因记录")
                continue
            for i, row in enumerate(rows):
                entry = f"{path}/{i}"
                if not isinstance(row, dict):
                    continue
                if not _content(row.get("statement")):
                    add("CARD_CONTENT_MISSING", entry + "/statement", "陈述为空、占位符或只有缺失标签而无说明")
                status, role, locations = (row.get(k) for k in ("information_status", "statement_role", "source_locations"))
                if status in ("not_reported", "not_applicable", "unavailable") and role != "information_boundary":
                    add("CARD_INFORMATION_BOUNDARY", entry, "缺失或不适用信息必须明确标为信息边界")
                if status == "reported" and (not isinstance(locations, list) or not locations):
                    add("CARD_LOCATION_REQUIRED", entry + "/source_locations", "已报告的陈述必须提供原文位置")
                if isinstance(locations, list):
                    for j, location in enumerate(locations):
                        if not isinstance(location, dict):
                            continue
                        locpath = entry + f"/source_locations/{j}"
                        page = location.get("pdf_page")
                        if ((page is not None or status == "reported")
                            and (type(page) is not int or not 1 <= page <= pages)):
                            add("CARD_LOCATION_INVALID", locpath + "/pdf_page", "原文页码必须在 PDF 物理页范围内")
                        for key in ("section", "figure", "table"):
                            if location.get(key) is not None and not _text(location[key]):
                                add("CARD_LOCATION_INVALID", locpath + "/" + key, "原文位置必须为非空文本或 null")
                if category == "findings":
                    fid = row.get("finding_id")
                    if not isinstance(fid, str) or not FINDING.fullmatch(fid) or fid in ids:
                        add("CARD_FINDING_ID_INVALID", entry + "/finding_id", "结果编号必须是唯一的 F001 格式")
                    else:
                        ids.add(fid)
        body_ids = set(re.findall(r"(?<![A-Za-z0-9])F[0-9]{3,}(?![A-Za-z0-9])", visible)) if isinstance(body, str) else set()
        for fid in sorted(ids - body_ids):
            add("CARD_FINDING_REFERENCE", "/card_body_markdown", f"正文没有引用机器结果 {fid}", finding_id=fid)
        for fid in sorted(body_ids - ids):
            add("CARD_FINDING_REFERENCE", "/card_body_markdown", f"正文引用了未定义的结果 {fid}", finding_id=fid)
        _provenance(config, draft, paper_input, identity, add)
    except (OSError, ValueError, KeyError, CardGenerationError, EvidenceTemplateError) as exc:
        add("CARD_RULESET_UNAVAILABLE", "/provenance", f"无法读取校验所需协议或版本资产：{type(exc).__name__}")
    report.update(ok=not errors, status="FAIL" if errors else "PASS",
                  eligible_for_theme_generation=not errors)
    return report


def _read_json(path):
    def invalid_constant(value):
        raise ValueError("非有限 JSON 常量")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("重复 JSON 键")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      parse_constant=invalid_constant, object_pairs_hook=unique)


def validate_subject_card_file(config, draft_path, input_path):
    """Save only an append-only validation record; the draft remains byte-identical."""
    try:
        path = Path(draft_path).resolve(strict=True)
        draft, record = _read_json(path), _read_json(input_path)
        report = validate_subject_card(config, draft, record)
        directory = path.parent / "validations"
        if not directory.resolve().is_relative_to(path.parent):
            raise OSError("校验记录目录越界")
        # A unique directory avoids overwriting any existing record, even on collision.
        directory = directory / report["validation_id"]
        directory.mkdir(parents=True, exist_ok=False)
        target = directory / "validation.json"
        atomic_text(target, json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        return {**report, "validation_path": str(target)}
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return {"schema_version": 1, "operation": "subject_card_validation", "ok": False, "status": "FAIL",
                "eligible_for_theme_generation": False, "content_validation_performed": False,
                "scientific_correctness_verified": False, "production_eligible": False, "errors": [{"code": "CARD_VALIDATION_IO",
                "path": "/", "message": f"无法读取输入或保存校验记录：{type(exc).__name__}"}], "warnings": []}


def load_validated_subject_card(config, draft_path, input_path, validation_path):
    """Downstream gate: recheck current bytes and rules; never trust a PASS label alone."""
    try:
        draft, record, saved = _read_json(draft_path), _read_json(input_path), _read_json(validation_path)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise CardValidationError("CARD_VALIDATION_REQUIRED", "缺少可读取的草稿、输入或校验记录") from exc
    fresh = validate_subject_card(config, draft, record)
    if not fresh["ok"]:
        raise CardValidationError("CARD_VALIDATION_FAILED", "当前草稿未通过校验，禁止进入主题流程", report=fresh)
    binding = ("schema_version", "operation", "policy_version", "validator_sha256",
               "draft_id", "draft_schema_version", "input_schema_version", "draft_sha256", "input_sha256",
               "ok", "status", "eligible_for_theme_generation", "scientific_correctness_verified",
               "production_eligible", "content_validation_performed", "errors", "warnings")
    if (not isinstance(saved, dict) or any(type(saved.get(k)) is not type(fresh[k]) or saved.get(k) != fresh[k] for k in binding)
        or not isinstance(saved.get("validation_id"), str) or not re.fullmatch(r"[a-f0-9]{32}", saved["validation_id"])
        or not _time(saved.get("validated_at"))):
        raise CardValidationError("CARD_VALIDATION_STALE", "校验记录缺失、未通过或与当前草稿/输入/规则不一致")
    return {"draft": deepcopy(draft), "validation": deepcopy(saved)}
