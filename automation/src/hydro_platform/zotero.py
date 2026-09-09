from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hydro_platform.config import ZoteroConfig


class ZoteroApiError(RuntimeError):
    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ApiResponse:
    data: Any
    headers: dict[str, str]


class ZoteroClient:
    def __init__(self, config: ZoteroConfig):
        self.config = config

    def get_json(self, path: str) -> ApiResponse:
        raw, headers, status = self._get(path, accept="application/json")
        try:
            data = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ZoteroApiError(
                "INVALID_API_RESPONSE",
                f"Zotero 返回了无法解析的 JSON：{path}",
                status,
            ) from exc
        return ApiResponse(data=data, headers=headers)

    def get_text(self, path: str) -> ApiResponse:
        raw, headers, status = self._get(path, accept="text/plain")
        try:
            data = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ZoteroApiError(
                "INVALID_API_RESPONSE",
                f"Zotero 返回了无法解析的文本：{path}",
                status,
            ) from exc
        return ApiResponse(data=data, headers=headers)

    def _get(self, path: str, *, accept: str) -> tuple[bytes, dict[str, str], int]:
        request = Request(
            f"{self.config.base_url}{path}",
            headers={
                "Accept": accept,
                "Zotero-API-Version": "3",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
                return raw, dict(response.headers.items()), response.status
        except HTTPError as exc:
            exc.close()
            if exc.code == 403:
                code = "GROUP_PERMISSION_DENIED"
            elif exc.code == 404:
                code = "GROUP_NOT_AVAILABLE"
            else:
                code = "ZOTERO_HTTP_ERROR"
            raise ZoteroApiError(code, f"Zotero API 返回 HTTP {exc.code}：{path}", exc.code) from exc
        except (URLError, TimeoutError) as exc:
            raise ZoteroApiError("LOCAL_API_UNAVAILABLE", f"无法连接本机 Zotero API：{exc}") from exc


def zotero_process_running(timeout_seconds: float = 5.0) -> bool | None:
    system = platform.system()
    try:
        if system == "Windows":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq zotero.exe", "/FO", "CSV", "/NH"],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                return None
            return "zotero.exe" in result.stdout.lower()

        process_name = "Zotero" if system == "Darwin" else "zotero"
        result = subprocess.run(
            ["pgrep", "-x", process_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _failure(
    checks: list[dict[str, str]],
    code: str,
    message: str,
    config: ZoteroConfig,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": False,
        "checked_at": _now(),
        "base_url": config.base_url,
        "group_id": config.group_id,
        "checks": checks,
        "error": {"code": code, "message": message},
    }


def _group_id(record: Any) -> int | None:
    if not isinstance(record, dict):
        return None
    candidates = [record.get("id"), record.get("key")]
    data = record.get("data")
    if isinstance(data, dict):
        candidates.extend([data.get("id"), data.get("groupID")])
    for candidate in candidates:
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _group_name(record: dict[str, Any]) -> str:
    data = record.get("data")
    if isinstance(data, dict) and isinstance(data.get("name"), str):
        return data["name"]
    if isinstance(record.get("name"), str):
        return record["name"]
    return ""


def discover_groups(
    config: ZoteroConfig,
    *,
    client: ZoteroClient | None = None,
    process_checker: Callable[[], bool | None] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    running = (
        process_checker()
        if process_checker is not None
        else zotero_process_running(config.process_timeout_seconds)
    )
    if running is False:
        checks.append(_check("zotero_process", "fail", "未发现 Zotero 进程"))
        return _failure(checks, "ZOTERO_NOT_RUNNING", "Zotero Desktop 当前没有运行", config)
    if running is None:
        checks.append(_check("zotero_process", "warn", "无法判断 Zotero 进程状态，继续检查 API"))
    else:
        checks.append(_check("zotero_process", "pass", "Zotero 进程正在运行"))

    api = client or ZoteroClient(config)
    try:
        response = api.get_json("/api/users/0/groups")
        checks.append(_check("local_api", "pass", "本地 API 可访问"))
    except ZoteroApiError as exc:
        checks.append(_check("local_api", "fail", str(exc)))
        return _failure(checks, exc.code, str(exc), config)

    if not isinstance(response.data, list):
        checks.append(_check("group_inventory", "fail", "群组列表格式异常"))
        return _failure(checks, "INVALID_API_RESPONSE", "Zotero 群组列表不是数组", config)

    groups = [
        {"group_id": group_id, "name": _group_name(record)}
        for record in response.data
        if (group_id := _group_id(record)) is not None
    ]
    checks.append(_check("group_inventory", "pass", f"发现 {len(groups)} 个可见群组"))
    return {
        "schema_version": 1,
        "ok": True,
        "checked_at": _now(),
        "base_url": config.base_url,
        "checks": checks,
        "groups": groups,
    }


def preflight(
    config: ZoteroConfig,
    *,
    client: ZoteroClient | None = None,
    process_checker: Callable[[], bool | None] | None = None,
) -> dict[str, Any]:
    discovered = discover_groups(config, client=client, process_checker=process_checker)
    if not discovered["ok"]:
        return discovered

    checks = discovered["checks"]
    groups = discovered["groups"]
    target = next((group for group in groups if group["group_id"] == config.group_id), None)
    if target is None:
        checks.append(_check("target_group", "fail", "目标群组不可见或尚未同步"))
        return _failure(
            checks,
            "GROUP_NOT_AVAILABLE",
            f"找不到目标 Zotero 群组：{config.group_id}",
            config,
        )

    api = client or ZoteroClient(config)
    try:
        response = api.get_json(f"/api/groups/{config.group_id}/items/top?limit=1")
    except ZoteroApiError as exc:
        checks.append(_check("target_group", "fail", str(exc)))
        return _failure(checks, exc.code, str(exc), config)

    item_count = response.headers.get("Total-Results")
    checks.append(_check("target_group", "pass", f"目标群组可读取：{target['name'] or config.group_id}"))
    return {
        "schema_version": 1,
        "ok": True,
        "checked_at": _now(),
        "base_url": config.base_url,
        "group_id": config.group_id,
        "group_name": target["name"],
        "item_count": int(item_count) if item_count and item_count.isdigit() else None,
        "checks": checks,
    }
