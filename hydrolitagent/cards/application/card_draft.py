"""The single-paper input contract, the wire check and the append-only save.

Three small pieces shared by every card entry point:

* ``read_paper_input`` -- consume one ``paper_input`` READY record and prove the
  local PDF is still the file the record describes;
* ``check_wire`` -- decode the fixed ``machine_fields`` shape, nothing else;
* ``save_draft`` -- write the preview and then ``draft.json`` as the atomic
  completion marker.

Nothing here calls a model or judges content: a saved draft is explicitly
``DRAFT_PENDING_VALIDATION``.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.domain.errors import CardGenerationError
from hydrolitagent.cards.domain.violations import (
    Violation,
    describe_value,
    violation_dicts,
)

KEY = re.compile(r"[A-Z0-9]{8}")
SHA256 = re.compile(r"[a-f0-9]{64}")
# Templates that may be used for a card describing one paper. Synthesis and
# aggregate templates stay out of the single-source path.
SINGLE_SOURCE_TEMPLATES = frozenset({
    "original-research", "review-synthesis", "survey-monitoring-statistics",
    "engineering-report", "book-chapter", "standard-guideline-policy",
    "dataset-data-product", "software-model-code",
})
ASSETS = ASSETS_DIR
PROMPT = ASSETS / "prompts/subject-card-draft-v1.md"
SCHEMA = ASSETS / "schemas/subject-card-draft-output.schema.json"


def fail(code: str, message: str) -> None:
    raise CardGenerationError(code, message)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_paper_input(record: Any) -> tuple[dict, Path]:
    """Consume the READY contract of the single-paper input, without re-reading Zotero."""
    if (not isinstance(record, dict) or type(record.get("schema_version")) is not int
        or record["schema_version"] != 1 or record.get("operation") != "paper_input"
        or record.get("ok") is not True or record.get("status") != "READY"
        or type(record.get("pdf_attachment_count")) is not int
        or record["pdf_attachment_count"] != 1):
        fail("CARD_DRAFT_INPUT_INVALID", "需要单篇 READY 输入记录")
    library, item, pdf = (record.get(k) for k in ("library", "item", "pdf"))
    if not all(isinstance(v, dict) for v in (library, item, pdf)):
        fail("CARD_DRAFT_INPUT_INVALID", "输入缺少文库、父条目或 PDF")
    if (library.get("type") not in {"user", "group"}
        or type(library.get("id")) is not int or library["id"] < 0
        or (library["type"] == "group" and library["id"] == 0)):
        fail("CARD_DRAFT_INPUT_INVALID", "文库身份无效")
    parent, attachment = item.get("item_key"), pdf.get("attachment_key")
    requested = record.get("requested_item_key")
    if (not all(isinstance(k, str) and KEY.fullmatch(k) for k in (parent, attachment, requested))
        or parent == attachment or requested not in (parent, attachment) or pdf.get("parent_key") != parent
        or not isinstance(item.get("title"), str) or not item["title"].strip()
        or not isinstance(pdf.get("sha256"), str) or not SHA256.fullmatch(pdf["sha256"])
        or type(pdf.get("file_size_bytes")) is not int or pdf["file_size_bytes"] < 1
        or not isinstance(pdf.get("local_path"), str) or not pdf["local_path"].strip()):
        fail("CARD_DRAFT_INPUT_INVALID", "论文或 PDF 身份字段无效")
    path = Path(pdf["local_path"])
    if not path.is_absolute():
        fail("CARD_DRAFT_INPUT_INVALID", "PDF 路径必须是输入记录返回的绝对路径")
    try:
        path = path.resolve(strict=True)
        with path.open("rb") as stream:
            header = stream.read(5)
        if not path.is_file() or path.suffix.lower() != ".pdf" or header != b"%PDF-":
            fail("CARD_DRAFT_PDF_UNREADABLE", "输入不是可读取的 PDF")
        if path.stat().st_size != pdf["file_size_bytes"] or digest(path) != pdf["sha256"]:
            fail("PDF_INPUT_CHANGED", "PDF 与输入记录的大小或哈希不同，请重新取得输入")
    except OSError as exc:
        raise CardGenerationError("CARD_DRAFT_PDF_UNREADABLE", "无法读取输入 PDF") from exc
    # fulltext_indexed=False is explicitly valid: the runner reads the local PDF.
    return deepcopy(record), path


_JSON_TYPE_LABELS = {
    "object": "对象",
    "array": "数组",
    "string": "字符串",
    "integer": "整数",
    "number": "数值",
    "boolean": "布尔值",
    "null": "null",
}


def _declared_type(schema: dict) -> str | None:
    types = schema.get("type")
    if isinstance(types, list):
        others = [kind for kind in types if kind != "null"]
        return others[0] if others else "null"
    return types


def _wire_type_ok(value: Any, kind: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "number": type(value) is int or (type(value) is float and math.isfinite(value)),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(kind, False)


def collect_wire_violations(
    value: Any, schema: dict, path: str = "machine_fields"
) -> list[Violation]:
    """Every shape problem under ``path``, including nested array items.

    The old check raised on the first problem, which told a repair step nothing
    about the other seven; this reports the whole list with a path per entry so
    a model can be pointed at the exact spot.
    """

    types = schema.get("type")
    if isinstance(types, list) and value is None and "null" in types:
        return []
    kind = _declared_type(schema)
    if not _wire_type_ok(value, kind or ""):
        return [
            Violation(
                "CARD_DRAFT_OUTPUT_INVALID",
                path,
                "机器字段类型不符合协议",
                _JSON_TYPE_LABELS.get(kind or "", kind or "未知类型"),
                describe_value(value),
            )
        ]
    if "enum" in schema and value not in schema["enum"]:
        return [
            Violation(
                "CARD_DRAFT_OUTPUT_INVALID",
                path,
                "机器字段取值不在协议枚举内",
                "、".join(str(item) for item in schema["enum"]),
                describe_value(value),
            )
        ]
    violations: list[Violation] = []
    if kind == "object":
        properties = schema.get("properties") or {}
        for key in sorted(set(properties) - set(value)):
            violations.append(
                Violation(
                    "CARD_DRAFT_OUTPUT_INVALID",
                    f"{path}.{key}",
                    "机器字段缺少该键",
                    "该键存在",
                    "未提供",
                )
            )
        for key in sorted(set(value) - set(properties)):
            violations.append(
                Violation(
                    "CARD_DRAFT_OUTPUT_INVALID",
                    f"{path}.{key}",
                    "机器字段多出协议外的键",
                    "只允许协议规定的键",
                    describe_value(value[key]),
                )
            )
        for key in sorted(set(properties) & set(value)):
            violations.extend(
                collect_wire_violations(value[key], properties[key], f"{path}.{key}")
            )
    elif kind == "array":
        items = schema.get("items") or {}
        for index, child in enumerate(value):
            violations.extend(collect_wire_violations(child, items, f"{path}[{index}]"))
    return violations


def describe_wire_contract(schema: dict, *, depth: int = 2) -> dict[str, Any]:
    """The key list a repair prompt may quote: names, types, nested item keys.

    ``depth`` is bounded on purpose. One level was not enough in practice: a
    model handed only ``item_keys`` copied the *top-level* ``source_locations``
    shape (with ``quote``/``anchor``) into the machine-field one, which allows
    only ``pdf_page``/``section``/``figure``/``table`` -- fifty violations of one
    repeated mistake.
    """

    contract: dict[str, Any] = {}
    for key, child in sorted((schema.get("properties") or {}).items()):
        kind = _declared_type(child)
        entry: dict[str, Any] = {"type": kind}
        if kind == "array":
            items = child.get("items") or {}
            entry["item_type"] = _declared_type(items)
            if _declared_type(items) == "object":
                entry["item_keys"] = sorted(items.get("properties") or {})
                if depth > 0:
                    nested = {
                        # Describe the *item* object, not the array wrapper.
                        name: describe_wire_contract(
                            grandchild.get("items") or {}, depth=depth - 1
                        )
                        for name, grandchild in sorted(
                            (items.get("properties") or {}).items()
                        )
                        if _declared_type(grandchild) == "array"
                        and _declared_type(grandchild.get("items")) == "object"
                    }
                    if nested:
                        entry["item_arrays"] = nested
        if "enum" in child:
            entry["enum"] = list(child["enum"])
        if child.get("minItems") is not None:
            entry["min_items"] = child["minItems"]
        contract[key] = entry
    return contract


def check_wire(value: Any, schema: dict, path: str = "machine_fields") -> None:
    """Only decode the fixed wire shape. Do not judge content, coverage or citations."""

    violations = collect_wire_violations(value, schema, path)
    if violations:
        raise CardGenerationError(
            "CARD_DRAFT_OUTPUT_INVALID",
            f"机器字段不符合协议：{len(violations)} 处问题",
            diagnostic={
                "violations": violation_dicts(violations),
                "machine_fields_contract": describe_wire_contract(schema),
            },
        )


def _comparable(draft: dict) -> str:
    """Everything that describes the card, minus the volatile bookkeeping."""

    return json.dumps(
        {key: value for key, value in draft.items() if key != "created_at"},
        ensure_ascii=False, sort_keys=True, allow_nan=False,
    )


def save_draft(root: Path, draft: dict) -> dict:
    """Write the preview once; draft.json is the last, atomic completion marker.

    Re-saving the same draft id with the same content returns the existing files
    instead of raising: finalizing an already-finalized workspace is a no-op, not
    a crash. A different result under the same draft id is a conflict, because a
    draft is append-only and never overwritten.
    """
    source = draft["source"]
    library = source["library"]
    identity = f"{library['type']}-{library['id']}-{source['parent_key']}"
    directory = root / "zotero" / identity / "drafts" / draft["draft_id"]
    resolved_root, resolved_dir = root.resolve(), directory.resolve()
    if not resolved_dir.is_relative_to(resolved_root):
        fail("CARD_DRAFT_PATH_INVALID", "草稿子目录不得通过链接逃逸出精读产物根")
    card = directory / "card.md"
    completed = directory / "draft.json"
    if resolved_dir.exists():
        try:
            current = json.loads(completed.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = None
        if isinstance(current, dict) and _comparable(current) == _comparable(draft):
            return {"literature_root": str(resolved_root), "draft_path": str(completed),
                    "card_path": str(card), "created": False}
        fail("CARD_DRAFT_ALREADY_EXISTS",
             "同一 draft_id 已存在内容不同的草稿；草稿只追加，不覆盖")
    directory.mkdir(parents=True, exist_ok=False)
    # A visible status belongs to the preview, never to the model-controlled body.
    card.write_text(
        "> 待校验主体卡草稿；未通过内容门禁，不是正式发布的卡片。\n\n"
        + draft["card_body_markdown"], encoding="utf-8", newline="\n",
    )
    pending = directory / "draft.json.tmp"
    pending.write_text(json.dumps(draft, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                       encoding="utf-8", newline="\n")
    pending.replace(completed)
    return {"literature_root": str(resolved_root), "draft_path": str(completed),
            "card_path": str(card), "created": True}


__all__ = [
    "ASSETS",
    "KEY",
    "PROMPT",
    "SCHEMA",
    "SHA256",
    "SINGLE_SOURCE_TEMPLATES",
    "check_wire",
    "collect_wire_violations",
    "describe_wire_contract",
    "digest",
    "fail",
    "read_paper_input",
    "save_draft",
]
