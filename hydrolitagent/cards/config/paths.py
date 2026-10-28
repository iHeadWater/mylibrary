"""Path parsing and containment rules for ``paths.*`` configuration values.

A path value never escapes its declared root; these helpers enforce that and
raise ``ConfigError`` otherwise.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .models import ConfigError


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
    paths: dict[str, Any], name: str, project_root: Path, *, allow_workspace: bool = False
) -> Path:
    if name not in paths:
        raise ConfigError(f"缺少 paths.{name}")
    raw_path = _path_value(paths[name], name=name)
    resolved = (raw_path if raw_path.is_absolute() else project_root / raw_path).resolve()
    if resolved.is_relative_to(project_root):
        return resolved
    # 仅 deployment.environment_dir 允许借用平台所嵌入的 workspace 根的环境
    # （uv 托管的共享 .venv）。只接受该根下约定位置的 .venv，避免配置把
    # 环境指向任意外逃路径（如 ../outside 或 ../../../outside）。
    if allow_workspace and resolved == project_root.parent / ".venv":
        return resolved
    raise ConfigError(f"paths.{name} 必须位于 paths.project_root 内")


def _require_inside(path: Path, parent: Path, *, name: str, parent_name: str) -> None:
    if not path.is_relative_to(parent):
        raise ConfigError(f"paths.{name} 必须位于 paths.{parent_name} 内")


def _resolve_literature_root(paths: dict[str, Any], project_root: Path) -> Path:
    """Resolve the product root that ``themes_dir`` / ``evidence_packs_dir`` live under.

    One source of truth for the whole project: the project-level
    ``configs/paths.toml`` (or ``HYDROLITAGENT_LITERATURE_ROOT``). The cards
    config only names subdirectories inside it. ``paths.literature_root`` stays
    available as an explicit override for tests and unusual deployments.
    """
    explicit = paths.get("literature_root")
    if explicit is not None:
        raw_root = _path_value(explicit, name="literature_root")
        resolved = (raw_root if raw_root.is_absolute() else project_root / raw_root).resolve()
        if not resolved.is_relative_to(project_root):
            raise ConfigError("paths.literature_root 必须位于 paths.project_root 内")
        return resolved

    from hydrolitagent._config import resolve_literature_root

    return resolve_literature_root(
        config_path=project_root / "configs" / "paths.toml",
        warn=False,
        default=project_root / "outputs",
    )


def _resolve_literature_path(
    paths: dict[str, Any], name: str, literature_root: Path
) -> Path:
    if name not in paths:
        raise ConfigError(f"缺少 paths.{name}")
    raw_path = _path_value(paths[name], name=name)
    resolved = (raw_path if raw_path.is_absolute() else literature_root / raw_path).resolve()
    if not resolved.is_relative_to(literature_root):
        raise ConfigError(f"paths.{name} 必须位于 paths.literature_root 内")
    return resolved


__all__ = [
    "_path_value",
    "_require_inside",
    "_resolve_literature_path",
    "_resolve_literature_root",
    "_resolve_project_path",
    "_resolve_project_root",
]
