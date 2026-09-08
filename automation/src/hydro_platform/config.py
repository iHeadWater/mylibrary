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
SUPPORTED_REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)
MULTI_AGENT_PROTOCOL_VERSION = "rough-card-multi-agent-v1"
LOCAL_PATH_PROTOCOL_VERSION = "rough-card-multi-agent-v2"
SINGLE_AGENT_PROTOCOL_VERSION = "rough-card-single-agent-v1"
REQUIRED_CARD_WORKFLOW_ROLES = (
    "fact_extractor_a",
    "fact_extractor_b",
    "fact_adjudicator",
    "critical_analyst",
    "card_synthesizer",
    "adversarial_reviewer",
)


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
class PdfReaderConfig:
    adapter: str
    server_name: str
    python_executable: str | None
    server_file: Path
    pdfinfo_executable: str
    pdftotext_executable: str
    pdftoppm_executable: str
    render_dpi: int
    max_pages_per_call: int
    output_token_limit: int
    startup_timeout_seconds: float
    tool_timeout_seconds: float


@dataclass(frozen=True)
class CardWorkflowRoleConfig:
    model: str | None
    reasoning_effort: str | None
    timeout_seconds: float


@dataclass(frozen=True)
class CardQualityWorkflowConfig:
    protocol_version: str
    fact_extraction_prompt_file: Path
    fact_adjudication_prompt_file: Path
    critical_analysis_prompt_file: Path
    adversarial_review_prompt_file: Path
    fact_extraction_schema_file: Path
    fact_adjudication_schema_file: Path
    critical_analysis_schema_file: Path
    adversarial_review_schema_file: Path
    minimum_verified_facts: int
    minimum_critical_analyses: int
    minimum_adversarial_challenges: int
    maximum_unresolved_high_severity: int
    roles: dict[str, CardWorkflowRoleConfig]


@dataclass(frozen=True)
class ProgressConfig:
    enabled: bool = True
    heartbeat_interval_seconds: float = 15


@dataclass(frozen=True)
class ConnectionGuardConfig:
    reconnect_event_limit: int = 2
    recovery_timeout_seconds: float = 60
    idle_timeout_seconds: float = 300
    pdf_tool_call_limit: int = 2
    reconnect_stop_enabled: bool = True


@dataclass(frozen=True)
class PdfDirectTrialConfig:
    prompt_file: Path
    schema_file: Path
    timeout_seconds: float
    windows_sandbox: str = "elevated"
    shell_executable: str = "powershell"
    preflight_timeout_seconds: float = 120
    python_executable: str | None = None
    text_extractor: str = "pdftotext"
    reading_prompt_file: Path | None = None


@dataclass(frozen=True)
class CardGeneratorConfig:
    adapter: str
    executable: str
    auth_mode: str
    preflight_timeout_seconds: float
    model: str | None
    reasoning_effort: str | None
    smoke_test_timeout_seconds: float
    generation_timeout_seconds: float
    pdf_reader: PdfReaderConfig
    workflow_mode: str = "multi_agent"  # legacy configurations remain explicit/readable
    multi_agent_workflow: CardQualityWorkflowConfig | None = None
    progress: ProgressConfig = ProgressConfig()
    connection_guard: ConnectionGuardConfig = ConnectionGuardConfig()
    pdf_direct_trial: PdfDirectTrialConfig | None = None
    runtime_dir: Path | None = None


@dataclass(frozen=True)
class PathConfig:
    project_root: Path
    runtime_dir: Path
    snapshot_file: Path
    tasks_file: Path
    lock_file: Path
    logs_dir: Path
    card_trials_dir: Path
    evidence_packs_dir: Path
    templates_dir: Path
    evidence_card_templates_dir: Path
    evidence_card_template_catalog_file: Path
    evidence_card_generation_prompt_file: Path
    card_generation_output_schema_file: Path
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
    "card_trials_dir",
    "evidence_packs_dir",
    "templates_dir",
    "evidence_card_templates_dir",
    "evidence_card_template_catalog_file",
    "evidence_card_generation_prompt_file",
    "card_generation_output_schema_file",
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


def _path_value(value: Any, *, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        qualified_name = name if "." in name else f"paths.{name}"
        raise ConfigError(f"{qualified_name} 必须是非空路径字符串")
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
    for name in (
        "snapshot_file",
        "tasks_file",
        "lock_file",
        "logs_dir",
        "card_trials_dir",
    ):
        _require_inside(
            getattr(path_config, name),
            path_config.runtime_dir,
            name=name,
            parent_name="runtime_dir",
        )
    _require_inside(
        path_config.evidence_card_templates_dir,
        path_config.templates_dir,
        name="evidence_card_templates_dir",
        parent_name="templates_dir",
    )
    _require_inside(
        path_config.evidence_card_template_catalog_file,
        path_config.evidence_card_templates_dir,
        name="evidence_card_template_catalog_file",
        parent_name="evidence_card_templates_dir",
    )
    _require_inside(
        path_config.evidence_card_generation_prompt_file,
        path_config.prompts_dir,
        name="evidence_card_generation_prompt_file",
        parent_name="prompts_dir",
    )
    _require_inside(
        path_config.card_generation_output_schema_file,
        path_config.schemas_dir,
        name="card_generation_output_schema_file",
        parent_name="schemas_dir",
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
        "model",
        "reasoning_effort",
        "smoke_test_timeout_seconds",
        "generation_timeout_seconds",
        "pdf_reader",
    )
    for name in card_generator_fields:
        if name not in raw_card_generator:
            raise ConfigError(f"缺少 card_generator.{name}")
    raw_progress = raw_card_generator.get("progress", {
        "enabled": True, "heartbeat_interval_seconds": 15,
    })
    if not isinstance(raw_progress, dict) or set(raw_progress) != {
        "enabled", "heartbeat_interval_seconds",
    }:
        raise ConfigError("card_generator.progress 必须包含 enabled 和 heartbeat_interval_seconds")
    interval = raw_progress["heartbeat_interval_seconds"]
    if (
        not isinstance(raw_progress["enabled"], bool)
        or isinstance(interval, bool)
        or not isinstance(interval, (int, float))
        or not 1 <= interval <= 300
    ):
        raise ConfigError("card_generator.progress.enabled 必须是布尔值，心跳间隔必须在 1–300 秒之间")
    progress_config = ProgressConfig(raw_progress["enabled"], float(interval))
    guard_defaults = ConnectionGuardConfig()
    guard_fields = {
        "reconnect_event_limit": (guard_defaults.reconnect_event_limit, 1, 10, int),
        "recovery_timeout_seconds": (guard_defaults.recovery_timeout_seconds, 1, 300, float),
        "idle_timeout_seconds": (guard_defaults.idle_timeout_seconds, 1, 3600, float),
        "pdf_tool_call_limit": (guard_defaults.pdf_tool_call_limit, 1, 5, int),
    }
    raw_guard = raw_card_generator.get("connection_guard", {
        name: rules[0] for name, rules in guard_fields.items()
    })
    if (
        not isinstance(raw_guard, dict)
        or not set(guard_fields).issubset(raw_guard)
        or set(raw_guard) - set(guard_fields) - {"reconnect_stop_enabled"}
    ):
        raise ConfigError("card_generator.connection_guard 必须完整填写四个限额字段，可选 reconnect_stop_enabled，不能包含未知字段")
    reconnect_stop_enabled = raw_guard.get("reconnect_stop_enabled", True)
    if not isinstance(reconnect_stop_enabled, bool):
        raise ConfigError("card_generator.connection_guard.reconnect_stop_enabled 必须是布尔值")
    guard_values: dict[str, Any] = {}
    for name, (_, minimum, maximum, converter) in guard_fields.items():
        value = raw_guard[name]
        valid_type = isinstance(value, int) if converter is int else isinstance(value, (int, float))
        if isinstance(value, bool) or not valid_type or not minimum <= value <= maximum:
            raise ConfigError(f"card_generator.connection_guard.{name} 必须在 {minimum}–{maximum} 之间")
        guard_values[name] = converter(value)
    connection_guard = ConnectionGuardConfig(**guard_values, reconnect_stop_enabled=reconnect_stop_enabled)
    raw_pdf_reader = raw_card_generator["pdf_reader"]
    if not isinstance(raw_pdf_reader, dict):
        raise ConfigError("card_generator.pdf_reader 必须是 JSON 对象")
    pdf_reader_fields = (
        "adapter",
        "server_name",
        "python_executable",
        "server_file",
        "pdfinfo_executable",
        "pdftotext_executable",
        "pdftoppm_executable",
        "render_dpi",
        "max_pages_per_call",
        "output_token_limit",
        "startup_timeout_seconds",
        "tool_timeout_seconds",
    )
    for name in pdf_reader_fields:
        if name not in raw_pdf_reader:
            raise ConfigError(f"缺少 card_generator.pdf_reader.{name}")
    raw_server_file = _path_value(
        raw_pdf_reader["server_file"],
        name="card_generator.pdf_reader.server_file",
    )
    server_file = (
        raw_server_file
        if raw_server_file.is_absolute()
        else project_root / raw_server_file
    ).resolve()
    if not server_file.is_relative_to(project_root):
        raise ConfigError(
            "card_generator.pdf_reader.server_file 必须位于 paths.project_root 内"
        )
    pdf_reader_config = PdfReaderConfig(
        adapter=_validate_card_generator_choice(
            "card_generator.pdf_reader.adapter",
            raw_pdf_reader["adapter"],
            supported={"project_mcp", "local_path"},
        ),
        server_name=_validate_server_name(
            "card_generator.pdf_reader.server_name",
            raw_pdf_reader["server_name"],
        ),
        python_executable=_validate_optional_non_empty_string(
            "card_generator.pdf_reader.python_executable",
            raw_pdf_reader["python_executable"],
        ),
        server_file=server_file,
        pdfinfo_executable=_validate_non_empty_string(
            "card_generator.pdf_reader.pdfinfo_executable",
            raw_pdf_reader["pdfinfo_executable"],
        ),
        pdftotext_executable=_validate_non_empty_string(
            "card_generator.pdf_reader.pdftotext_executable",
            raw_pdf_reader["pdftotext_executable"],
        ),
        pdftoppm_executable=_validate_non_empty_string(
            "card_generator.pdf_reader.pdftoppm_executable",
            raw_pdf_reader["pdftoppm_executable"],
        ),
        render_dpi=_validate_positive_int(
            "card_generator.pdf_reader.render_dpi",
            raw_pdf_reader["render_dpi"],
        ),
        max_pages_per_call=_validate_positive_int(
            "card_generator.pdf_reader.max_pages_per_call",
            raw_pdf_reader["max_pages_per_call"],
        ),
        output_token_limit=_validate_positive_int(
            "card_generator.pdf_reader.output_token_limit",
            raw_pdf_reader["output_token_limit"],
        ),
        startup_timeout_seconds=_validate_seconds(
            "card_generator.pdf_reader.startup_timeout_seconds",
            raw_pdf_reader["startup_timeout_seconds"],
        ),
        tool_timeout_seconds=_validate_seconds(
            "card_generator.pdf_reader.tool_timeout_seconds",
            raw_pdf_reader["tool_timeout_seconds"],
        ),
    )
    if not 72 <= pdf_reader_config.render_dpi <= 300:
        raise ConfigError("card_generator.pdf_reader.render_dpi 必须在 72 到 300 之间")
    if pdf_reader_config.max_pages_per_call > 10:
        raise ConfigError(
            "card_generator.pdf_reader.max_pages_per_call 不能大于 10"
        )
    if pdf_reader_config.output_token_limit > 200000:
        raise ConfigError(
            "card_generator.pdf_reader.output_token_limit 不能大于 200000"
        )

    workflow_mode = raw_card_generator.get("workflow_mode", "multi_agent")
    if workflow_mode not in {"single_agent", "multi_agent"}:
        raise ConfigError("card_generator.workflow_mode 仅支持 single_agent 或 multi_agent")
    multi_agent_workflow = None
    if workflow_mode == "single_agent":
        if pdf_reader_config.adapter != "local_path":
            raise ConfigError("single_agent 当前要求 pdf_reader.adapter=local_path")
        if raw_card_generator.get("multi_agent_workflow") is not None:
            raise ConfigError("single_agent 请移除 multi_agent_workflow，避免无效配置造成误解")
    else:
        raw_workflow = raw_card_generator.get("multi_agent_workflow")
        if not isinstance(raw_workflow, dict):
            raise ConfigError("card_generator.multi_agent_workflow 必须是 JSON 对象")
        workflow_fields = (
            "protocol_version",
            "prompts",
            "schemas",
            "quality_gate",
            "roles",
        )
        for name in workflow_fields:
            if name not in raw_workflow:
                raise ConfigError(f"缺少 card_generator.multi_agent_workflow.{name}")
        protocol_version = _validate_non_empty_string(
            "card_generator.multi_agent_workflow.protocol_version",
            raw_workflow["protocol_version"],
        )
        expected_protocol = (LOCAL_PATH_PROTOCOL_VERSION if pdf_reader_config.adapter == "local_path"
                             else MULTI_AGENT_PROTOCOL_VERSION)
        if protocol_version != expected_protocol:
            raise ConfigError(
                "card_generator.multi_agent_workflow.protocol_version 当前仅支持 "
                f"{expected_protocol}（与 pdf_reader.adapter 对应）"
            )

        raw_workflow_prompts = raw_workflow["prompts"]
        raw_workflow_schemas = raw_workflow["schemas"]
        if not isinstance(raw_workflow_prompts, dict):
            raise ConfigError("card_generator.multi_agent_workflow.prompts 必须是 JSON 对象")
        if not isinstance(raw_workflow_schemas, dict):
            raise ConfigError("card_generator.multi_agent_workflow.schemas 必须是 JSON 对象")
        workflow_file_keys = (
            "fact_extraction",
            "fact_adjudication",
            "critical_analysis",
            "adversarial_review",
        )
        if set(raw_workflow_prompts) != set(workflow_file_keys):
            raise ConfigError(
                "card_generator.multi_agent_workflow.prompts 必须且只能包含："
                + "、".join(workflow_file_keys)
            )
        if set(raw_workflow_schemas) != set(workflow_file_keys):
            raise ConfigError(
                "card_generator.multi_agent_workflow.schemas 必须且只能包含："
                + "、".join(workflow_file_keys)
            )

        def workflow_file(
            collection: dict[str, Any],
            key: str,
            *,
            collection_name: str,
            parent: Path,
        ) -> Path:
            config_name = f"card_generator.multi_agent_workflow.{collection_name}.{key}"
            raw_path = _path_value(collection[key], name=config_name)
            resolved = (
                raw_path if raw_path.is_absolute() else project_root / raw_path
            ).resolve()
            if not resolved.is_relative_to(parent):
                raise ConfigError(f"{config_name} 必须位于 {parent} 内")
            return resolved

        prompt_paths = {
            key: workflow_file(
                raw_workflow_prompts,
                key,
                collection_name="prompts",
                parent=path_config.prompts_dir,
            )
            for key in workflow_file_keys
        }
        schema_paths = {
            key: workflow_file(
                raw_workflow_schemas,
                key,
                collection_name="schemas",
                parent=path_config.schemas_dir,
            )
            for key in workflow_file_keys
        }

        raw_quality_gate = raw_workflow["quality_gate"]
        quality_fields = (
            "minimum_verified_facts",
            "minimum_critical_analyses",
            "minimum_adversarial_challenges",
            "maximum_unresolved_high_severity",
        )
        if not isinstance(raw_quality_gate, dict) or set(raw_quality_gate) != set(
            quality_fields
        ):
            raise ConfigError(
                "card_generator.multi_agent_workflow.quality_gate 字段不完整或包含未知字段"
            )

        raw_roles = raw_workflow["roles"]
        if not isinstance(raw_roles, dict) or set(raw_roles) != set(
            REQUIRED_CARD_WORKFLOW_ROLES
        ):
            raise ConfigError(
                "card_generator.multi_agent_workflow.roles 必须且只能包含："
                + "、".join(REQUIRED_CARD_WORKFLOW_ROLES)
            )
        workflow_roles: dict[str, CardWorkflowRoleConfig] = {}
        for role_name in REQUIRED_CARD_WORKFLOW_ROLES:
            raw_role = raw_roles[role_name]
            if not isinstance(raw_role, dict) or set(raw_role) != {
                "model",
                "reasoning_effort",
                "timeout_seconds",
            }:
                raise ConfigError(
                    f"card_generator.multi_agent_workflow.roles.{role_name} "
                    "必须包含 model、reasoning_effort、timeout_seconds"
                )
            workflow_roles[role_name] = CardWorkflowRoleConfig(
                model=_validate_optional_non_empty_string(
                    f"card_generator.multi_agent_workflow.roles.{role_name}.model",
                    raw_role["model"],
                ),
                reasoning_effort=_validate_optional_card_generator_choice(
                    (
                        "card_generator.multi_agent_workflow.roles."
                        f"{role_name}.reasoning_effort"
                    ),
                    raw_role["reasoning_effort"],
                    supported=SUPPORTED_REASONING_EFFORTS,
                ),
                timeout_seconds=_validate_seconds(
                    f"card_generator.multi_agent_workflow.roles.{role_name}.timeout_seconds",
                    raw_role["timeout_seconds"],
                ),
            )

        multi_agent_workflow = CardQualityWorkflowConfig(
            protocol_version=protocol_version,
            fact_extraction_prompt_file=prompt_paths["fact_extraction"],
            fact_adjudication_prompt_file=prompt_paths["fact_adjudication"],
            critical_analysis_prompt_file=prompt_paths["critical_analysis"],
            adversarial_review_prompt_file=prompt_paths["adversarial_review"],
            fact_extraction_schema_file=schema_paths["fact_extraction"],
            fact_adjudication_schema_file=schema_paths["fact_adjudication"],
            critical_analysis_schema_file=schema_paths["critical_analysis"],
            adversarial_review_schema_file=schema_paths["adversarial_review"],
            minimum_verified_facts=_validate_positive_int(
                "card_generator.multi_agent_workflow.quality_gate.minimum_verified_facts",
                raw_quality_gate["minimum_verified_facts"],
            ),
            minimum_critical_analyses=_validate_positive_int(
                "card_generator.multi_agent_workflow.quality_gate.minimum_critical_analyses",
                raw_quality_gate["minimum_critical_analyses"],
            ),
            minimum_adversarial_challenges=_validate_positive_int(
                "card_generator.multi_agent_workflow.quality_gate.minimum_adversarial_challenges",
                raw_quality_gate["minimum_adversarial_challenges"],
            ),
            maximum_unresolved_high_severity=_validate_non_negative_int(
                (
                    "card_generator.multi_agent_workflow.quality_gate."
                    "maximum_unresolved_high_severity"
                ),
                raw_quality_gate["maximum_unresolved_high_severity"],
            ),
            roles=workflow_roles,
        )

    raw_direct = raw_card_generator.get("pdf_direct_trial", {
        "prompt_file": str(path_config.prompts_dir / "pdf-direct-read-trial-v2.md"),
        "schema_file": str(path_config.schemas_dir / "pdf-direct-read-trial-output.schema.json"),
        "timeout_seconds": 1200,
    })
    direct_required = {"prompt_file", "schema_file", "timeout_seconds"}
    direct_optional = {"windows_sandbox", "shell_executable", "preflight_timeout_seconds", "python_executable", "text_extractor", "reading_prompt_file"}
    if (not isinstance(raw_direct, dict) or not direct_required <= set(raw_direct)
        or set(raw_direct) - direct_required - direct_optional):
        raise ConfigError("card_generator.pdf_direct_trial 必须填写 prompt_file、schema_file、timeout_seconds")
    direct_paths = {}
    raw_direct = {**raw_direct, "reading_prompt_file": raw_direct.get(
        "reading_prompt_file", str(path_config.prompts_dir / "pdf-local-reading-v1.md"))}
    for name, parent in (("prompt_file", path_config.prompts_dir), ("schema_file", path_config.schemas_dir),
                         ("reading_prompt_file", path_config.prompts_dir)):
        raw_path = _path_value(raw_direct[name], name=f"card_generator.pdf_direct_trial.{name}")
        resolved = (raw_path if raw_path.is_absolute() else project_root / raw_path).resolve()
        if not resolved.is_relative_to(parent):
            raise ConfigError(f"card_generator.pdf_direct_trial.{name} 必须位于配置的提示词或 schema 目录内")
        direct_paths[name] = resolved
    direct_trial_config = PdfDirectTrialConfig(
        **direct_paths,
        timeout_seconds=_validate_seconds("card_generator.pdf_direct_trial.timeout_seconds", raw_direct["timeout_seconds"]),
        windows_sandbox=_validate_card_generator_choice(
            "card_generator.pdf_direct_trial.windows_sandbox", raw_direct.get("windows_sandbox", "elevated"),
            supported={"elevated", "unelevated"}),
        shell_executable=_validate_non_empty_string(
            "card_generator.pdf_direct_trial.shell_executable", raw_direct.get("shell_executable", "powershell")),
        preflight_timeout_seconds=_validate_seconds(
            "card_generator.pdf_direct_trial.preflight_timeout_seconds", raw_direct.get("preflight_timeout_seconds", 120)),
        python_executable=(None if raw_direct.get("python_executable") is None else _validate_non_empty_string(
            "card_generator.pdf_direct_trial.python_executable", raw_direct["python_executable"])),
        text_extractor=_validate_card_generator_choice(
            "card_generator.pdf_direct_trial.text_extractor", raw_direct.get("text_extractor", "pdftotext"),
            supported={"pdftotext", "pypdf"}),
    )

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
        model=_validate_optional_non_empty_string(
            "card_generator.model",
            raw_card_generator["model"],
        ),
        reasoning_effort=_validate_optional_card_generator_choice(
            "card_generator.reasoning_effort",
            raw_card_generator["reasoning_effort"],
            supported=SUPPORTED_REASONING_EFFORTS,
        ),
        smoke_test_timeout_seconds=_validate_seconds(
            "card_generator.smoke_test_timeout_seconds",
            raw_card_generator["smoke_test_timeout_seconds"],
        ),
        generation_timeout_seconds=_validate_seconds(
            "card_generator.generation_timeout_seconds",
            raw_card_generator["generation_timeout_seconds"],
        ),
        pdf_reader=pdf_reader_config,
        workflow_mode=workflow_mode,
        multi_agent_workflow=multi_agent_workflow,
        progress=progress_config,
        connection_guard=connection_guard,
        pdf_direct_trial=direct_trial_config,
        runtime_dir=path_config.runtime_dir,
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
