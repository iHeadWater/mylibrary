from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from contextlib import AbstractContextManager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from hydro_platform.config import PdfGateConfig, TaskConfig, ZoteroConfig
from hydro_platform.pdf_gate import evaluate_pdf_gate
from hydro_platform.snapshot import fetch_snapshot
from hydro_platform.zotero import ZoteroClient


READY_STATE = "READY_FOR_EXTRACTION"
CLAIMABLE_STATES = {READY_STATE, "RETRY_PENDING"}


class TaskStoreError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class RuntimeLock(AbstractContextManager["RuntimeLock"]):
    def __init__(self, path: str | Path, *, stale_seconds: int):
        self.path = Path(path)
        self.stale_seconds = stale_seconds
        self.token = secrets.token_hex(16)
        self.acquired = False

    def _payload(self) -> bytes:
        return (
            json.dumps(
                {
                    "schema_version": 1,
                    "pid": os.getpid(),
                    "token": self.token,
                    "acquired_at": _timestamp(),
                },
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")

    def _remove_if_stale(self) -> bool:
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return True
        if age <= self.stale_seconds:
            return False
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            pid = int(payload.get("pid"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            pid = -1
        if _pid_running(pid):
            return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise TaskStoreError("TASK_LOCK_ERROR", f"无法清理过期任务锁：{self.path}") from exc
        return True

    def __enter__(self) -> "RuntimeLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                descriptor = os.open(
                    self.path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError as exc:
                if self._remove_if_stale():
                    continue
                raise TaskStoreError(
                    "TASK_STORE_BUSY",
                    "另一个任务进程正在更新任务清单，请稍后重试",
                ) from exc
            try:
                os.write(descriptor, self._payload())
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self.acquired = True
            return self
        raise TaskStoreError("TASK_LOCK_ERROR", "无法取得任务清单锁")

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if not self.acquired:
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("token") == self.token:
                self.path.unlink(missing_ok=True)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        self.acquired = False
        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _timestamp(value: datetime | None = None) -> str:
    moment = value or _utc_now()
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _new_registry(group_id: int, at: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "group_id": group_id,
        "created_at": at,
        "updated_at": at,
        "tasks": {},
    }


def load_task_registry(path: str | Path, group_id: int, *, now: datetime | None = None) -> dict[str, Any]:
    task_path = Path(path)
    at = _timestamp(now)
    if not task_path.exists():
        return _new_registry(group_id, at)
    try:
        data = json.loads(task_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskStoreError("TASK_STORE_INVALID", f"无法读取任务清单：{task_path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise TaskStoreError("TASK_STORE_INVALID", "任务清单结构或版本无效")
    if data.get("group_id") != group_id:
        raise TaskStoreError("TASK_GROUP_MISMATCH", "任务清单属于另一个 Zotero 群组")
    tasks = data.get("tasks")
    if not isinstance(tasks, dict) or any(not isinstance(task, dict) for task in tasks.values()):
        raise TaskStoreError("TASK_STORE_INVALID", "任务清单中的 tasks 结构无效")
    return data


def save_task_registry(path: str | Path, registry: dict[str, Any]) -> None:
    task_path = Path(path)
    task_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = task_path.with_suffix(task_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, task_path)


def _task_id(group_id: int, parent_key: str, attachment_key: str, pdf_sha256: str) -> str:
    canonical = f"{group_id}\0{parent_key}\0{attachment_key}\0{pdf_sha256}".encode("utf-8")
    return "TASK-" + hashlib.sha256(canonical).hexdigest()


def _gate_state(gate_result: dict[str, Any]) -> str:
    status = gate_result.get("gate_status")
    reason = gate_result.get("reason_code")
    if status == "READY":
        return READY_STATE
    if status == "BLOCKED":
        return "BLOCKED"
    return {
        "PDF_MISSING": "WAITING_FOR_PDF",
        "PDF_FILE_NOT_SYNCED": "WAITING_FOR_FILE_SYNC",
        "FULLTEXT_NOT_INDEXED": "WAITING_FOR_FULLTEXT",
    }.get(reason, "WAITING")


def _gate_input(group_id: int, parent_key: str, gate_result: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    pdf = gate_result.get("pdf")
    if not isinstance(pdf, dict):
        return {"attachment_key": None, "pdf_sha256": None}, None
    attachment_key = pdf.get("attachment_key")
    pdf_sha256 = pdf.get("sha256")
    input_data = {
        "attachment_key": attachment_key if isinstance(attachment_key, str) else None,
        "pdf_sha256": pdf_sha256 if isinstance(pdf_sha256, str) else None,
    }
    if input_data["attachment_key"] and input_data["pdf_sha256"]:
        return input_data, _task_id(
            group_id,
            parent_key,
            input_data["attachment_key"],
            input_data["pdf_sha256"],
        )
    return input_data, None


def _append_history(
    task: dict[str, Any],
    *,
    previous_state: str | None,
    state: str,
    reason_code: str,
    at: str,
    max_entries: int,
) -> None:
    history = task.setdefault("history", [])
    if not isinstance(history, list):
        raise TaskStoreError("TASK_STORE_INVALID", "任务历史结构无效")
    history.append(
        {
            "at": at,
            "from": previous_state,
            "to": state,
            "reason_code": reason_code,
            "task_id": task.get("task_id"),
        }
    )
    if len(history) > max_entries:
        del history[:-max_entries]


def _set_state(
    task: dict[str, Any],
    *,
    state: str,
    reason_code: str,
    message: str,
    at: str,
    max_history_entries: int,
) -> bool:
    previous_state = task.get("state")
    if (
        previous_state == state
        and task.get("reason_code") == reason_code
        and task.get("message") == message
    ):
        return False
    task["state"] = state
    task["reason_code"] = reason_code
    task["message"] = message
    task["updated_at"] = at
    _append_history(
        task,
        previous_state=previous_state if isinstance(previous_state, str) else None,
        state=state,
        reason_code=reason_code,
        at=at,
        max_entries=max_history_entries,
    )
    return True


def _lease_expired(task: dict[str, Any], now: datetime) -> bool:
    lease = task.get("lease")
    if not isinstance(lease, dict):
        return True
    expires_at = _parse_timestamp(lease.get("expires_at"))
    return expires_at is None or expires_at <= now


def reconcile_tasks(
    registry: dict[str, Any],
    snapshot: dict[str, Any],
    gate_results: dict[str, dict[str, Any]],
    task_config: TaskConfig,
    *,
    now: datetime | None = None,
) -> int:
    moment = now or _utc_now()
    at = _timestamp(moment)
    group_id = registry["group_id"]
    if snapshot.get("group_id") != group_id:
        raise TaskStoreError("TASK_GROUP_MISMATCH", "Zotero 快照与任务清单群组不一致")
    parents = snapshot.get("parents")
    if not isinstance(parents, dict):
        raise TaskStoreError("SNAPSHOT_INVALID", "Zotero 快照缺少父条目映射")
    tasks = registry["tasks"]
    changed_parent_keys: set[str] = set()

    for parent_key, parent in parents.items():
        gate_result = gate_results.get(parent_key)
        if not isinstance(parent, dict) or not isinstance(gate_result, dict):
            raise TaskStoreError("TASK_INPUT_INVALID", f"父条目 {parent_key} 缺少有效门禁结果")
        target_state = _gate_state(gate_result)
        input_data, incoming_task_id = _gate_input(group_id, parent_key, gate_result)
        task = tasks.get(parent_key)
        created = task is None

        if created:
            task = {
                "record_id": f"{group_id}:{parent_key}",
                "group_id": group_id,
                "parent_key": parent_key,
                "title": parent.get("title"),
                "task_id": incoming_task_id,
                "input": input_data,
                "state": None,
                "reason_code": None,
                "message": None,
                "attempt_count": 0,
                "lease": None,
                "created_at": at,
                "updated_at": at,
                "history": [],
            }
            tasks[parent_key] = task
            new_input = True
            changed_parent_keys.add(parent_key)
        else:
            new_input = task.get("input") != input_data or task.get("task_id") != incoming_task_id
            if task.get("title") != parent.get("title"):
                task["title"] = parent.get("title")
                task["updated_at"] = at
                changed_parent_keys.add(parent_key)

        if new_input:
            task["input"] = input_data
            task["task_id"] = incoming_task_id
            task["attempt_count"] = 0
            task["lease"] = None
            changed_parent_keys.add(parent_key)

        current_state = task.get("state")
        if not new_input and current_state == "PROCESSING" and _lease_expired(task, moment):
            target_state = "RETRY_PENDING"
            reason_code = "LEASE_EXPIRED"
            message = "上一次处理租约已过期，可以安全重试"
            task["lease"] = None
        elif not new_input and current_state in {"PROCESSING", "RETRY_PENDING", "COMPLETED"} and target_state == READY_STATE:
            target_state = current_state
            reason_code = str(task.get("reason_code") or gate_result.get("reason_code") or "STATE_PRESERVED")
            message = str(task.get("message") or gate_result.get("message") or "保持现有处理状态")
        else:
            reason_code = str(gate_result.get("reason_code") or "UNKNOWN")
            message = str(gate_result.get("message") or "未提供状态说明")

        state_changed = _set_state(
            task,
            state=target_state,
            reason_code=reason_code,
            message=message,
            at=at,
            max_history_entries=task_config.max_history_entries,
        )
        if state_changed:
            changed_parent_keys.add(parent_key)
        elif new_input and not created:
            task["updated_at"] = at
            _append_history(
                task,
                previous_state=target_state,
                state=target_state,
                reason_code="INPUT_CHANGED",
                at=at,
                max_entries=task_config.max_history_entries,
            )

    for parent_key, task in tasks.items():
        if parent_key in parents or task.get("state") == "REMOVED":
            continue
        task["lease"] = None
        if _set_state(
            task,
            state="REMOVED",
            reason_code="ITEM_REMOVED",
            message="父条目已不在当前 Zotero 群组中",
            at=at,
            max_history_entries=task_config.max_history_entries,
        ):
            changed_parent_keys.add(parent_key)

    if changed_parent_keys:
        registry["updated_at"] = at
    return len(changed_parent_keys)


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    public = deepcopy(task)
    lease = public.get("lease")
    if isinstance(lease, dict):
        lease.pop("token", None)
    return public


def _summary(registry: dict[str, Any], path: str | Path, *, changed_count: int = 0) -> dict[str, Any]:
    tasks = [_public_task(task) for _, task in sorted(registry["tasks"].items())]
    counts: dict[str, int] = {}
    for task in tasks:
        state = str(task.get("state") or "UNKNOWN")
        counts[state] = counts.get(state, 0) + 1
    return {
        "schema_version": 1,
        "ok": True,
        "group_id": registry["group_id"],
        "task_count": len(tasks),
        "changed_count": changed_count,
        "state_counts": dict(sorted(counts.items())),
        "tasks": tasks,
        "state_path": str(Path(path).resolve()),
    }


def sync_tasks(
    zotero: ZoteroConfig,
    pdf_gate: PdfGateConfig,
    task_config: TaskConfig,
    task_path: str | Path,
    lock_path: str | Path,
    *,
    page_size: int,
    client: ZoteroClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if zotero.group_id is None:
        raise TaskStoreError("CONFIG_ERROR", "任务同步需要目标 Zotero 群组 ID")
    with RuntimeLock(lock_path, stale_seconds=task_config.lock_stale_seconds):
        registry = load_task_registry(task_path, zotero.group_id, now=now)
        snapshot = fetch_snapshot(zotero, page_size=page_size, client=client)
        gates = {
            parent_key: evaluate_pdf_gate(
                zotero,
                pdf_gate,
                parent_key,
                client=client,
            )
            for parent_key in snapshot["parents"]
        }
        changed_count = reconcile_tasks(
            registry,
            snapshot,
            gates,
            task_config,
            now=now,
        )
        if changed_count or not Path(task_path).exists():
            save_task_registry(task_path, registry)
        return _summary(registry, task_path, changed_count=changed_count)


def list_tasks(
    group_id: int,
    task_path: str | Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    registry = load_task_registry(task_path, group_id, now=now)
    return _summary(registry, task_path)


def _with_registry_lock(
    group_id: int,
    task_config: TaskConfig,
    task_path: str | Path,
    lock_path: str | Path,
    action: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    with RuntimeLock(lock_path, stale_seconds=task_config.lock_stale_seconds):
        registry = load_task_registry(task_path, group_id)
        result = action(registry)
        save_task_registry(task_path, registry)
        return result


def claim_task(
    group_id: int,
    parent_key: str,
    task_config: TaskConfig,
    task_path: str | Path,
    lock_path: str | Path,
    *,
    now: datetime | None = None,
    token_factory: Callable[[], str] | None = None,
) -> dict[str, Any]:
    moment = now or _utc_now()
    at = _timestamp(moment)

    def action(registry: dict[str, Any]) -> dict[str, Any]:
        task = registry["tasks"].get(parent_key)
        if not isinstance(task, dict):
            raise TaskStoreError("TASK_NOT_FOUND", f"找不到父条目任务：{parent_key}")
        if task.get("state") == "PROCESSING" and _lease_expired(task, moment):
            task["lease"] = None
            _set_state(
                task,
                state="RETRY_PENDING",
                reason_code="LEASE_EXPIRED",
                message="上一次处理租约已过期，可以安全重试",
                at=at,
                max_history_entries=task_config.max_history_entries,
            )
        if task.get("state") not in CLAIMABLE_STATES:
            raise TaskStoreError(
                "TASK_NOT_CLAIMABLE",
                f"任务当前状态不可领取：{task.get('state')}",
            )
        token = (token_factory or (lambda: secrets.token_urlsafe(24)))()
        task["attempt_count"] = int(task.get("attempt_count") or 0) + 1
        task["lease"] = {
            "token": token,
            "claimed_at": at,
            "expires_at": _timestamp(moment + timedelta(seconds=task_config.lease_seconds)),
        }
        _set_state(
            task,
            state="PROCESSING",
            reason_code="TASK_CLAIMED",
            message="任务已被一个处理进程领取",
            at=at,
            max_history_entries=task_config.max_history_entries,
        )
        registry["updated_at"] = at
        return {"task": _public_task(task), "lease_token": token}

    return _with_registry_lock(group_id, task_config, task_path, lock_path, action)


def finish_task(
    group_id: int,
    parent_key: str,
    lease_token: str,
    task_config: TaskConfig,
    task_path: str | Path,
    lock_path: str | Path,
    *,
    completed: bool,
    reason_code: str,
    message: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = now or _utc_now()
    at = _timestamp(moment)

    def action(registry: dict[str, Any]) -> dict[str, Any]:
        task = registry["tasks"].get(parent_key)
        if not isinstance(task, dict):
            raise TaskStoreError("TASK_NOT_FOUND", f"找不到父条目任务：{parent_key}")
        lease = task.get("lease")
        if task.get("state") != "PROCESSING" or not isinstance(lease, dict):
            raise TaskStoreError("TASK_NOT_PROCESSING", "任务当前不处于处理中")
        if not secrets.compare_digest(str(lease.get("token") or ""), lease_token):
            raise TaskStoreError("LEASE_TOKEN_MISMATCH", "任务租约不匹配，拒绝更新状态")
        task["lease"] = None
        state = "COMPLETED" if completed else "RETRY_PENDING"
        _set_state(
            task,
            state=state,
            reason_code=reason_code,
            message=message,
            at=at,
            max_history_entries=task_config.max_history_entries,
        )
        registry["updated_at"] = at
        return {"task": _public_task(task)}

    return _with_registry_lock(group_id, task_config, task_path, lock_path, action)
