from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_BASE_URL = "http://127.0.0.1:23119"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_PROCESS_TIMEOUT_SECONDS = 5.0


class ConfigError(ValueError):
    """Raised when the application configuration is invalid."""


@dataclass(frozen=True)
class ZoteroConfig:
    base_url: str = DEFAULT_BASE_URL
    group_id: int | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    process_timeout_seconds: float = DEFAULT_PROCESS_TIMEOUT_SECONDS


@dataclass(frozen=True)
class ScanConfig:
    page_size: int


@dataclass(frozen=True)
class PdfGateConfig:
    min_file_size_bytes: int
    min_text_characters: int
    hash_chunk_size_bytes: int


@dataclass(frozen=True)
class TaskConfig:
    lease_seconds: int
    lock_stale_seconds: int
    max_history_entries: int


@dataclass(frozen=True)
class CardGeneratorConfig:
    adapter: str
    executable: str
    auth_mode: str
    preflight_timeout_seconds: float


@dataclass(frozen=True)
class PathConfig:
    project_root: Path
    runtime_dir: Path
    snapshot_file: Path
    tasks_file: Path
    lock_file: Path
    logs_dir: Path
    evidence_packs_dir: Path
    templates_dir: Path
    themes_dir: Path
    members_dir: Path
    activity_dir: Path
    reports_dir: Path
    prompts_dir: Path
    schemas_dir: Path


@dataclass(frozen=True)
class AppConfig:
    source_file: Path | None
    zotero: ZoteroConfig
    scan: ScanConfig
    pdf_gate: PdfGateConfig
    tasks: TaskConfig
    card_generator: CardGeneratorConfig
    paths: PathConfig


PATH_FIELDS = (
    "runtime_dir",
    "snapshot_file",
    "tasks_file",
    "lock_file",
    "logs_dir",
    "evidence_packs_dir",
    "templates_dir",
    "themes_dir",
    "members_dir",
    "activity_dir",
    "reports_dir",
    "prompts_dir",
    "schemas_dir",
)


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


def _validate_page_size(value: Any) -> int:
    if isinstance(value, bool):
        raise ConfigError("scan.page_size 必须是 1 到 100 之间的整数")
    try:
        page_size = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError("scan.page_size 必须是 1 到 100 之间的整数") from exc
    if not 1 <= page_size <= 100:
        raise ConfigError("scan.page_size 必须是 1 到 100 之间的整数")
    return page_size


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


def _validate_non_empty_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} 必须是非空字符串")
    return value.strip()


def _validate_card_generator_choice(
    name: str,
    value: Any,
    *,
    supported: set[str],
) -> str:
    normalized = _validate_non_empty_string(name, value)
    if normalized not in supported:
        choices = "、".join(sorted(supported))
        raise ConfigError(f"{name} 当前仅支持：{choices}")
    return normalized


def _path_value(value: Any, *, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"paths.{name} 必须是非空路径字符串")
    return Path(os.path.expandvars(value)).expanduser()


def _resolve_project_root(paths: dict[str, Any], config_file: Path | None) -> Path:
    if "project_root" not in paths:
        raise ConfigError("缺少 paths.project_root")
    base_dir = config_file.parent if config_file is not None else Path.cwd()
    raw_root = _path_value(paths["project_root"], name="project_root")
    root = raw_root if raw_root.is_absolute() else base_dir / raw_root
    return root.resolve()


def _resolve_project_path(
    paths: dict[str, Any], name: str, project_root: Path
) -> Path:
    if name not in paths:
        raise ConfigError(f"缺少 paths.{name}")
    raw_path = _path_value(paths[name], name=name)
    resolved = (raw_path if raw_path.is_absolute() else project_root / raw_path).resolve()
    if not resolved.is_relative_to(project_root):
        raise ConfigError(f"paths.{name} 必须位于 paths.project_root 内")
    return resolved


def _require_inside(path: Path, parent: Path, *, name: str, parent_name: str) -> None:
    if not path.is_relative_to(parent):
        raise ConfigError(f"paths.{name} 必须位于 paths.{parent_name} 内")


def _read_config_file(config_path: str | Path | None) -> tuple[Path | None, dict[str, Any]]:
    if config_path is None:
        raise ConfigError("必须提供总配置文件路径")

    config_file = Path(config_path).expanduser().resolve()
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"配置文件不存在：{config_file}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件不是有效 JSON：{config_file}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ConfigError("配置文件根节点必须是 JSON 对象")
    if data.get("schema_version", 1) != 1:
        raise ConfigError("当前仅支持 schema_version=1")
    return config_file, data


def load_config(
    config_path: str | Path | None = None,
    *,
    base_url: str | None = None,
    group_id: int | str | None = None,
    timeout_seconds: float | str | None = None,
    require_group: bool = False,
) -> AppConfig:
    config_file, data = _read_config_file(config_path)

    raw_paths = data.get("paths", {})
    if not isinstance(raw_paths, dict):
        raise ConfigError("paths 必须是 JSON 对象")
    project_root = _resolve_project_root(raw_paths, config_file)
    path_config = PathConfig(
        project_root=project_root,
        **{
            name: _resolve_project_path(raw_paths, name, project_root)
            for name in PATH_FIELDS
        },
    )
    for name in ("snapshot_file", "tasks_file", "lock_file", "logs_dir"):
        _require_inside(
            getattr(path_config, name),
            path_config.runtime_dir,
            name=name,
            parent_name="runtime_dir",
        )

    raw_zotero = data.get("zotero", {})
    if not isinstance(raw_zotero, dict):
        raise ConfigError("zotero 必须是 JSON 对象")
    if base_url is None and "base_url" not in raw_zotero:
        raise ConfigError("缺少 zotero.base_url")
    if timeout_seconds is None and "timeout_seconds" not in raw_zotero:
        raise ConfigError("缺少 zotero.timeout_seconds")
    if "process_timeout_seconds" not in raw_zotero:
        raise ConfigError("缺少 zotero.process_timeout_seconds")
    zotero_config = ZoteroConfig(
        base_url=_validate_base_url(
            base_url if base_url is not None else raw_zotero["base_url"]
        ),
        group_id=_validate_group_id(
            group_id if group_id is not None else raw_zotero.get("group_id"),
            required=require_group,
        ),
        timeout_seconds=_validate_seconds(
            "zotero.timeout_seconds",
            timeout_seconds
            if timeout_seconds is not None
            else raw_zotero["timeout_seconds"],
        ),
        process_timeout_seconds=_validate_seconds(
            "zotero.process_timeout_seconds",
            raw_zotero["process_timeout_seconds"],
        ),
    )

    raw_scan = data.get("scan", {})
    if not isinstance(raw_scan, dict):
        raise ConfigError("scan 必须是 JSON 对象")
    if "page_size" not in raw_scan:
        raise ConfigError("缺少 scan.page_size")
    scan_config = ScanConfig(page_size=_validate_page_size(raw_scan["page_size"]))

    raw_pdf_gate = data.get("pdf_gate", {})
    if not isinstance(raw_pdf_gate, dict):
        raise ConfigError("pdf_gate 必须是 JSON 对象")
    pdf_gate_fields = (
        "min_file_size_bytes",
        "min_text_characters",
        "hash_chunk_size_bytes",
    )
    for name in pdf_gate_fields:
        if name not in raw_pdf_gate:
            raise ConfigError(f"缺少 pdf_gate.{name}")
    pdf_gate_config = PdfGateConfig(
        min_file_size_bytes=_validate_positive_int(
            "pdf_gate.min_file_size_bytes", raw_pdf_gate["min_file_size_bytes"]
        ),
        min_text_characters=_validate_positive_int(
            "pdf_gate.min_text_characters", raw_pdf_gate["min_text_characters"]
        ),
        hash_chunk_size_bytes=_validate_positive_int(
            "pdf_gate.hash_chunk_size_bytes", raw_pdf_gate["hash_chunk_size_bytes"]
        ),
    )

    raw_tasks = data.get("tasks", {})
    if not isinstance(raw_tasks, dict):
        raise ConfigError("tasks 必须是 JSON 对象")
    task_fields = ("lease_seconds", "lock_stale_seconds", "max_history_entries")
    for name in task_fields:
        if name not in raw_tasks:
            raise ConfigError(f"缺少 tasks.{name}")
    task_config = TaskConfig(
        lease_seconds=_validate_positive_int(
            "tasks.lease_seconds", raw_tasks["lease_seconds"]
        ),
        lock_stale_seconds=_validate_positive_int(
            "tasks.lock_stale_seconds", raw_tasks["lock_stale_seconds"]
        ),
        max_history_entries=_validate_positive_int(
            "tasks.max_history_entries", raw_tasks["max_history_entries"]
        ),
    )

    raw_card_generator = data.get("card_generator", {})
    if not isinstance(raw_card_generator, dict):
        raise ConfigError("card_generator 必须是 JSON 对象")
    card_generator_fields = (
        "adapter",
        "executable",
        "auth_mode",
        "preflight_timeout_seconds",
    )
    for name in card_generator_fields:
        if name not in raw_card_generator:
            raise ConfigError(f"缺少 card_generator.{name}")
    card_generator_config = CardGeneratorConfig(
        adapter=_validate_card_generator_choice(
            "card_generator.adapter",
            raw_card_generator["adapter"],
            supported={"codex_cli"},
        ),
        executable=_validate_non_empty_string(
            "card_generator.executable",
            raw_card_generator["executable"],
        ),
        auth_mode=_validate_card_generator_choice(
            "card_generator.auth_mode",
            raw_card_generator["auth_mode"],
            supported={"chatgpt_account"},
        ),
        preflight_timeout_seconds=_validate_seconds(
            "card_generator.preflight_timeout_seconds",
            raw_card_generator["preflight_timeout_seconds"],
        ),
    )

    return AppConfig(
        source_file=config_file,
        zotero=zotero_config,
        scan=scan_config,
        pdf_gate=pdf_gate_config,
        tasks=task_config,
        card_generator=card_generator_config,
        paths=path_config,
    )
