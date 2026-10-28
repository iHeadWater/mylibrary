"""Scalar and structured validators for configuration values.

Every validator either returns the normalized value or raises ``ConfigError``.
They are pure functions: no filesystem access, no environment lookup.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .models import ConfigError


def _validate_base_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("zotero.base_url 必须是非空字符串")

    normalized = value.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ConfigError("zotero.base_url 必须是本机 HTTP 地址")
    if parsed.port is None or not 1 <= parsed.port <= 65535:
        raise ConfigError("zotero.base_url 必须包含有效端口")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ConfigError("zotero.base_url 不能包含路径、查询参数或片段")
    return normalized


def _validate_group_id(value: Any, *, required: bool) -> int | None:
    if value is None:
        if required:
            raise ConfigError("缺少 zotero.group_id；请先运行 discover-groups")
        return None
    if isinstance(value, bool):
        raise ConfigError("zotero.group_id 必须是正整数")
    try:
        group_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError("zotero.group_id 必须是正整数") from exc
    if group_id <= 0:
        raise ConfigError("zotero.group_id 必须是正整数")
    return group_id


def _validate_seconds(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ConfigError(f"{name} 必须是正数")
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} 必须是正数") from exc
    if seconds <= 0:
        raise ConfigError(f"{name} 必须是正数")
    return seconds


def _validate_positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{name} 必须是正整数")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} 必须是正整数") from exc
    if number <= 0:
        raise ConfigError(f"{name} 必须是正整数")
    return number


def _validate_non_negative_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{name} 必须是非负整数")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} 必须是非负整数") from exc
    if number < 0:
        raise ConfigError(f"{name} 必须是非负整数")
    return number


def _validate_non_empty_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} 必须是非空字符串")
    return value.strip()


def _validate_optional_non_empty_string(name: str, value: Any) -> str | None:
    if value is None:
        return None
    return _validate_non_empty_string(name, value)


def _validate_optional_card_generator_choice(
    name: str,
    value: Any,
    *,
    supported: set[str] | frozenset[str],
) -> str | None:
    if value is None:
        return None
    normalized = _validate_non_empty_string(name, value).casefold()
    if normalized not in supported:
        choices = "、".join(sorted(supported))
        raise ConfigError(f"{name} 当前仅支持：{choices}，或 null")
    return normalized


def _validate_server_name(name: str, value: Any) -> str:
    normalized = _validate_non_empty_string(name, value)
    if not all(character.isalnum() or character in {"_", "-"} for character in normalized):
        raise ConfigError(f"{name} 只能包含字母、数字、下划线和连字符")
    return normalized


__all__ = [
    "_validate_base_url",
    "_validate_group_id",
    "_validate_non_empty_string",
    "_validate_non_negative_int",
    "_validate_optional_card_generator_choice",
    "_validate_optional_non_empty_string",
    "_validate_positive_int",
    "_validate_seconds",
    "_validate_server_name",
]
