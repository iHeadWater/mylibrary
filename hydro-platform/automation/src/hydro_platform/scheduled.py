"""Daily-slot gate around the existing pipeline. Polls do not imply model calls."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from hydro_platform.pipeline import run_once
from hydro_platform.publication import atomic_text
from hydro_platform.tasks import PipelineRunLock, TaskStoreError


def state_path(config):
    return config.paths.runtime_dir / "scheduler-state.json"


def _binding(config):
    return {"schema_version": 1, "group_id": config.zotero.group_id,
            "project_root": str(config.paths.project_root)}


def read_state(config):
    path = state_path(config)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or any(data.get(k) != v for k, v in _binding(config).items()):
        raise ValueError("调度记录不属于当前项目和共享库")
    date.fromisoformat(data["slot_date"])
    if (type(data.get("attempt_count")) is not int or data["attempt_count"] < 0 or
            data.get("status") not in {"RUNNING", "COMPLETED", "FAILED", "BUSY", "PENDING"}):
        raise ValueError("调度记录损坏")
    for field in ("last_attempt_at", "next_retry_at"):
        value = data.get(field)
        if value is not None and datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("调度时间缺少时区")
    return data


def due_status(config, state, now):
    if now.tzinfo is None:
        raise ValueError("调度需要有时区的本机时间")
    hour, minute = map(int, config.scheduler.daily_time.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    slot = (now.date() if now >= target else now.date() - timedelta(days=1)).isoformat()
    if not config.scheduler.enabled:
        return slot, "DISABLED"
    if state is None or state["slot_date"] < slot:
        return slot, "DUE"
    if state["slot_date"] > slot:
        return slot, "CLOCK_REVERSED"
    if state["status"] == "COMPLETED":
        return slot, "ALREADY_COMPLETED"
    if state["attempt_count"] >= config.scheduler.max_attempts_per_slot:
        return slot, "ATTEMPTS_EXHAUSTED"
    retry_at = state.get("next_retry_at")
    if retry_at and now < datetime.fromisoformat(retry_at):
        return slot, "RETRY_COOLDOWN"
    return slot, "DUE"


def scheduled_tick(config, *, now=None, pipeline=None):
    supplied_time = now is not None
    now = now or datetime.now().astimezone()
    result = {"schema_version": 1, "operation": "scheduled_tick", "ok": True,
              "pipeline_invoked": False, "model_call_count": 0, "checked_at": now.isoformat()}
    if not config.scheduler.enabled:
        return {**result, "status": "DISABLED"}
    try:
        with PipelineRunLock(config.paths.runtime_dir / "scheduler.lock"):
            previous = read_state(config)
            slot, status = due_status(config, previous, now)
            result.update(slot_date=slot, status=status)
            if status != "DUE":
                result["ok"] = status not in {"ATTEMPTS_EXHAUSTED", "CLOCK_REVERSED"}
                return result
            attempts = previous["attempt_count"] if previous and previous["slot_date"] == slot else 0
            state = {**_binding(config), "slot_date": slot, "attempt_count": attempts + 1,
                     "status": "RUNNING", "last_attempt_at": now.isoformat(),
                     "next_retry_at": (now + timedelta(minutes=config.scheduler.retry_interval_minutes)).isoformat()}
            # Reserve before expensive work: a crashed attempt is not silently forgotten.
            atomic_text(state_path(config), json.dumps(state, ensure_ascii=False, indent=2))
            result["pipeline_invoked"] = True
            try:
                outcome = (pipeline or run_once)(config)
            except Exception as exc:
                outcome = {"ok": False, "status": "FAILED", "error": {
                    "code": getattr(exc, "code", "SCHEDULE_PIPELINE_ERROR"),
                    "message": "本轮流水线异常；保留已保存成果，详情需检查本机运行状态"}}
            # Another manually started run does not consume a paid processing attempt.
            if outcome.get("status") == "ALREADY_RUNNING":
                state.update(status="BUSY", attempt_count=attempts)
            elif outcome.get("ok") and (outcome.get("status") == "COMPLETED_WITH_PENDING" or
                    (outcome.get("counts") or {}).get("waiting", 0) or
                    (outcome.get("counts") or {}).get("deferred", 0)):
                state["status"] = "PENDING"
            else:
                state["status"] = "COMPLETED" if outcome.get("ok") else "FAILED"
            state["pipeline_status"] = outcome.get("status", "UNKNOWN")
            state["report_path"] = outcome.get("report_path")
            state["pending_count"] = outcome.get("pending_count", sum(
                (outcome.get("counts") or {}).get(name, 0) for name in ("waiting", "deferred")))
            finished = now if supplied_time else datetime.now().astimezone()
            state["last_finished_at"] = finished.isoformat()
            state["next_retry_at"] = (finished + timedelta(minutes=config.scheduler.retry_interval_minutes)).isoformat()
            state["error_code"] = outcome.get("error", {}).get("code")
            if state["status"] == "COMPLETED":
                state["next_retry_at"] = None
            atomic_text(state_path(config), json.dumps(state, ensure_ascii=False, indent=2))
            result.update(status=state["status"], ok=bool(outcome.get("ok")),
                          pending_count=state["pending_count"],
                          attempt_count=state["attempt_count"], pipeline_report_path=state["report_path"],
                          generation_attempt_count=outcome.get("generation_attempt_count", 0),
                          theme_model_call_count=(outcome.get("theme_pipeline") or {}).get("model_call_count", 0))
            # A card attempt can fail before invoking a model; do not invent an exact paid-call count.
            result["model_call_count"] = result["theme_model_call_count"] if not result["generation_attempt_count"] else None
            result["note"] = "调度不自动推送 Git；已完成卡和主题步骤由原流水线复用"
            return result
    except TaskStoreError as exc:
        if exc.code == "TASK_STORE_BUSY":
            return {**result, "status": "ALREADY_RUNNING"}
        return {**result, "ok": False, "status": "FAILED", "error": {"code": exc.code, "message": str(exc)}}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {**result, "ok": False, "status": "FAILED", "error": {
            "code": "SCHEDULE_STATE_ERROR", "message": "调度状态无法读取或保存；不覆盖损坏记录、不自动重置尝试次数"}}
