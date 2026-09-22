"""Small public configuration for Zotero input; never load model configuration."""
from __future__ import annotations
import json
import math
import os
import tomllib
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from hydro_platform.config import ZoteroConfig, PdfGateConfig, ConfigError

ROOT = Path(__file__).resolve().parents[4]
DEFAULT = ROOT / "configs/paper-input.toml"


def load_paper_input_config(config_file=None, *, base_url=None, group_id=None, timeout_seconds=None, require_group=False):
    selected = config_file or os.environ.get("HYDRO_PLATFORM_PAPER_INPUT_CONFIG")
    path = Path(selected).expanduser().resolve() if selected else DEFAULT
    values = {}
    if selected or path.exists():
        try:
            raw = path.read_text(encoding="utf-8-sig")
            values = json.loads(raw) if path.suffix.lower() == ".json" else tomllib.loads(raw)
            if not isinstance(values, dict):
                raise ValueError("配置必须是对象")
        except (OSError, ValueError) as exc:
            raise ConfigError(f"无法读取论文输入配置：{path}（{exc}）") from exc
    z, g = values.get("zotero", {}), values.get("pdf_gate", {})
    if not isinstance(z, dict) or not isinstance(g, dict):
        raise ConfigError("zotero 和 pdf_gate 必须是配置表")
    base = base_url if base_url is not None else os.environ.get("HYDRO_PLATFORM_ZOTERO_BASE_URL", z.get("base_url", "http://127.0.0.1:23119"))
    group = group_id if group_id is not None else os.environ.get("HYDRO_PLATFORM_ZOTERO_GROUP_ID", z.get("group_id"))
    timeout = timeout_seconds if timeout_seconds is not None else os.environ.get("HYDRO_PLATFORM_ZOTERO_TIMEOUT", z.get("timeout_seconds", 5.0))
    try:
        if not isinstance(base, str):
            raise ValueError("Zotero 地址必须是字符串")
        url = urlparse(base)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
            raise ValueError("Zotero 地址应为不带凭据或路径的 HTTP(S) 地址")
        url.port
        if group is not None:
            if isinstance(group, bool) or not str(group).isdigit() or int(group) < 1:
                raise ValueError("群组 ID 必须为正整数；个人库不需要填写")
            group = int(group)
        if require_group and group is None:
            raise ValueError("请用 --group-id 指定群组，或用 --user-library 选择个人库")
        if isinstance(timeout, bool) or not math.isfinite(float(timeout)) or not 0 < float(timeout) <= 300:
            raise ValueError("超时必须大于 0 且不超过 300 秒")
        defaults = {"min_file_size_bytes": 1024, "min_text_characters": 1000, "hash_chunk_size_bytes": 1048576}
        for key in defaults:
            value = g.get(key, defaults[key])
            if type(value) is not int or value < 1:
                raise ValueError(f"{key} 必须为正整数")
            defaults[key] = value
        return SimpleNamespace(zotero=ZoteroConfig(base_url=base.rstrip("/"), group_id=group, timeout_seconds=float(timeout)),
                               pdf_gate=PdfGateConfig(**defaults))
    except (TypeError, ValueError) as exc:
        raise ConfigError(str(exc)) from exc


def describe_config(config):
    return {"schema_version": 1, "operation": "paper_input_config", "ok": True,
            "model_required": False, "zotero": {"base_url": config.zotero.base_url,
            "group_id": config.zotero.group_id, "timeout_seconds": config.zotero.timeout_seconds},
            "pdf_gate": asdict(config.pdf_gate)}
