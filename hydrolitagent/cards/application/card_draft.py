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


def check_wire(value: Any, schema: dict, path: str = "machine_fields") -> None:
    """Only decode the fixed wire shape. Do not judge content, coverage or citations."""
    types = schema.get("type")
    if isinstance(types, list):
        if value is None and "null" in types:
            return
        types = next(t for t in types if t != "null")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "number": type(value) is int or (type(value) is float and math.isfinite(value)),
    }.get(types, False)
    if not valid or ("enum" in schema and value not in schema["enum"]):
        fail("CARD_DRAFT_OUTPUT_INVALID", f"机器字段无法解析：{path}")
    if types == "object":
        properties = schema["properties"]
        if set(value) != set(properties):
            fail("CARD_DRAFT_OUTPUT_INVALID", f"机器字段缺少或多出键：{path}")
        for key, child in properties.items():
            check_wire(value[key], child, f"{path}.{key}")
    elif types == "array":
        for index, child in enumerate(value):
            check_wire(child, schema["items"], f"{path}[{index}]")


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
    "digest",
    "fail",
    "read_paper_input",
    "save_draft",
]
