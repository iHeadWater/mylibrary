"""Proxy overrides for owned Codex children only; never mutate os.environ or OS settings."""
from __future__ import annotations

from typing import Mapping

from hydrolitagent.cards.config import CodexProxyConfig


PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "WS_PROXY", "WSS_PROXY")
LOCAL_BYPASS = ("localhost", "127.0.0.1", "::1")


def proxy_bypass(config: CodexProxyConfig) -> tuple[str, ...]:
    # Local access cannot accidentally be routed outside by removing the config defaults.
    return tuple(dict.fromkeys((*LOCAL_BYPASS, *config.no_proxy)))


def codex_proxy_environment(
    config: CodexProxyConfig, environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    overrides = dict(environment or {})
    if not config.enabled:
        return overrides  # Off means inherit existing behavior, NOT force direct access.
    if not config.url:
        raise ValueError("启用 Codex 子进程代理时必须配置地址")
    for name in PROXY_VARIABLES:
        overrides[name] = overrides[name.lower()] = config.url
    # Explicit mode replaces inherited bypass settings (e.g. NO_PROXY=*) for this child.
    bypass = ",".join(proxy_bypass(config))
    overrides["NO_PROXY"] = overrides["no_proxy"] = bypass
    return overrides


def proxy_summary(config: CodexProxyConfig) -> dict:
    return {
        "enabled": config.enabled,
        "mode": "explicit" if config.enabled else "inherit",
        "scope": "codex_child_process",
        "url": config.url if config.enabled else None,
        "no_proxy": list(proxy_bypass(config)) if config.enabled else None,
        "connectivity_verified": False,
    }
