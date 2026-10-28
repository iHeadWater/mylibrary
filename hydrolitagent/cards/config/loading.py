"""Reading the team config file and assembling the frozen ``AppConfig``.

``load_config`` keeps its exact signature, validation order and error messages
from the pre-split ``config.py``; only its imports changed.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from .executables import _resolve_executable
from .models import (
    LITERATURE_PATH_FIELDS,
    PATH_FIELDS,
    SUPPORTED_REASONING_EFFORTS,
    AppConfig,
    CardGeneratorConfig,
    ConfigError,
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
    _resolve_literature_path,
    _resolve_literature_root,
    _resolve_project_path,
    _resolve_project_root,
)
from .validators import (
    _validate_base_url,
    _validate_group_id,
    _validate_non_empty_string,
    _validate_optional_card_generator_choice,
    _validate_optional_non_empty_string,
    _validate_positive_int,
    _validate_seconds,
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


_CONVERTER_MODES = frozenset({"layout", "text"})
_CONVERTER_TABLE_MODES = frozenset({"markdown", "text"})


def _load_converter(raw: Any, path_config: PathConfig) -> ConverterConfig:
    if not isinstance(raw, dict) or set(raw) - set(ConverterConfig.__dataclass_fields__):
        raise ConfigError("converter 包含未知字段或不是 JSON 对象")

    converter_id = raw.get("converter_id", "none")
    if not isinstance(converter_id, str) or not converter_id.strip():
        raise ConfigError("converter.converter_id 必须是非空字符串")
    mode = raw.get("mode", "layout")
    if mode not in _CONVERTER_MODES:
        raise ConfigError("converter.mode 仅支持 layout 或 text")
    table_mode = raw.get("table_mode", "markdown")
    if table_mode not in _CONVERTER_TABLE_MODES:
        raise ConfigError("converter.table_mode 仅支持 markdown 或 text")

    extract_figures = raw.get("extract_figures", True)
    if type(extract_figures) is not bool:
        raise ConfigError("converter.extract_figures 必须是布尔值")
    ocr = raw.get("ocr", False)
    if type(ocr) is not bool:
        raise ConfigError("converter.ocr 必须是布尔值")

    coverage = raw.get("min_text_coverage", 0.60)
    if isinstance(coverage, bool) or not isinstance(coverage, (int, float)):
        raise ConfigError("converter.min_text_coverage 必须是 0 到 1 之间的数值")
    if not math.isfinite(float(coverage)) or not 0.0 <= float(coverage) <= 1.0:
        raise ConfigError("converter.min_text_coverage 必须是 0 到 1 之间的数值")

    cache_value = raw.get("cache_dir")
    if cache_value is None:
        cache_dir = path_config.runtime_dir
    else:
        raw_cache = _path_value(cache_value, name="converter.cache_dir")
        resolved = (
            raw_cache if raw_cache.is_absolute() else path_config.project_root / raw_cache
        ).resolve()
        if not resolved.is_relative_to(path_config.project_root):
            raise ConfigError("converter.cache_dir 必须位于 paths.project_root 内")
        cache_dir = resolved

    return ConverterConfig(
        converter_id=converter_id.strip(),
        mode=mode,
        extract_figures=extract_figures,
        table_mode=table_mode,
        ocr=ocr,
        min_text_coverage=float(coverage),
        cache_dir=cache_dir,
    )


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
    literature_root = _resolve_literature_root(raw_paths, project_root)
    path_config = PathConfig(
        project_root=project_root,
        literature_root=literature_root,
        **{
            name: _resolve_project_path(raw_paths, name, project_root)
            for name in PATH_FIELDS
        },
        **{
            name: _resolve_literature_path(raw_paths, name, literature_root)
            for name in LITERATURE_PATH_FIELDS
        },
    )
    for name in (
        "snapshot_file",
        "tasks_file",
        "lock_file",
        "logs_dir",
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
    card_generator_fields = ("model", "reasoning_effort", "generation_timeout_seconds")
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
    card_generator_config = CardGeneratorConfig(
        # ``runner`` is a registry id; the default executor is the in-session
        # protocol, which needs no credential. ``--ai-provider`` overrides it.
        runner=_validate_non_empty_string(
            "card_generator.runner",
            raw_card_generator.get("runner", "in_session"),
        ).casefold(),
        model=_validate_optional_non_empty_string(
            "card_generator.model",
            raw_card_generator["model"],
        ),
        reasoning_effort=_validate_optional_card_generator_choice(
            "card_generator.reasoning_effort",
            raw_card_generator["reasoning_effort"],
            supported=SUPPORTED_REASONING_EFFORTS,
        ),
        generation_timeout_seconds=_validate_seconds(
            "card_generator.generation_timeout_seconds",
            raw_card_generator["generation_timeout_seconds"],
        ),
        progress=progress_config,
        runtime_dir=path_config.runtime_dir,
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

    converter_config = _load_converter(data.get("converter", {}), path_config)

    return AppConfig(
        source_file=config_file,
        zotero=zotero_config,
        pdf_gate=pdf_gate_config,
        tasks=task_config,
        card_generator=card_generator_config,
        paths=path_config,
        pipeline=PipelineConfig(**pipeline_values),
        theme_pipeline=ThemePipelineConfig(**theme_values),
        converter=converter_config,
    )


__all__ = [
    "_load_converter",
    "_read_config_file",
    "load_config",
]
