"""Configuration facade for ``hydrolitagent.cards``.

The former single-module ``config.py`` is split by responsibility:

* ``models``      -- frozen dataclasses, defaults, ``ConfigError``;
* ``validators``  -- scalar / structured value validation;
* ``paths``       -- path parsing and containment rules;
* ``executables`` -- executable discovery policy;
* ``loading``     -- reading the JSON file and assembling ``AppConfig``.

Every name that used to be importable from ``hydrolitagent.cards.config`` stays
importable from here, including the private helpers. Protocol identifiers are
re-exported from the provider-free domain layer via ``models``.
"""
from __future__ import annotations

from .executables import _resolve_executable
from .loading import (
    CARD_PIPELINE_ENV,
    _load_converter,
    _read_config_file,
    load_config,
    resolve_pipeline_mode,
)
from .models import (
    ARTIFACT_PATH_FIELDS,
    DEFAULT_BASE_URL,
    DEFAULT_PIPELINE_MODE,
    DEFAULT_PROCESS_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    PIPELINE_MODES,
    LEGACY_SINGLE_AGENT_PROTOCOL_VERSION,
    LOCAL_PATH_PROTOCOL_VERSION,
    MULTI_AGENT_PROTOCOL_VERSION,
    PATH_FIELDS,
    REQUIRED_CARD_WORKFLOW_ROLES,
    SINGLE_AGENT_PROTOCOL_VERSION,
    SUPPORTED_REASONING_EFFORTS,
    AppConfig,
    CardGeneratorConfig,
    CardQualityWorkflowConfig,
    CardWorkflowRoleConfig,
    CodexProxyConfig,
    ConfigError,
    ConnectionGuardConfig,
    ConverterConfig,
    PathConfig,
    PdfGateConfig,
    PipelineConfig,
    ProgressConfig,
    TaskConfig,
    ThemePipelineConfig,
    ZoteroConfig,
    ZoteroStartupConfig,
)
from .paths import (
    _path_value,
    _require_inside,
    _resolve_artifact_path,
    _resolve_artifact_root,
    _resolve_project_path,
    _resolve_project_root,
)
from .validators import (
    _validate_base_url,
    _validate_card_generator_choice,
    _validate_codex_proxy,
    _validate_group_id,
    _validate_non_empty_string,
    _validate_non_negative_int,
    _validate_optional_card_generator_choice,
    _validate_optional_non_empty_string,
    _validate_positive_int,
    _validate_seconds,
    _validate_server_name,
)

__all__ = [
    # Models and defaults
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
    "PATH_FIELDS",
    "PIPELINE_MODES",
    "PathConfig",
    "PdfGateConfig",
    "PipelineConfig",
    "ProgressConfig",
    "TaskConfig",
    "ThemePipelineConfig",
    "ZoteroConfig",
    "ZoteroStartupConfig",
    # Protocol identifiers re-exported from the domain layer
    "LEGACY_SINGLE_AGENT_PROTOCOL_VERSION",
    "LOCAL_PATH_PROTOCOL_VERSION",
    "MULTI_AGENT_PROTOCOL_VERSION",
    "REQUIRED_CARD_WORKFLOW_ROLES",
    "SINGLE_AGENT_PROTOCOL_VERSION",
    "SUPPORTED_REASONING_EFFORTS",
    # Loading entry point
    "CARD_PIPELINE_ENV",
    "_load_converter",
    "load_config",
    "resolve_pipeline_mode",
]
