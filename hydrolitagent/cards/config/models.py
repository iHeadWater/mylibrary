"""Frozen configuration models, defaults and the configuration error type.

This module is pure data: dataclasses and constants only. Validation, path
containment and executable discovery live in sibling modules and import from
here. Protocol identifiers live in the provider-free domain layer and are
re-exported so existing imports keep working during the decoupling migration.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydrolitagent.cards.domain.protocol import (
    LEGACY_SINGLE_AGENT_PROTOCOL_VERSION,
    LOCAL_PATH_PROTOCOL_VERSION,
    MULTI_AGENT_PROTOCOL_VERSION,
    SINGLE_AGENT_PROTOCOL_VERSION,
    SUPPORTED_REASONING_EFFORTS,
)
from hydrolitagent.cards.domain.roles import REQUIRED_CARD_WORKFLOW_ROLES


DEFAULT_BASE_URL = "http://127.0.0.1:23119"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_PROCESS_TIMEOUT_SECONDS = 5.0


class ConfigError(ValueError):
    """Raised when the application configuration is invalid."""


@dataclass(frozen=True)
class ZoteroStartupConfig:
    enabled: bool = False
    launch_if_missing: bool = True
    executable: str | None = None
    wait_timeout_seconds: float = 120.0
    poll_interval_seconds: float = 5.0


@dataclass(frozen=True)
class ZoteroConfig:
    base_url: str = DEFAULT_BASE_URL
    group_id: int | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    process_timeout_seconds: float = DEFAULT_PROCESS_TIMEOUT_SECONDS
    startup: ZoteroStartupConfig = ZoteroStartupConfig()


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
    heartbeat_interval_seconds: float = 60


@dataclass(frozen=True)
class ConnectionGuardConfig:
    reconnect_event_limit: int = 2
    recovery_timeout_seconds: float = 60
    idle_timeout_seconds: float = 300
    pdf_tool_call_limit: int = 2
    reconnect_stop_enabled: bool = True


@dataclass(frozen=True)
class CodexProxyConfig:
    enabled: bool = False
    url: str | None = None
    no_proxy: tuple[str, ...] = ("localhost", "127.0.0.1", "::1")


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
    workflow_mode: str = "single_agent"  # 收敛后只剩单 Agent（multi_agent 已移除）
    multi_agent_workflow: CardQualityWorkflowConfig | None = None
    progress: ProgressConfig = ProgressConfig()
    connection_guard: ConnectionGuardConfig = ConnectionGuardConfig()
    runtime_dir: Path | None = None
    proxy: CodexProxyConfig = CodexProxyConfig()


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
    # 科研产物根：证据卡 / 主题 / 运行记录 / 文献链接的落点。
    # 默认在工作区根（仓库根），也可指向仓库外的共享位置（见 artifact_root_external）。
    artifact_root: Path
    artifact_root_external: bool
    evidence_cards_dir: Path
    themes_vault_dir: Path
    run_records_dir: Path
    literature_index_dir: Path


@dataclass(frozen=True)
class PipelineConfig:
    max_items_per_run: int | None = None
    max_run_seconds: int | None = None
    max_attempts_per_item: int = 3
    retry_cooldown_seconds: int = 3600


@dataclass(frozen=True)
class ThemePipelineConfig:
    enabled: bool = False
    research_goal: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: float | None = None
    assets_dir: Path | None = None


@dataclass(frozen=True)
class ConverterConfig:
    """PDF→Markdown converter selection and options.

    ``converter_id="none"`` keeps the legacy pipeline (the default). A concrete
    converter id is only meaningful once the Markdown-first pipeline is enabled;
    the cache directory is resolved by ``load_config`` and always sits under
    ``paths.project_root``.
    """

    converter_id: str = "none"
    mode: str = "layout"
    extract_figures: bool = True
    table_mode: str = "markdown"
    ocr: bool = False
    min_text_coverage: float = 0.60
    cache_dir: Path | None = None


# ``CARD_PIPELINE`` selects the conversion pipeline for a run. Stage 3b makes
# the Markdown-first pipeline the default: Python converts the PDF once and the
# runner reads ``paper.md``, so Poppler is no longer a prerequisite. ``legacy``
# stays available for one release as an explicit rollback.
PIPELINE_MODES = ("legacy", "markdown")
DEFAULT_PIPELINE_MODE = "markdown"


@dataclass(frozen=True)
class AppConfig:
    source_file: Path | None
    zotero: ZoteroConfig
    pdf_gate: PdfGateConfig
    tasks: TaskConfig
    card_generator: CardGeneratorConfig
    paths: PathConfig
    pipeline: PipelineConfig = PipelineConfig()
    theme_pipeline: ThemePipelineConfig = ThemePipelineConfig()
    converter: ConverterConfig = ConverterConfig()
    # Provider-neutral bag handed to the runner factory (``base_url`` and the
    # HTTP runner's token budgets). ``None`` means "the on-disk config chose no
    # AI selection"; the file loader leaves it unset so nothing changes for
    # existing configs.
    runner_options: dict[str, Any] | None = None


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

# 产物根下的子目录。它们相对 paths.artifact_root 解析，且不得离开产物根。
ARTIFACT_PATH_FIELDS = (
    "evidence_cards_dir",
    "themes_vault_dir",
    "run_records_dir",
    "literature_index_dir",
)


__all__ = [
    "ARTIFACT_PATH_FIELDS",
    "AppConfig",
    "CardGeneratorConfig",
    "CardQualityWorkflowConfig",
    "CardWorkflowRoleConfig",
    "CodexProxyConfig",
    "ConfigError",
    "ConnectionGuardConfig",
    "ConverterConfig",
    "DEFAULT_BASE_URL",
    "DEFAULT_PIPELINE_MODE",
    "DEFAULT_PROCESS_TIMEOUT_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "LEGACY_SINGLE_AGENT_PROTOCOL_VERSION",
    "LOCAL_PATH_PROTOCOL_VERSION",
    "MULTI_AGENT_PROTOCOL_VERSION",
    "PATH_FIELDS",
    "PdfGateConfig",
    "PathConfig",
    "PIPELINE_MODES",
    "PipelineConfig",
    "ProgressConfig",
    "REQUIRED_CARD_WORKFLOW_ROLES",
    "SINGLE_AGENT_PROTOCOL_VERSION",
    "SUPPORTED_REASONING_EFFORTS",
    "TaskConfig",
    "ThemePipelineConfig",
    "ZoteroConfig",
    "ZoteroStartupConfig",
]
