"""Path parsing and containment rules for ``paths.*`` configuration values.

A path value never escapes its declared root unless the configuration says so
explicitly (``paths.artifact_root_external``); these helpers enforce that and
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


def _resolve_artifact_root(
    paths: dict[str, Any], project_root: Path
) -> tuple[Path, bool]:
    """解析科研产物根，返回 (解析后路径, 是否位于项目外)。

    默认解析到工作区根（仓库根），即 ``project_root`` 的上一级，与王新宇分支
    原有的磁盘布局一致。落在 ``project_root`` 之外必须显式声明
    ``paths.artifact_root_external = true``——与 ``deployment.environment_dir``
    借用共享 ``.venv`` 同一思路：外部位置是允许的，但必须是写明的意图，
    而不是被相对路径（如 ``../outside``）悄悄带出去。
    """
    if "artifact_root" not in paths:
        raise ConfigError("缺少 paths.artifact_root")
    raw_root = _path_value(paths["artifact_root"], name="artifact_root")
    resolved = (raw_root if raw_root.is_absolute() else project_root / raw_root).resolve()
    declared = paths.get("artifact_root_external", False)
    if not isinstance(declared, bool):
        raise ConfigError("paths.artifact_root_external 必须是布尔值")
    external = not resolved.is_relative_to(project_root)
    if external and not declared:
        raise ConfigError(
            "paths.artifact_root 必须位于 paths.project_root 内；"
            "确需指向项目外（如共享盘）时必须显式设置 "
            "paths.artifact_root_external = true"
        )
    return resolved, external


def _resolve_artifact_path(paths: dict[str, Any], name: str, artifact_root: Path) -> Path:
    if name not in paths:
        raise ConfigError(f"缺少 paths.{name}")
    raw_path = _path_value(paths[name], name=name)
    resolved = (
        raw_path if raw_path.is_absolute() else artifact_root / raw_path
    ).resolve()
    if not resolved.is_relative_to(artifact_root):
        raise ConfigError(f"paths.{name} 必须位于 paths.artifact_root 内")
    return resolved


__all__ = [
    "_path_value",
    "_require_inside",
    "_resolve_artifact_path",
    "_resolve_artifact_root",
    "_resolve_project_path",
    "_resolve_project_root",
]
