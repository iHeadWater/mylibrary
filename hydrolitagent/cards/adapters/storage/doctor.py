"""Capability probes for artifact and runtime storage.

Two things can break a card run before a model is ever reached: the artifact
root is not writable, or the runtime lock cannot be taken. Both are checked by
doing them for real in a throwaway path, not by inspecting permissions.

The probes never touch an existing draft, task registry or lock file: they use
a process-unique name and remove it afterwards.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from hydrolitagent.cards.ports.doctor import DoctorCheck
from hydrolitagent.cards.tasks import PipelineRunLock, TaskStoreError

_WRITE_FIX = "检查 --output-root、paths 配置与目录权限，确保当前用户可创建文件"
_LOCK_FIX = "检查 paths.runtime_dir 是否可写，并确认没有其它实例长期占用运行锁"


def _probe_name(prefix: str) -> str:
    return f"{prefix}-{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp"


def _write_check(root: Path) -> DoctorCheck:
    name = "storage.output_root"
    capability = "storage.write"
    probe = root / _probe_name(".doctor-write")
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe.write_text("doctor", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return DoctorCheck(
            name=name,
            capability=capability,
            status="fail",
            detail=f"产物根不可写：{root}（{type(exc).__name__}: {exc}）",
            fix=_WRITE_FIX,
        )
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    return DoctorCheck(
        name=name,
        capability=capability,
        status="pass",
        detail=f"可写入：{root}",
    )


def _lock_check(runtime_dir: Path) -> DoctorCheck:
    name = "storage.runtime_lock"
    capability = "storage.lock"
    probe = runtime_dir / _probe_name(".doctor-lock")
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        with PipelineRunLock(probe):
            pass
    except (OSError, TaskStoreError) as exc:
        return DoctorCheck(
            name=name,
            capability=capability,
            status="fail",
            detail=f"运行锁不可用：{runtime_dir}（{type(exc).__name__}: {exc}）",
            fix=_LOCK_FIX,
        )
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    return DoctorCheck(
        name=name,
        capability=capability,
        status="pass",
        detail=f"运行锁可取得并释放：{runtime_dir}",
    )


def storage_checks(*, output_root: Path, runtime_dir: Path) -> tuple[DoctorCheck, ...]:
    """Check the two storage capabilities a card run depends on."""

    return (_write_check(Path(output_root)), _lock_check(Path(runtime_dir)))


__all__ = ["storage_checks"]
