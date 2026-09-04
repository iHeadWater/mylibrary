from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hydro_platform.config import ZoteroConfig
from hydro_platform.zotero import ZoteroClient


IGNORED_ITEM_TYPES = {"attachment", "note", "annotation"}


class SnapshotError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _header(headers: dict[str, str], name: str) -> str | None:
    wanted = name.lower()
    return next((value for key, value in headers.items() if key.lower() == wanted), None)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _item_key(record: dict[str, Any], data: dict[str, Any]) -> str | None:
    for value in (record.get("key"), data.get("key")):
        if isinstance(value, str) and value:
            return value
    return None


def _item_version(record: dict[str, Any], data: dict[str, Any]) -> int | None:
    return _positive_int(record.get("version")) or _positive_int(data.get("version"))


def _is_pdf_attachment(data: dict[str, Any]) -> bool:
    if data.get("itemType") != "attachment":
        return False
    content_type = str(data.get("contentType") or "").lower()
    filename = str(data.get("filename") or "").lower()
    return content_type == "application/pdf" or filename.endswith(".pdf")


def fetch_snapshot(
    config: ZoteroConfig,
    *,
    page_size: int,
    client: ZoteroClient | None = None,
) -> dict[str, Any]:
    if config.group_id is None:
        raise SnapshotError("CONFIG_ERROR", "扫描需要目标 Zotero 群组 ID")
    if page_size <= 0 or page_size > 100:
        raise SnapshotError("CONFIG_ERROR", "page_size 必须在 1 到 100 之间")

    api = client or ZoteroClient(config)
    records: list[dict[str, Any]] = []
    start = 0
    total: int | None = None
    library_version: int | None = None

    while total is None or start < total:
        response = api.get_json(
            f"/api/groups/{config.group_id}/items?limit={page_size}&start={start}"
        )
        if not isinstance(response.data, list):
            raise SnapshotError("INVALID_API_RESPONSE", "Zotero 条目列表不是数组")
        if any(not isinstance(record, dict) for record in response.data):
            raise SnapshotError("INVALID_API_RESPONSE", "Zotero 条目记录格式异常")

        records.extend(response.data)
        page_total = _positive_int(_header(response.headers, "Total-Results"))
        if total is None:
            total = page_total if page_total is not None else len(response.data)
        page_version = _positive_int(_header(response.headers, "Last-Modified-Version"))
        if page_version is not None:
            library_version = max(library_version or 0, page_version)

        if not response.data:
            break
        start += len(response.data)
        if page_total is None and len(response.data) < page_size:
            break

    parents: dict[str, dict[str, Any]] = {}
    pdf_attachments: dict[str, dict[str, Any]] = {}

    for record in records:
        data = record.get("data")
        if not isinstance(data, dict):
            raise SnapshotError("INVALID_API_RESPONSE", "Zotero 条目缺少 data 对象")
        key = _item_key(record, data)
        if key is None:
            raise SnapshotError("INVALID_API_RESPONSE", "Zotero 条目缺少 Key")

        item_type = str(data.get("itemType") or "")
        parent_key = data.get("parentItem")
        if _is_pdf_attachment(data):
            pdf_attachments[key] = {
                "parent_key": parent_key if isinstance(parent_key, str) else None,
                "version": _item_version(record, data),
                "content_type": data.get("contentType"),
                "filename": data.get("filename"),
                "link_mode": data.get("linkMode"),
                "date_modified": data.get("dateModified"),
            }
        elif item_type not in IGNORED_ITEM_TYPES and not parent_key:
            parents[key] = {
                "version": _item_version(record, data),
                "item_type": item_type,
                "title": data.get("title"),
                "date_modified": data.get("dateModified"),
            }

    return {
        "schema_version": 1,
        "group_id": config.group_id,
        "captured_at": _now(),
        "library_version": library_version,
        "counts": {
            "all_items": len(records),
            "parents": len(parents),
            "pdf_attachments": len(pdf_attachments),
        },
        "parents": dict(sorted(parents.items())),
        "pdf_attachments": dict(sorted(pdf_attachments.items())),
    }


def load_snapshot(path: str | Path) -> dict[str, Any] | None:
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        return None
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError("SNAPSHOT_INVALID", f"无法读取本地快照：{snapshot_path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise SnapshotError("SNAPSHOT_INVALID", "本地快照结构或版本无效")
    if not isinstance(data.get("parents"), dict) or not isinstance(data.get("pdf_attachments"), dict):
        raise SnapshotError("SNAPSHOT_INVALID", "本地快照缺少父条目或 PDF 附件映射")
    return data


def save_snapshot(path: str | Path, snapshot: dict[str, Any]) -> None:
    snapshot_path = Path(path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = snapshot_path.with_suffix(snapshot_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, snapshot_path)


def compare_snapshots(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    old_parents = previous["parents"]
    new_parents = current["parents"]
    old_pdfs = previous["pdf_attachments"]
    new_pdfs = current["pdf_attachments"]

    for key in sorted(new_parents.keys() - old_parents.keys()):
        changes.append(
            {
                "type": "ITEM_ADDED",
                "item_key": key,
                "title": new_parents[key].get("title"),
            }
        )

    for key in sorted(old_parents.keys() - new_parents.keys()):
        changes.append(
            {
                "type": "ITEM_REMOVED",
                "item_key": key,
                "title": old_parents[key].get("title"),
            }
        )

    for key in sorted(new_pdfs.keys() - old_pdfs.keys()):
        changes.append(
            {
                "type": "PDF_ADDED",
                "attachment_key": key,
                "parent_key": new_pdfs[key].get("parent_key"),
                "filename": new_pdfs[key].get("filename"),
            }
        )

    for key in sorted(old_pdfs.keys() - new_pdfs.keys()):
        changes.append(
            {
                "type": "PDF_REMOVED",
                "attachment_key": key,
                "parent_key": old_pdfs[key].get("parent_key"),
                "filename": old_pdfs[key].get("filename"),
            }
        )

    for key in sorted(new_pdfs.keys() & old_pdfs.keys()):
        before = old_pdfs[key]
        after = new_pdfs[key]
        if before != after:
            changes.append(
                {
                    "type": "PDF_ATTACHMENT_CHANGED",
                    "attachment_key": key,
                    "parent_key": after.get("parent_key"),
                    "filename": after.get("filename"),
                    "previous_version": before.get("version"),
                    "current_version": after.get("version"),
                }
            )

    return changes


def scan_group(
    config: ZoteroConfig,
    state_path: str | Path,
    *,
    page_size: int,
    client: ZoteroClient | None = None,
) -> dict[str, Any]:
    previous = load_snapshot(state_path)
    current = fetch_snapshot(config, client=client, page_size=page_size)

    if previous is not None and previous.get("group_id") != config.group_id:
        raise SnapshotError(
            "SNAPSHOT_GROUP_MISMATCH",
            "本地快照属于另一个 Zotero 群组，拒绝覆盖",
        )

    mode = "baseline" if previous is None else "incremental"
    changes = [] if previous is None else compare_snapshots(previous, current)
    save_snapshot(state_path, current)
    return {
        "schema_version": 1,
        "ok": True,
        "mode": mode,
        "group_id": config.group_id,
        "captured_at": current["captured_at"],
        "library_version": current["library_version"],
        "counts": current["counts"],
        "change_count": len(changes),
        "changes": changes,
        "state_path": str(Path(state_path).resolve()),
    }
