"""Reading the team config file and assembling the frozen ``AppConfig``.

``load_config`` keeps its exact signature, validation order and error messages
from the pre-split ``config.py``; only its imports changed.
"""
from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

from .executables import _resolve_executable
from .models import (
    ARTIFACT_PATH_FIELDS,
    LOCAL_PATH_PROTOCOL_VERSION,
    MULTI_AGENT_PROTOCOL_VERSION,
    PATH_FIELDS,
    REQUIRED_CARD_WORKFLOW_ROLES,
    SUPPORTED_REASONING_EFFORTS,
    AppConfig,
    CardGeneratorConfig,
    CardQualityWorkflowConfig,
    CardWorkflowRoleConfig,
    ConfigError,
    ConnectionGuardConfig,
    PathConfig,
    PdfDirectTrialConfig,
    PdfGateConfig,
    PdfReaderConfig,
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
    artifact_root, artifact_root_external = _resolve_artifact_root(raw_paths, project_root)
    path_config = PathConfig(
        project_root=project_root,
        **{
            name: _resolve_project_path(raw_paths, name, project_root)
            for name in PATH_FIELDS
        },
        artifact_root=artifact_root,
        artifact_root_external=artifact_root_external,
        **{
            name: _resolve_artifact_path(raw_paths, name, artifact_root)
            for name in ARTIFACT_PATH_FIELDS
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
    raw_startup = raw_zotero.get("startup", {})
    if not isinstance(raw_startup, dict) or set(raw_startup) - set(ZoteroStartupConfig.__dataclass_fields__):
        raise ConfigError("zotero.startup 包含未知字段或不是 JSON 对象")
    startup = ZoteroStartupConfig(**raw_startup)
    for name in ("enabled", "launch_if_missing"):
        if type(getattr(startup, name)) is not bool:
            raise ConfigError(f"zotero.startup.{name} 必须是布尔值")
    startup_values = {}
    for name, upper in (("wait_timeout_seconds", 600), ("poll_interval_seconds", 30)):
        value = getattr(startup, name)
        if isinstance(value, bool):
            raise ConfigError(f"zotero.startup.{name} 必须是有限正数")
        value = _validate_seconds("zotero.startup." + name, value)
        if not math.isfinite(value) or value > upper:
            raise ConfigError(f"zotero.startup.{name} 必须大于0且不超过{upper}")
        startup_values[name] = value
    if startup_values["poll_interval_seconds"] > startup_values["wait_timeout_seconds"]:
        raise ConfigError("Zotero轮询间隔不能大于等待预算")
    startup = replace(startup, **startup_values, executable=_resolve_executable(
        _validate_optional_non_empty_string("zotero.startup.executable", startup.executable), path_config.project_root))
    zotero_config = ZoteroConfig(
        startup=startup,
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
        "enabled": True, "heartbeat_interval_seconds": ProgressConfig().heartbeat_interval_seconds,
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

    workflow_mode = raw_card_generator.get("workflow_mode", "single_agent")
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
        proxy=_validate_codex_proxy(raw_card_generator.get("proxy", {})),
    )

    raw_pipeline = data.get("pipeline", {})
    pipeline_defaults = PipelineConfig()
    if not isinstance(raw_pipeline, dict) or set(raw_pipeline) - set(PipelineConfig.__dataclass_fields__):
        raise ConfigError("pipeline 包含未知字段或不是 JSON 对象")
    pipeline_values = {}
    for name in PipelineConfig.__dataclass_fields__:
        value = raw_pipeline.get(name, getattr(pipeline_defaults, name))
        if name in {"max_items_per_run", "max_run_seconds"} and value is None:
            pipeline_values[name] = None
            continue
        if type(value) is not int or value < 1:
            raise ConfigError(f"pipeline.{name} 必须是正整数；仅篇数和整轮时间上限允许 null")
        pipeline_values[name] = value

    raw_themes = data.get("theme_pipeline", {})
    if not isinstance(raw_themes, dict) or set(raw_themes) - set(ThemePipelineConfig.__dataclass_fields__):
        raise ConfigError("theme_pipeline 包含未知字段或不是 JSON 对象")
    theme_values = dict(raw_themes)
    if type(theme_values.get("enabled", False)) is not bool:
        raise ConfigError("theme_pipeline.enabled 必须是布尔值")
    for name in ("research_goal", "model", "reasoning_effort"):
        value = theme_values.get(name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ConfigError(f"theme_pipeline.{name} 必须是非空字符串或 null")
    if theme_values.get("reasoning_effort") not in SUPPORTED_REASONING_EFFORTS | {None}:
        raise ConfigError("theme_pipeline.reasoning_effort 不受支持")
    if theme_values.get("timeout_seconds") is not None:
        theme_values["timeout_seconds"] = _validate_seconds("theme_pipeline.timeout_seconds", theme_values["timeout_seconds"])
        if not math.isfinite(theme_values["timeout_seconds"]):
            raise ConfigError("theme_pipeline.timeout_seconds 必须是有限正数")
    asset_value = theme_values.get("assets_dir")
    if asset_value is not None and (not isinstance(asset_value, str) or not asset_value.strip()):
        raise ConfigError("theme_pipeline.assets_dir 必须是路径字符串或 null")
    if asset_value:
        # 此前该值直接 project_root / asset_value 后 resolve，给绝对路径即可静默
        # 逃出 project_root。它是唯一没走 containment 的路径值，这里补上。
        raw_asset = _path_value(asset_value, name="theme_pipeline.assets_dir")
        resolved_asset = (
            raw_asset if raw_asset.is_absolute() else path_config.project_root / raw_asset
        ).resolve()
        if not resolved_asset.is_relative_to(path_config.project_root):
            raise ConfigError("theme_pipeline.assets_dir 必须位于 paths.project_root 内")
        theme_values["assets_dir"] = resolved_asset
    else:
        theme_values["assets_dir"] = path_config.templates_dir / "themes"

    card_generator_config = replace(card_generator_config,
        executable=_resolve_executable(card_generator_config.executable, path_config.project_root),
        pdf_reader=replace(pdf_reader_config, **{name: _resolve_executable(getattr(pdf_reader_config, name), path_config.project_root)
            for name in ("python_executable", "pdfinfo_executable", "pdftotext_executable", "pdftoppm_executable")}),
        pdf_direct_trial=replace(direct_trial_config, **{name: _resolve_executable(getattr(direct_trial_config, name), path_config.project_root)
            for name in ("python_executable", "shell_executable")}))

    return AppConfig(
        source_file=config_file,
        zotero=zotero_config,
        pdf_gate=pdf_gate_config,
        tasks=task_config,
        card_generator=card_generator_config,
        paths=path_config,
        pipeline=PipelineConfig(**pipeline_values),
        theme_pipeline=ThemePipelineConfig(**theme_values),
    )


__all__ = ["_read_config_file", "load_config"]
