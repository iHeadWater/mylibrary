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
class ProgressConfig:
    enabled: bool = True
    heartbeat_interval_seconds: float = 60


@dataclass(frozen=True)
class CardGeneratorConfig:
    """Which executor runs a card task, and how long it may take.

    ``runner`` is a registry id (``in_session`` or ``direct``). The API key is
    never part of the configuration: the ``direct`` runner reads it from the
    environment, and ``in_session`` needs none. ``model`` and
    ``reasoning_effort`` are the ordinary per-run model choice.
    """

    model: str | None
    reasoning_effort: str | None
    generation_timeout_seconds: float
    runner: str = "in_session"
    progress: ProgressConfig = ProgressConfig()
    runtime_dir: Path | None = None


@dataclass(frozen=True)
class PathConfig:
    project_root: Path
    # 产物根：单篇草稿、主题池、证据包都写在它下面。它来自项目级
    # configs/paths.toml（或 HYDROLITAGENT_LITERATURE_ROOT），cards 只声明子目录名。
    literature_root: Path
    runtime_dir: Path
    snapshot_file: Path
    tasks_file: Path
    lock_file: Path
    logs_dir: Path
    evidence_packs_dir: Path
    templates_dir: Path
    evidence_card_templates_dir: Path
    evidence_card_template_catalog_file: Path
    evidence_card_generation_prompt_file: Path
    themes_dir: Path


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


# 相对项目根解析：代码、模板、运行区。
PATH_FIELDS = (
    "runtime_dir",
    "snapshot_file",
    "tasks_file",
    "lock_file",
    "logs_dir",
    "templates_dir",
    "evidence_card_templates_dir",
    "evidence_card_template_catalog_file",
    "evidence_card_generation_prompt_file",
)

# 产物根下的子目录。它们相对 literature_root 解析，且不得离开产物根。
LITERATURE_PATH_FIELDS = (
    "evidence_packs_dir",
    "themes_dir",
)


__all__ = [
    "AppConfig",
    "CardGeneratorConfig",
    "ConfigError",
    "ConverterConfig",
    "DEFAULT_BASE_URL",
    "DEFAULT_PROCESS_TIMEOUT_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "LEGACY_SINGLE_AGENT_PROTOCOL_VERSION",
    "LOCAL_PATH_PROTOCOL_VERSION",
    "MULTI_AGENT_PROTOCOL_VERSION",
    "PATH_FIELDS",
    "PdfGateConfig",
    "PathConfig",
    "PipelineConfig",
    "ProgressConfig",
    "SINGLE_AGENT_PROTOCOL_VERSION",
    "SUPPORTED_REASONING_EFFORTS",
    "TaskConfig",
    "ThemePipelineConfig",
    "ZoteroConfig",
    "ZoteroStartupConfig",
]
