from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from hydro_platform.config import PdfGateConfig, ZoteroConfig
from hydro_platform.pdf_gate import (
    ITEM_KEY_PATTERN,
    PdfGateError,
    attachment_summary,
    file_url_to_path,
    inspect_pdf_file,
    is_pdf_attachment,
)
from hydro_platform.zotero import ZoteroApiError, ZoteroClient


DEMO_PAPER = {
    "title": (
        "Simulating historical flood events at the continental scale: "
        "Observational validation of a large-scale hydrodynamic model"
    ),
    "doi": "10.5194/nhess-21-559-2021",
    "source_url": "https://nhess.copernicus.org/articles/21/559/2021/",
    "pdf_url": "https://nhess.copernicus.org/articles/21/559/2021/nhess-21-559-2021.pdf",
    "destination": "我的文库 → 科研平台 → 证据卡训练集",
}


class PaperInputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _library_path(zotero: ZoteroConfig, library_type: str) -> tuple[str, dict[str, Any]]:
    if library_type == "user":
        return "/api/users/0", {"type": "user", "id": 0}
    if library_type != "group":
        raise PaperInputError("INVALID_LIBRARY_TYPE", "library_type 必须是 group 或 user")
    if zotero.group_id is None:
        raise PaperInputError("CONFIG_ERROR", "群组库输入需要配置 Zotero group_id")
    return (
        f"/api/groups/{zotero.group_id}",
        {"type": "group", "id": zotero.group_id},
    )


def _candidate(record: dict[str, Any]) -> dict[str, Any]:
    data = record.get("data")
    meta = record.get("meta")
    data = data if isinstance(data, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    return {
        "item_key": record.get("key") or data.get("key"),
        "item_type": data.get("itemType"),
        "title": data.get("title"),
        "creators": meta.get("creatorSummary"),
        "date": data.get("date"),
        "doi": data.get("DOI"),
        "url": data.get("url"),
        "child_count": meta.get("numChildren"),
    }


def _is_selectable_parent(record: dict[str, Any]) -> bool:
    data = record.get("data")
    if not isinstance(data, dict):
        return False
    return data.get("itemType") not in {"attachment", "note", "annotation"}


def prepare_paper_input(
    zotero: ZoteroConfig,
    gate: PdfGateConfig,
    *,
    query: str | None = None,
    item_key: str | None = None,
    library_type: str = "group",
    limit: int = 10,
    client: ZoteroClient | None = None,
) -> dict[str, Any]:
    """Search Zotero candidates or resolve one confirmed item into PDF input."""
    if bool(query) == bool(item_key):
        raise PaperInputError("INVALID_INPUT", "必须且只能提供 query 或 item_key 其中一个")
    if not 1 <= limit <= 50:
        raise PaperInputError("INVALID_LIMIT", "limit 必须在 1 到 50 之间")

    base_path, library = _library_path(zotero, library_type)
    api = client or ZoteroClient(zotero)
    if query is not None:
        normalized_query = query.strip()
        if not normalized_query:
            raise PaperInputError("INVALID_QUERY", "query 不能为空")
        params = urlencode(
            {"q": normalized_query, "qmode": "everything", "limit": limit}
        )
        response = api.get_json(f"{base_path}/items/top?{params}")
        if not isinstance(response.data, list) or any(
            not isinstance(record, dict) for record in response.data
        ):
            raise PaperInputError("INVALID_API_RESPONSE", "Zotero 搜索结果格式异常")

        return {
            "schema_version": 1,
            "ok": True,
            "operation": "paper_input",
            "status": "SELECTION_REQUIRED",
            "message": "请从候选文献中确认 item_key 后重新执行",
            "library": library,
            "query": normalized_query,
            "candidates": [
                _candidate(record)
                for record in response.data
                if _is_selectable_parent(record)
            ],
        }

    normalized_key = (item_key or "").strip().upper()
    if not ITEM_KEY_PATTERN.fullmatch(normalized_key):
        raise PaperInputError("INVALID_ITEM_KEY", "item_key 必须是 8 位字母或数字")
    requested_key = normalized_key
    try:
        item_response = api.get_json(f"{base_path}/items/{normalized_key}")
    except ZoteroApiError as exc:
        if exc.status != 404:
            raise
        return {
            "schema_version": 1,
            "ok": True,
            "operation": "paper_input",
            "status": "BLOCKED",
            "reason_code": "ITEM_NOT_FOUND",
            "message": "Zotero 中找不到指定 item_key",
            "library": library,
            "requested_item_key": requested_key,
        }
    if not isinstance(item_response.data, dict):
        raise PaperInputError("INVALID_API_RESPONSE", "Zotero 条目格式异常")
    requested_data = item_response.data.get("data")
    if (
        isinstance(requested_data, dict)
        and requested_data.get("parentItem")
    ):
        parent_key = requested_data.get("parentItem")
        if not isinstance(parent_key, str) or not ITEM_KEY_PATTERN.fullmatch(parent_key):
            raise PaperInputError(
                "INVALID_API_RESPONSE", "Zotero 子条目没有有效的父条目 Key"
            )
        normalized_key = parent_key
        try:
            item_response = api.get_json(f"{base_path}/items/{normalized_key}")
        except ZoteroApiError as exc:
            if exc.status != 404:
                raise
            return {
                "schema_version": 1,
                "ok": True,
                "operation": "paper_input",
                "status": "BLOCKED",
                "reason_code": "ITEM_NOT_FOUND",
                "message": "Zotero 中找不到附件对应的父条目",
                "library": library,
                "requested_item_key": requested_key,
                "parent_item_key": normalized_key,
            }
        if not isinstance(item_response.data, dict):
            raise PaperInputError("INVALID_API_RESPONSE", "Zotero 父条目格式异常")
    item = _candidate(item_response.data)

    children_response = api.get_json(f"{base_path}/items/{normalized_key}/children")
    if not isinstance(children_response.data, list) or any(
        not isinstance(record, dict) for record in children_response.data
    ):
        raise PaperInputError("INVALID_API_RESPONSE", "Zotero 子条目列表格式异常")
    pdf_records = [
        record for record in children_response.data if is_pdf_attachment(record)
    ]
    if len(pdf_records) > 1:
        candidates = [attachment_summary(record) for record in pdf_records]
        return {
            "schema_version": 1,
            "ok": True,
            "operation": "paper_input",
            "status": "BLOCKED",
            "reason_code": "MULTIPLE_PDFS",
            "message": "父条目包含多个 PDF；请在 Zotero 中人工整理后重试",
            "library": library,
            "requested_item_key": requested_key,
            "item": item,
            "pdf_attachment_count": len(candidates),
            "candidates": candidates,
        }
    if not pdf_records:
        return {
            "schema_version": 1,
            "ok": True,
            "operation": "paper_input",
            "status": "WAITING",
            "reason_code": "PDF_MISSING",
            "message": "条目没有 PDF；请打开来源页面并用 Zotero Connector 抓取后重试",
            "library": library,
            "requested_item_key": requested_key,
            "item": item,
            "source_url": item.get("url"),
            "pdf_attachment_count": 0,
        }
    pdf = attachment_summary(pdf_records[0])
    attachment_key = pdf["attachment_key"]
    try:
        file_response = api.get_text(
            f"{base_path}/items/{attachment_key}/file/view/url"
        )
        file_path = file_url_to_path(file_response.data)
    except ZoteroApiError as exc:
        if exc.status != 404:
            raise
        return {
            "schema_version": 1,
            "ok": True,
            "operation": "paper_input",
            "status": "WAITING",
            "reason_code": "PDF_FILE_NOT_SYNCED",
            "message": "Zotero 有 PDF 附件记录，但本地文件尚不可用",
            "library": library,
            "requested_item_key": requested_key,
            "item": item,
            "pdf_attachment_count": 1,
            "pdf": pdf,
        }
    except PdfGateError as exc:
        return {
            "schema_version": 1,
            "ok": True,
            "operation": "paper_input",
            "status": "BLOCKED",
            "reason_code": exc.code,
            "message": str(exc),
            "library": library,
            "requested_item_key": requested_key,
            "item": item,
            "pdf_attachment_count": 1,
            "pdf": pdf,
        }
    size, sha256, file_problem = inspect_pdf_file(file_path, gate)
    if file_problem is not None:
        status = "WAITING" if file_problem == "PDF_FILE_NOT_SYNCED" else "BLOCKED"
        messages = {
            "PDF_FILE_NOT_SYNCED": "PDF 文件尚未下载到本机",
            "PDF_FILE_UNREADABLE": "本机无法读取 PDF 文件",
            "PDF_FILE_TOO_SMALL": "PDF 文件过小，不能视为有效全文",
            "PDF_STRUCTURE_INVALID": "文件缺少有效 PDF 头或结束标记",
        }
        pdf.update(
            {
                "file_size_bytes": size,
                "sha256": sha256 or None,
                "local_path": str(file_path.resolve()),
            }
        )
        return {
            "schema_version": 1,
            "ok": True,
            "operation": "paper_input",
            "status": status,
            "reason_code": file_problem,
            "message": messages[file_problem],
            "library": library,
            "requested_item_key": requested_key,
            "item": item,
            "pdf_attachment_count": 1,
            "pdf": pdf,
        }
    pdf.update(
        {
            "file_size_bytes": size,
            "sha256": sha256,
            "local_path": str(file_path.resolve()),
        }
    )

    try:
        fulltext_response = api.get_json(
            f"{base_path}/items/{attachment_key}/fulltext"
        )
    except ZoteroApiError as exc:
        if exc.status != 404:
            raise
        pdf["fulltext_indexed"] = False
    else:
        if not isinstance(fulltext_response.data, dict):
            raise PaperInputError("INVALID_API_RESPONSE", "Zotero 全文响应格式异常")
        content = fulltext_response.data.get("content")
        if content is not None and not isinstance(content, str):
            raise PaperInputError(
                "INVALID_API_RESPONSE", "Zotero 全文 content 字段格式异常"
            )
        text_characters = sum(
            1 for character in (content or "") if not character.isspace()
        )
        pdf["fulltext_indexed"] = text_characters > 0
        pdf["text_characters"] = text_characters

    return {
        "schema_version": 1,
        "ok": True,
        "operation": "paper_input",
        "status": "READY",
        "reason_code": "PDF_READY",
        "message": "已取得可读取的本地 PDF",
        "library": library,
        "requested_item_key": requested_key,
        "item": item,
        "pdf_attachment_count": 1,
        "pdf": pdf,
    }


def prepare_demo_paper(
    zotero: ZoteroConfig,
    gate: PdfGateConfig,
    *,
    client: ZoteroClient | None = None,
) -> dict[str, Any]:
    """Resolve the reproducible public demo paper from a personal library."""
    search = prepare_paper_input(
        zotero,
        gate,
        query=DEMO_PAPER["doi"],
        library_type="user",
        client=client,
    )
    matches = [
        candidate
        for candidate in search["candidates"]
        if str(candidate.get("doi") or "").casefold() == DEMO_PAPER["doi"].casefold()
    ]
    if not matches:
        return {
            "schema_version": 1,
            "ok": True,
            "operation": "paper_input",
            "status": "IMPORT_REQUIRED",
            "reason_code": "ITEM_NOT_IN_LIBRARY",
            "message": "本地 Zotero 没有演示论文；请打开文章页并用 Zotero Connector 抓取后重试",
            "title": DEMO_PAPER["title"],
            "doi": DEMO_PAPER["doi"],
            "source_url": DEMO_PAPER["source_url"],
            "pdf_url": DEMO_PAPER["pdf_url"],
            "destination": DEMO_PAPER["destination"],
        }
    if len(matches) > 1:
        return {
            **search,
            "candidates": matches,
            "message": "本地 Zotero 有多个同 DOI 条目；请确认 item_key 后重试",
        }
    return prepare_paper_input(
        zotero,
        gate,
        item_key=matches[0]["item_key"],
        library_type="user",
        client=client,
    )


def prepare_paper_batch(
    zotero: ZoteroConfig,
    gate: PdfGateConfig,
    item_keys: list[str],
    *,
    library_type: str = "group",
    client: ZoteroClient | None = None,
) -> dict[str, Any]:
    """Resolve several item keys without stopping on per-paper problems."""
    api = client or ZoteroClient(zotero)
    results: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []

    for item_key in item_keys:
        try:
            result = prepare_paper_input(
                zotero,
                gate,
                item_key=item_key,
                library_type=library_type,
                client=api,
            )
        except (PdfGateError, ZoteroApiError, ValueError) as exc:
            result = {
                "schema_version": 1,
                "ok": False,
                "operation": "paper_input",
                "status": "FAILED",
                "reason_code": getattr(exc, "code", "INVALID_INPUT"),
                "message": str(exc),
                "requested_item_key": item_key,
            }
        results.append(result)
        if result.get("status") == "READY":
            continue
        item = result.get("item")
        title = item.get("title") if isinstance(item, dict) else None
        problem = {
            "item_key": result.get("requested_item_key", item_key),
            "title": title,
            "status": result.get("status", "FAILED"),
            "reason_code": result.get("reason_code", "UNKNOWN"),
            "message": result.get("message", "未知问题"),
        }
        if "candidates" in result:
            problem["candidates"] = result["candidates"]
        problems.append(problem)

    ready_count = sum(result.get("status") == "READY" for result in results)
    return {
        "schema_version": 1,
        "ok": True,
        "operation": "paper_input_batch",
        "status": "COMPLETED_WITH_PROBLEMS" if problems else "COMPLETED",
        "total": len(results),
        "ready_count": ready_count,
        "problem_count": len(problems),
        "results": results,
        "problems": problems,
    }
