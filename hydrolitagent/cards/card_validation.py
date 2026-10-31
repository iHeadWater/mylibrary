"""Deterministic subject-card gate (#31), not scientific verification or publication."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from copy import deepcopy
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

from hydrolitagent.cards.application.card_draft import (
    KEY, PROMPT, SCHEMA, SHA256, SINGLE_SOURCE_TEMPLATES,
)
from hydrolitagent.cards._paths import ASSETS_DIR, PROMPTS_DIR, SCHEMAS_DIR
from hydrolitagent.cards.application.prompts import (
    build_template_prompt, load_template_bundle, read_prompt,
)
from hydrolitagent.cards.domain.errors import CardGenerationError
from hydrolitagent.cards.domain.grounding import cited_pages
from hydrolitagent.cards.evidence_templates import EvidenceTemplateError
from hydrolitagent.cards.publication import atomic_text
from hydrolitagent.cards.domain.protocol import MARKDOWN_CARD_PROTOCOL_VERSION
from hydrolitagent.cards.domain.source_access import (
    CLAUDE_PDF_READ,
    CURRENT_METHODS,
    LOCAL_PDF_PATH,
    MARKDOWN_PREPARED,
    source_access_acceptable,
)

POLICY = "subject-card-validation-v1"
POLICY_MARKDOWN = "subject-card-validation-v2"
MARKDOWN_DRAFT_SCHEMA_VERSION = 2
LEGACY_READ_ONLY = "LEGACY_READ_ONLY"
# A v2 provenance record must carry these; ``combined_prompt_sha256`` cannot be
# recomputed from the input record alone because the prompt embeds the prepared
# paper's canaries and page anchors.
MARKDOWN_PROVENANCE_FIELDS = (
    "prompt_version", "prompt_sha256", "draft_prompt_version", "draft_prompt_sha256",
    "combined_prompt_sha256", "output_schema_sha256", "template_id", "template_version",
    "template_sha256", "catalog_version", "converter_id", "converter_version",
    "runner_id", "generation_protocol_version",
)
FIELDS = ("research_questions", "study_objects_and_scales", "data_and_methods",
          "comparison_baselines", "findings", "boundaries", "missing_information")
FINDING = re.compile(r"F[0-9]{3,}")
PLACEHOLDERS = {"", "-", "—", "todo", "tbd", "n/a", "待补", "待填写", "待补充", "未填写",
                "未报告", "不适用", "not reported", "not applicable"}


@dataclass(frozen=True)
class ValidationAssets:
    """Portable, public path interface; no account or machine configuration required."""
    templates_dir: Path
    catalog_file: Path
    generation_prompt: Path
    draft_prompt: Path
    reading_prompt: Path
    output_schema: Path
    claude_reading_prompt: Path = PROMPTS_DIR / "pdf-claude-reading-v1.md"
    # Markdown-first (v2) assets: the runner reads ``paper.md``, so the draft
    # prompt and output schema differ from the legacy PDF path.
    markdown_reading_prompt: Path = PROMPTS_DIR / "markdown-reading-v1.md"
    markdown_output_schema: Path = SCHEMAS_DIR / "subject-card-draft-output-v3.schema.json"

    def __post_init__(self):
        for field in fields(self):
            object.__setattr__(self, field.name, Path(getattr(self, field.name)).expanduser().resolve())

    @classmethod
    def from_root(cls, platform_root=None):
        root = Path(platform_root) if platform_root is not None else ASSETS_DIR
        return cls(root / "templates/evidence-cards", root / "templates/evidence-cards/_catalog.json",
                   root / "prompts/evidence-card-generation-v8.md",
                   root / "prompts/subject-card-draft-v1.md",
                   root / "prompts/pdf-local-reading-v1.md",
                   root / "schemas/subject-card-draft-output.schema.json",
                   root / "prompts/pdf-claude-reading-v1.md",
                   root / "prompts/markdown-reading-v1.md",
                   root / "schemas/subject-card-draft-output-v3.schema.json")

    @classmethod
    def from_config(cls, config):
        return cls(config.paths.evidence_card_templates_dir,
                   config.paths.evidence_card_template_catalog_file,
                   config.paths.evidence_card_generation_prompt_file, PROMPT,
                   PROMPTS_DIR / "pdf-local-reading-v1.md", SCHEMA,
                   PROMPTS_DIR / "pdf-claude-reading-v1.md",
                   PROMPTS_DIR / "markdown-reading-v1.md",
                   SCHEMAS_DIR / "subject-card-draft-output-v3.schema.json")

    def as_dict(self):
        return {field.name: str(getattr(self, field.name)) for field in fields(self)}


def _assets(config):
    if config is None:
        return ValidationAssets.from_root()
    return config if isinstance(config, ValidationAssets) else ValidationAssets.from_config(config)


def _source_path(value):
    """Historical source path, interpreted in its origin OS, never in the current CWD."""
    if not isinstance(value, str) or not value.strip():
        return None
    for kind in (PureWindowsPath, PurePosixPath):
        path = kind(value)
        if path.is_absolute():
            return str(path)
    return None


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
        or _source_path(pdf["local_path"]) is None):
        add("CARD_INPUT_INVALID", "/paper_input", "输入身份、大小、哈希或路径无效")
        return None
    return {"library": library, "parent_key": parent, "requested_item_key": requested,
            "attachment_key": attachment, "pdf_sha256": pdf["sha256"],
            "pdf_size_bytes": pdf["file_size_bytes"], "item": item}


def _provenance(assets, draft, record, identity, add):
    """Compare recorded versions with the actual configured assets, not a model claim."""
    catalog, templates = load_template_bundle(assets.templates_dir, assets.catalog_file)
    templates = {k: v for k, v in templates.items() if k in SINGLE_SOURCE_TEMPLATES}
    base = read_prompt(assets.generation_prompt)
    supplement = read_prompt(assets.draft_prompt)
    recorded = draft.get("provenance")
    protocol = recorded.get("generation_protocol_version") if isinstance(recorded, dict) else None
    claude = protocol == "claude-local-pdf-v1"
    reading = read_prompt(assets.claude_reading_prompt if claude else assets.reading_prompt)
    access = draft.get("reading_record")
    if isinstance(access, dict) and access.get("method") != (CLAUDE_PDF_READ if claude else LOCAL_PDF_PATH):
        add("CARD_READING_RECORD_INVALID", "/reading_record/method", "阅读记录与所选后端协议不一致")
    provenance = draft.get("provenance")
    if not isinstance(provenance, dict):
        add("CARD_PROVENANCE_MISSING", "/provenance", "缺少提示词和模板版本信息")
        return
    expected = {
        "prompt_version": base["version"], "prompt_sha256": base["sha256"],
        "draft_prompt_version": supplement["version"], "draft_prompt_sha256": supplement["sha256"],
        "reading_prompt_version": reading["version"], "reading_prompt_sha256": reading["sha256"],
        "output_schema_sha256": hashlib.sha256(assets.output_schema.read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
        "catalog_version": catalog["catalog_version"], "generation_protocol_version": "claude-local-pdf-v1" if claude else "codex-local-pdf-v1",
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
            "source_pdf_absolute_path": _source_path(record["pdf"]["local_path"]),
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


def _base_report(policy_version, *, pipeline, legacy_read_only, errors, warnings):
    return {
        "schema_version": 1, "operation": "subject_card_validation",
        "validation_id": uuid.uuid4().hex, "validated_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": policy_version,
        "validator_sha256": hashlib.sha256(Path(__file__).read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
        # ``report_mode`` labels a historical draft without reinterpreting it:
        # v1 artifacts stay readable but are never treated as a current pass.
        "report_mode": LEGACY_READ_ONLY if legacy_read_only else "CURRENT",
        "draft_pipeline": pipeline,
        "ok": False, "status": "FAIL", "eligible_for_theme_generation": False,
        "content_validation_performed": True,
        "scientific_correctness_verified": False, "production_eligible": False,
        "errors": errors, "warnings": warnings,
    }


def _validate_machine_fields(schema_path, draft, body, pages, add, warnings):
    """Deterministic wire/content checks shared by v1 and v2 drafts.

    It judges shape, placeholders, page ranges and finding references. It never
    decides whether the science is right.
    """
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))["properties"]["machine_fields"]
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
    # Headings are visible references too. Strip them only for the nonempty-body check above.
    reference_text = re.sub(r"<!--.*?-->", "", body, flags=re.S) if isinstance(body, str) else ""
    if draft.get("pipeline") == "markdown":
        # A card for a human reader carries no machine identifiers. It says
        # where a statement comes from in plain words ("第 3 页"), and every such
        # mention has to point at a page the program verified a quote on --
        # otherwise "cited" would mean nothing.
        _check_page_citations(draft, reference_text, pages, add)
        return
    body_ids = set(re.findall(r"(?<![A-Za-z0-9])F[0-9]{3,}(?![A-Za-z0-9])", reference_text))
    for fid in sorted(ids - body_ids):
        add("CARD_FINDING_REFERENCE", "/card_body_markdown", f"正文没有引用机器结果 {fid}", finding_id=fid)
    for fid in sorted(body_ids - ids):
        add("CARD_FINDING_REFERENCE", "/card_body_markdown", f"正文引用了未定义的结果 {fid}", finding_id=fid)


def _check_page_citations(draft, body, pages, add):
    """Every page the body points at must be one the program verified.

    A page that carries no quotable prose -- a full-page figure, a reference
    list -- is the exception: the card may say "第 3 页" about a figure there,
    and no sentence exists to prove it with, so there is nothing to check.
    Coverage is measured on the pages that do carry prose.
    """
    access = draft.get("source_access")
    reading = access.get("reading") if isinstance(access, dict) else None
    reading = reading if isinstance(reading, dict) else {}
    verified = {
        page for page in reading.get("verified_pages") or [] if type(page) is int
    }
    content = {
        page for page in reading.get("content_pages") or [] if type(page) is int
    }
    mentioned = cited_pages(body)
    fields = draft.get("machine_fields")
    findings = fields.get("findings") if isinstance(fields, dict) else None
    if not mentioned:
        if findings:
            add("CARD_PAGE_CITATION", "/card_body_markdown",
                "正文没有标注任何页码；读者无法回到原文核对")
        return
    for page in mentioned:
        if not 1 <= page <= pages:
            add("CARD_PAGE_CITATION", "/card_body_markdown",
                f"正文引用了不存在的第 {page} 页", page=page)
        elif page in verified:
            continue
        elif content and page not in content:
            # Nothing on that page could have been quoted in the first place.
            continue
        else:
            add("CARD_PAGE_CITATION", "/card_body_markdown",
                f"正文引用了第 {page} 页，但该页没有程序核验过的原文证据", page=page)


def _check_body(draft, add, warnings):
    body = draft.get("card_body_markdown")
    visible = re.sub(r"<!--.*?-->|(?m:^[ \t]*#{1,6}[ \t]+[^\r\n]*$)", "", body, flags=re.S) if isinstance(body, str) else ""
    if not _content(visible):
        add("CARD_CONTENT_MISSING", "/card_body_markdown", "缺少可读正文或仅有占位内容")
    elif len(visible.strip()) < 300:
        warnings.append({"code": "CARD_TEXT_SHORT", "path": "/card_body_markdown",
                         "message": "正文较短，请关注信息覆盖；字数不决定是否通过"})
    return body


def _validate_legacy_draft(assets, draft, paper_input, identity, report, add, warnings):
    """Rules for schema_version 1 drafts (PDF read by the provider itself)."""
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
        or access.get("method") not in CURRENT_METHODS
        or any(access.get(k) is not True for k in ("source_identity_verified", "source_unchanged",
                                                  "model_reading_report_accepted"))):
        add("CARD_READING_RECORD_INVALID", "/reading_record", "阅读记录与草稿来源不一致或未被接受")
    if isinstance(access, dict) and access.get("method") == CLAUDE_PDF_READ and not source_access_acceptable(
            access, expected_sha256=source.get("pdf_sha256"), expected_parent_key=source.get("parent_key")):
        add("CARD_READING_RECORD_INVALID", "/reading_record", "Claude 的只读 PDF 回执或来源身份不完整")
    body = _check_body(draft, add, warnings)
    try:
        _validate_machine_fields(assets.output_schema, draft, body, pages, add, warnings)
        _provenance(assets, draft, paper_input, identity, add)
    except (OSError, ValueError, KeyError, CardGenerationError, EvidenceTemplateError) as exc:
        add("CARD_RULESET_UNAVAILABLE", "/provenance", f"无法读取校验所需协议或版本资产：{type(exc).__name__}", asset_paths=assets.as_dict())


def _check_markdown_access(access, source, pages, add):
    """The v2 receipt: both digests, converter identity and program verdicts."""
    if not isinstance(access, dict):
        add("CARD_READING_RECORD_INVALID", "/source_access", "缺少 Markdown 阅读回执")
        return
    if access.get("method") != MARKDOWN_PREPARED:
        add("CARD_READING_RECORD_INVALID", "/source_access/method", "阅读回执必须记录 markdown_prepared")
    digest = access.get("source_pdf_sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest) or digest != source.get("pdf_sha256"):
        add("CARD_SOURCE_MISMATCH", "/source_access/source_pdf_sha256", "回执的 PDF 哈希与草稿来源不一致")
    markdown_digest = access.get("markdown_sha256")
    if not isinstance(markdown_digest, str) or not SHA256.fullmatch(markdown_digest):
        add("CARD_READING_RECORD_INVALID", "/source_access/markdown_sha256", "缺少有效的 Markdown 哈希")
    if access.get("parent_key") != source.get("parent_key"):
        add("CARD_SOURCE_MISMATCH", "/source_access/parent_key", "回执的父条目与草稿来源不一致")
    if type(access.get("page_count")) is not int or access["page_count"] != pages:
        add("CARD_READING_RECORD_INVALID", "/source_access/page_count", "回执页数与草稿来源不一致")
    for key in ("converter_id", "converter_version"):
        if not _text(access.get(key)):
            add("CARD_READING_RECORD_INVALID", f"/source_access/{key}", "缺少转换器身份")
    reading = access.get("reading")
    if not isinstance(reading, dict):
        add("CARD_READING_RECORD_INVALID", "/source_access/reading", "缺少由程序计算的阅读结论")
        return
    if reading.get("verified") is not True:
        add("CARD_READING_NOT_VERIFIED", "/source_access/reading/verified",
            "引文与页锚点未通过程序校验；不能作为已核验阅读")
    if reading.get("canaries_ok") is not True:
        add("CARD_READING_NOT_VERIFIED", "/source_access/reading/canaries_ok",
            "完整性 canary 未被全部回显")
    if reading.get("scientific_correctness_verified") is not False:
        add("CARD_READING_RECORD_INVALID", "/source_access/reading/scientific_correctness_verified",
            "自动校验不能声称科研正确性")
    coverage = reading.get("quote_coverage")
    if (isinstance(coverage, bool) or not isinstance(coverage, (int, float))
            or not 0.0 <= float(coverage) <= 1.0):
        add("CARD_READING_RECORD_INVALID", "/source_access/reading/quote_coverage",
            "引文覆盖率必须是 0 到 1 之间的数值")


def _provenance_markdown(assets, draft, add):
    """Compare the v2 provenance record with the assets shipped with this code."""
    catalog, templates = load_template_bundle(assets.templates_dir, assets.catalog_file)
    templates = {k: v for k, v in templates.items() if k in SINGLE_SOURCE_TEMPLATES}
    base = read_prompt(assets.generation_prompt)
    supplement = read_prompt(assets.markdown_reading_prompt)
    provenance = draft.get("provenance")
    if not isinstance(provenance, dict):
        add("CARD_PROVENANCE_MISSING", "/provenance", "缺少转换器、运行器和模板版本信息")
        return
    for key in MARKDOWN_PROVENANCE_FIELDS:
        if key not in provenance:
            add("CARD_PROVENANCE_MISSING", f"/provenance/{key}", "缺少版本或指纹")
    expected = {
        "prompt_version": base["version"], "prompt_sha256": base["sha256"],
        "draft_prompt_version": supplement["version"], "draft_prompt_sha256": supplement["sha256"],
        "output_schema_sha256": hashlib.sha256(
            assets.markdown_output_schema.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest(),
        "catalog_version": catalog["catalog_version"],
        "generation_protocol_version": MARKDOWN_CARD_PROTOCOL_VERSION,
    }
    tid = provenance.get("template_id")
    template = templates.get(tid) if isinstance(tid, str) else None
    if template is None:
        add("CARD_TEMPLATE_INVALID", "/provenance/template_id", "不是当前启用的单来源模板")
    else:
        expected.update(template_version=template["local_version"], template_sha256=template["content_sha256"])
    for key, value in expected.items():
        if key not in provenance:
            continue
        if provenance[key] != value:
            add("CARD_VERSION_MISMATCH", f"/provenance/{key}", "记录与当前输入或配置的版本不一致")
    # ``combined_prompt_sha256`` embeds prepared-paper canaries and anchors that
    # the input record does not carry, so only its shape is checkable here.
    combined = provenance.get("combined_prompt_sha256")
    if "combined_prompt_sha256" in provenance and (
        not isinstance(combined, str) or not SHA256.fullmatch(combined)
    ):
        add("CARD_VERSION_MISMATCH", "/provenance/combined_prompt_sha256", "必须记录 64 位 SHA-256")
    access = draft.get("source_access") if isinstance(draft.get("source_access"), dict) else {}
    for key in ("converter_id", "converter_version"):
        if key in provenance and provenance[key] != access.get(key):
            add("CARD_VERSION_MISMATCH", f"/provenance/{key}", "与阅读回执记录的转换器不一致")
    if not _text(provenance.get("runner_id")):
        add("CARD_PROVENANCE_MISSING", "/provenance/runner_id", "缺少运行器标识")


def _validate_markdown_draft(assets, draft, paper_input, identity, report, add, warnings):
    """Rules for schema_version 2 drafts produced by the Markdown-first pipeline."""
    if type(draft.get("schema_version")) is not int or draft["schema_version"] != MARKDOWN_DRAFT_SCHEMA_VERSION:
        add("CARD_DRAFT_VERSION", "/schema_version", "仅支持主体卡草稿协议版本 2")
    if draft.get("pipeline") != "markdown":
        add("CARD_DRAFT_INVALID", "/pipeline", "v2 草稿必须记录 markdown 管线")
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
    access = draft.get("source_access")
    _check_markdown_access(access, source, pages, add)
    # ``verified`` is computed by ``domain.grounding`` at generation time; this
    # report only records it so eligibility can require it explicitly.
    reading = access.get("reading") if isinstance(access, dict) else None
    verified_reading = (
        isinstance(reading, dict)
        and reading.get("verified") is True
        and reading.get("canaries_ok") is True
    )
    report["reading_verified"] = verified_reading
    report["reading_status"] = "VERIFIED" if verified_reading else "PARTIAL"
    # During the migration the draft carries the same receipt under both names;
    # a mismatch means one of them was edited independently.
    if fingerprint(draft.get("reading_record")) != fingerprint(access):
        add("CARD_READING_RECORD_INVALID", "/reading_record",
            "reading_record 与 source_access 必须是同一份回执")
    body = _check_body(draft, add, warnings)
    try:
        _validate_machine_fields(assets.markdown_output_schema, draft, body, pages, add, warnings)
        _provenance_markdown(assets, draft, add)
    except (OSError, ValueError, KeyError, CardGenerationError, EvidenceTemplateError) as exc:
        add("CARD_RULESET_UNAVAILABLE", "/provenance", f"无法读取校验所需协议或版本资产：{type(exc).__name__}", asset_paths=assets.as_dict())


def validate_subject_card(config, draft, paper_input):
    """Pure with respect to input artifacts: read assets, return a report, never invoke AI."""
    assets = _assets(config)
    errors, warnings = [], []
    def add(code, path, message, **details):
        errors.append({"code": code, "path": path, "message": message, **details})

    markdown = isinstance(draft, dict) and draft.get("pipeline") == "markdown"
    report = _base_report(
        POLICY_MARKDOWN if markdown else POLICY,
        pipeline="markdown" if markdown else "legacy",
        legacy_read_only=not markdown,
        errors=errors, warnings=warnings,
    )
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
    if markdown:
        _validate_markdown_draft(assets, draft, paper_input, identity, report, add, warnings)
    else:
        _validate_legacy_draft(assets, draft, paper_input, identity, report, add, warnings)
    eligible = not errors
    if markdown:
        # A new draft may only enter theme generation with a verified reading;
        # a PARTIAL grounding is saved as a draft but never eligible.
        eligible = eligible and report.get("reading_verified") is True
    report.update(ok=not errors, status="FAIL" if errors else "PASS",
                  eligible_for_theme_generation=eligible)
    return report


def read_strict_json(path):
    """Public name for the decoder shared by drafts and their validation records.

    One owner for the on-disk contract: duplicate keys and non-finite numbers
    are rejected everywhere instead of each reader growing its own rules.
    """
    return _read_json(path)


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


def validate_subject_card_file(config, draft_path, input_path, *, report_dir=None):
    """Save only an append-only validation record; the draft remains byte-identical."""
    try:
        path = Path(draft_path).resolve(strict=True)
        draft, record = _read_json(path), _read_json(input_path)
        report = validate_subject_card(config, draft, record)
        directory = (Path(report_dir).expanduser().resolve() if report_dir is not None
                     else path.parent / "validations")
        if report_dir is None and not directory.resolve().is_relative_to(path.parent):
            raise OSError("校验记录目录越界")
        # A unique directory avoids overwriting any existing record, even on collision.
        directory = directory / report["validation_id"]
        directory.mkdir(parents=True, exist_ok=False)
        target = directory / "validation.json"
        atomic_text(target, json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        return {**report, "validation_path": str(target), "asset_paths": _assets(config).as_dict()}
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
