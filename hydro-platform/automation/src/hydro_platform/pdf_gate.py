from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from hydro_platform.config import PdfGateConfig, ZoteroConfig
from hydro_platform.zotero import ZoteroApiError, ZoteroClient


ITEM_KEY_PATTERN = re.compile(r"^[A-Z0-9]{8}$")


class PdfGateError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def is_pdf_attachment(record: dict[str, Any]) -> bool:
    """Return whether a Zotero child record represents a PDF attachment."""
    data = record.get("data")
    if not isinstance(data, dict) or data.get("itemType") != "attachment":
        return False
    content_type = str(data.get("contentType") or "").lower()
    filename = str(data.get("filename") or "").lower()
    return content_type == "application/pdf" or filename.endswith(".pdf")


def attachment_summary(record: dict[str, Any]) -> dict[str, Any]:
    """Return the stable attachment fields exposed by PDF readiness results."""
    data = record.get("data")
    if not isinstance(data, dict):
        raise PdfGateError("INVALID_API_RESPONSE", "PDF 附件缺少 data 对象")
    key = record.get("key") or data.get("key")
    if not isinstance(key, str) or not ITEM_KEY_PATTERN.fullmatch(key):
        raise PdfGateError("INVALID_API_RESPONSE", "PDF 附件缺少有效 Zotero Key")
    return {
        "attachment_key": key,
        "filename": data.get("filename"),
        "content_type": data.get("contentType"),
        "link_mode": data.get("linkMode"),
        "parent_key": data.get("parentItem"),
    }


def _result(
    config: ZoteroConfig,
    parent_key: str,
    *,
    gate_status: str,
    reason_code: str,
    message: str,
    pdf_count: int,
    pdf: dict[str, Any] | None = None,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": 1,
        "ok": True,
        "gate_status": gate_status,
        "reason_code": reason_code,
        "message": message,
        "group_id": config.group_id,
        "parent_key": parent_key,
        "pdf_attachment_count": pdf_count,
    }
    if pdf is not None:
        result["pdf"] = pdf
    if candidates is not None:
        result["candidates"] = candidates
    return result


def file_url_to_path(value: Any) -> Path:
    """Convert a local Zotero file URL to a platform path."""
    if not isinstance(value, str) or not value.strip():
        raise PdfGateError("INVALID_FILE_URL", "Zotero 没有返回有效的 PDF 文件地址")
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() != "file":
        raise PdfGateError("PDF_NOT_LOCAL", "PDF 尚未成为制卡机上的本地文件")
    if parsed.netloc not in {"", "localhost"}:
        raise PdfGateError("PDF_NOT_LOCAL", "第一版不读取网络共享路径中的 PDF")
    return Path(url2pathname(unquote(parsed.path)))


def inspect_pdf_file(path: Path, gate: PdfGateConfig) -> tuple[int, str, str | None]:
    """Validate a local PDF and return size, SHA-256, and an optional problem code."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            header = handle.read(8)
            handle.seek(0)
            digest = hashlib.sha256()
            tail = b""
            while chunk := handle.read(gate.hash_chunk_size_bytes):
                digest.update(chunk)
                tail = (tail + chunk)[-4096:]
    except FileNotFoundError:
        return 0, "", "PDF_FILE_NOT_SYNCED"
    except OSError:
        return 0, "", "PDF_FILE_UNREADABLE"

    if size < gate.min_file_size_bytes:
        return size, digest.hexdigest(), "PDF_FILE_TOO_SMALL"
    if not header.startswith(b"%PDF-") or b"%%EOF" not in tail:
        return size, digest.hexdigest(), "PDF_STRUCTURE_INVALID"
    return size, digest.hexdigest(), None


def evaluate_pdf_gate(
    zotero: ZoteroConfig,
    gate: PdfGateConfig,
    parent_key: str,
    *,
    client: ZoteroClient | None = None,
) -> dict[str, Any]:
    if zotero.group_id is None:
        raise PdfGateError("CONFIG_ERROR", "PDF 门禁需要目标 Zotero 群组 ID")
    normalized_key = parent_key.strip().upper()
    if not ITEM_KEY_PATTERN.fullmatch(normalized_key):
        raise PdfGateError("INVALID_ITEM_KEY", "父条目 Key 必须是 8 位字母或数字")

    api = client or ZoteroClient(zotero)
    response = api.get_json(
        f"/api/groups/{zotero.group_id}/items/{normalized_key}/children"
    )
    if not isinstance(response.data, list) or any(
        not isinstance(record, dict) for record in response.data
    ):
        raise PdfGateError("INVALID_API_RESPONSE", "Zotero 子条目列表格式异常")

    pdf_records = [record for record in response.data if is_pdf_attachment(record)]
    summaries = [attachment_summary(record) for record in pdf_records]
    if not summaries:
        return _result(
            zotero,
            normalized_key,
            gate_status="WAITING",
            reason_code="PDF_MISSING",
            message="父条目尚无 PDF 附件，等待补充后重试",
            pdf_count=0,
        )
    if len(summaries) > 1:
        return _result(
            zotero,
            normalized_key,
            gate_status="BLOCKED",
            reason_code="MULTIPLE_PDFS",
            message="父条目包含多个 PDF，无法安全判断主文",
            pdf_count=len(summaries),
            candidates=summaries,
        )

    pdf = summaries[0]
    if pdf.get("parent_key") != normalized_key:
        raise PdfGateError("INVALID_API_RESPONSE", "PDF 附件与父条目关联不一致")
    attachment_key = pdf["attachment_key"]
    try:
        file_response = api.get_text(
            f"/api/groups/{zotero.group_id}/items/{attachment_key}/file/view/url"
        )
        file_path = file_url_to_path(file_response.data)
    except ZoteroApiError as exc:
        if exc.status == 404:
            return _result(
                zotero,
                normalized_key,
                gate_status="WAITING",
                reason_code="PDF_FILE_NOT_SYNCED",
                message="Zotero 已有附件记录，但制卡机尚未取得本地 PDF 文件",
                pdf_count=1,
                pdf=pdf,
            )
        raise
    except PdfGateError as exc:
        return _result(
            zotero,
            normalized_key,
            gate_status="BLOCKED",
            reason_code=exc.code,
            message=str(exc),
            pdf_count=1,
            pdf=pdf,
        )

    size, sha256, file_problem = inspect_pdf_file(file_path, gate)
    pdf.update(
        {
            "file_size_bytes": size,
            "sha256": sha256 or None,
            "local_path": str(file_path.resolve()),
        }
    )
    if file_problem is not None:
        status = "WAITING" if file_problem == "PDF_FILE_NOT_SYNCED" else "BLOCKED"
        messages = {
            "PDF_FILE_NOT_SYNCED": "PDF 文件尚未同步到制卡机",
            "PDF_FILE_UNREADABLE": "制卡机无法读取 PDF 文件",
            "PDF_FILE_TOO_SMALL": "PDF 文件过小，不能视为有效全文",
            "PDF_STRUCTURE_INVALID": "文件缺少有效 PDF 头或结束标记",
        }
        return _result(
            zotero,
            normalized_key,
            gate_status=status,
            reason_code=file_problem,
            message=messages[file_problem],
            pdf_count=1,
            pdf=pdf,
        )

    try:
        fulltext_response = api.get_json(
            f"/api/groups/{zotero.group_id}/items/{attachment_key}/fulltext"
        )
    except ZoteroApiError as exc:
        if exc.status == 404:
            return _result(
                zotero,
                normalized_key,
                gate_status="WAITING",
                reason_code="FULLTEXT_NOT_INDEXED",
                message="PDF 文件存在，但 Zotero 尚未提供索引全文",
                pdf_count=1,
                pdf=pdf,
            )
        raise
    if not isinstance(fulltext_response.data, dict):
        raise PdfGateError("INVALID_API_RESPONSE", "Zotero 全文响应格式异常")
    content = fulltext_response.data.get("content")
    if content is not None and not isinstance(content, str):
        raise PdfGateError("INVALID_API_RESPONSE", "Zotero 全文 content 字段格式异常")
    text_characters = sum(1 for character in (content or "") if not character.isspace())
    pdf["text_characters"] = text_characters
    if text_characters < gate.min_text_characters:
        return _result(
            zotero,
            normalized_key,
            gate_status="BLOCKED",
            reason_code="TEXT_NOT_EXTRACTABLE",
            message="可提取文字不足，可能是扫描件或索引异常；第一版不自动 OCR",
            pdf_count=1,
            pdf=pdf,
        )

    return _result(
        zotero,
        normalized_key,
        gate_status="READY",
        reason_code="PDF_READY",
        message="已取得可读取 PDF 文件和足量可提取全文",
        pdf_count=1,
        pdf=pdf,
    )
