"""Drain one scanned queue serially; optional operator caps and finite per-item attempts."""
from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from hydro_platform.card_generators import build_card_generator_adapter
from hydro_platform.card_generation import CardGenerationError, generate_evidence_card
from hydro_platform.draft_recovery import recover_failed_draft
from hydro_platform.config import AppConfig
from hydro_platform.evidence_packages import (
    EvidencePackageError, find_evidence_package, load_evidence_manifest,
    sync_evidence_packages, validate_evidence_task,
)
from hydro_platform.evidence_templates import EvidenceTemplateError, validate_evidence_templates
from hydro_platform.pdf_delivery import PdfDeliveryError
from hydro_platform.pdf_gate import PdfGateError
from hydro_platform.progress import report_progress
from hydro_platform.publication import atomic_text, identity, recover_publication, validate_saved_package
from hydro_platform.tasks import (
    PipelineRunLock, RuntimeLock, TaskStoreError, _lease_expired, _parse_timestamp,
    complete_task_from_package, load_task_registry, sync_tasks,
)
from hydro_platform.zotero import ZoteroApiError, preflight
from hydro_platform.zotero_readiness import ensure_zotero_ready
from hydro_platform.themes import run_themes
from hydro_platform.activity import sync_activity
from hydro_platform.daily_report import daily_report


KNOWN_ERRORS = (CardGenerationError, EvidencePackageError, TaskStoreError, PdfGateError,
                PdfDeliveryError, EvidenceTemplateError, ZoteroApiError)
GLOBAL_GENERATOR_ERRORS = {"CODEX_RATE_LIMITED", "CODEX_SERVICE_UNAVAILABLE", "CODEX_CLI_NOT_FOUND",
                           "CODEX_AUTH_MODE_MISMATCH", "CODEX_NOT_LOGGED_IN",
                           "CODEX_USAGE_LIMIT", "CODEX_MODEL_UNAVAILABLE", "CODEX_REASONING_EFFORT_UNAVAILABLE"}
RETRYABLE_REASONS = {"LEASE_EXPIRED", "CODEX_RATE_LIMITED", "CODEX_SERVICE_UNAVAILABLE",
                    "CODEX_GENERATION_TIMEOUT", "CODEX_RECONNECT_TIMEOUT", "CODEX_NO_PROGRESS_TIMEOUT"}


def _error(exc):
    if isinstance(exc, KNOWN_ERRORS):
        result = {"code": exc.code, "message": str(exc)}
        diagnostic = getattr(exc, "diagnostic", None)
        if isinstance(diagnostic, dict) and diagnostic.get("draft_path"):
            result["draft_path"] = diagnostic["draft_path"]
        return result
    return {"code": "PIPELINE_LOCAL_ERROR", "message": "本地记录或文件访问失败；保留现有结果"}


def _now():
    return datetime.now(timezone.utc)


def _package_status(config, task):
    """Return (complete manifest, restored files), or (None, False) for no complete card."""
    paths = config.paths
    normalized = validate_evidence_task(task, config.zotero.group_id)
    package = find_evidence_package(paths.evidence_packs_dir, task["parent_key"])
    if package is None:
        if task["state"] == "COMPLETED":
            raise EvidencePackageError("EVIDENCE_PACKAGE_MISSING", "已完成任务的证据包缺失，不自动重复制卡")
        return None, False
    expected = {"group_id": normalized["group_id"], "parent_key": normalized["parent_key"],
                "attachment_key": normalized["attachment_key"], "pdf_sha256": normalized["pdf_sha256"],
                "source_task_id": normalized["task_id"], "evidence_id": f"EV-{normalized['parent_key']}"}
    with RuntimeLock(paths.lock_file, stale_seconds=config.tasks.lock_stale_seconds):
        manifest = load_evidence_manifest(package / "manifest.json")
        if identity(manifest) != expected:
            raise EvidencePackageError("EVIDENCE_INPUT_MISMATCH", "现有证据包与当前输入不同，不覆盖旧卡")
        recovered = recover_publication(package, paths.lock_file, manifest)
        completed = validate_saved_package(package)
        if completed is None and task["state"] == "COMPLETED":
            raise EvidencePackageError("EVIDENCE_PACKAGE_INCONSISTENT", "任务已完成但仍是占位卡，不自动重跑")
        return completed, recovered


def run_once(config: AppConfig, *, progress=None, dry_run=False, clock=time.monotonic, now=None):
    started = clock()
    moment = now or _now()
    def remaining_seconds():
        cap = config.pipeline.max_run_seconds
        return float("inf") if cap is None else cap - (clock() - started)
    if dry_run:
        registry = load_task_registry(config.paths.tasks_file, config.zotero.group_id)
        return {"schema_version": 1, "ok": True, "operation": "run_once", "status": "LOCAL_PREVIEW",
                "dry_run": True, "model_invoked": False, "files_modified": False,
                "note": "仅查看已有本地任务及本轮配置；未扫描 Zotero，不代表最新文献已经发现或运行环境已经通过。",
                "theme_pipeline_enabled": config.theme_pipeline.enabled,
                "limits": vars(config.pipeline), "tasks": [
                    {k: task.get(k) for k in ("parent_key", "title", "state", "attempt_count")}
                    for _, task in sorted(registry["tasks"].items())]}
    report = {"schema_version": 1, "ok": True, "operation": "run_once", "status": "COMPLETED",
              "run_id": uuid4().hex, "started_at": moment.isoformat(), "group_id": config.zotero.group_id,
              "limits": vars(config.pipeline), "generation_attempt_count": 0,
              "new_discovered_count": 0, "items": [], "git_modified": False}
    lock_path = config.paths.lock_file.with_name(config.paths.lock_file.name + ".pipeline")
    phase = "acquire_run_lock"
    observed_snapshot = None
    monitoring = {"errors": []}
    def observe(snapshot):
        nonlocal observed_snapshot
        observed_snapshot = snapshot
        try:
            result = sync_activity(config, snapshot=snapshot, now=now)
            monitoring["before_generation"] = result
            if not result["ok"]:
                monitoring["errors"].append({"stage": "activity_before", "code": "ACTIVITY_PACKAGE_ISSUES"})
        except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
            monitoring["errors"].append({"stage": "activity_before", "code": getattr(exc, "code", "ACTIVITY_FAILED")})
    try:
        if config.card_generator.workflow_mode != "single_agent":
            raise CardGenerationError("PIPELINE_MODE_UNSUPPORTED", "统一入口当前只支持 single_agent 模式")
        with PipelineRunLock(lock_path):
            before = load_task_registry(config.paths.tasks_file, config.zotero.group_id)
            phase = "zotero_preflight"
            report_progress(progress, "phase", message="统一运行：检查 Zotero 和共享库")
            readiness = ensure_zotero_ready(config.zotero, progress=progress, probe=preflight,
                                           wait_budget=remaining_seconds() if config.zotero.startup.enabled else None)
            report["zotero_readiness"] = readiness
            if not readiness["ok"]:
                report.update(ok=False, status="FAILED", error=readiness.get("error") or {
                    "code": "ZOTERO_NOT_READY", "message": "Zotero 或指定群组未就绪"})
            else:
                phase = "tasks_sync"
                report_progress(progress, "phase", message="扫描共享库并更新待处理任务；包含后补 PDF，不单独重复执行 scan")
                options = {"snapshot_consumer": observe} if config.activity_reporting.enabled else {}
                synced = sync_tasks(config.zotero, config.pdf_gate, config.tasks, config.paths.tasks_file,
                                    config.paths.lock_file, page_size=config.scan.page_size, now=now, **options)
                report["new_discovered_count"] = len({t["parent_key"] for t in synced["tasks"]} - set(before["tasks"]))
                tasks = sorted(synced["tasks"], key=lambda t: (str(t.get("created_at", "")), str(t.get("parent_key", ""))))
                report["scanned_task_count"] = len(tasks)
                report_progress(progress, "phase", message=f"本轮发现 {len(tasks)} 条任务；自动逐篇处理并正式保存，无需逐批操作")
                generator_ready = False
                stop_reason = None
                for queue_index, task in enumerate(tasks, 1):
                    key, state = task.get("parent_key"), task.get("state")
                    item = {"parent_key": key, "title": task.get("title"), "initial_state": state}
                    phase = "package_reconciliation"
                    try:
                        if not isinstance(key, str) or not isinstance(state, str):
                            item.update(status="BLOCKED", reason_code="TASK_RECORD_INVALID")
                        elif state == "REMOVED":
                            item.update(status="SKIPPED", reason_code="REMOVED")
                        elif state == "PROCESSING" and not _lease_expired(task, now or _now()):
                            item.update(status="WAITING", reason_code="ACTIVE_LEASE")
                        elif state.startswith("WAITING"):
                            item.update(status="WAITING", reason_code=task.get("reason_code"))
                        elif state == "BLOCKED":
                            item.update(status="BLOCKED", reason_code=task.get("reason_code"),
                                        message="保留阻塞记录，不自动重新调用模型")
                        else:
                            completed, recovered = _package_status(config, task)
                            if not completed:
                                draft_result = recover_failed_draft(config, task, now=now)
                                if draft_result:
                                    completed = load_evidence_manifest(Path(draft_result["manifest_path"]))
                                    recovered = True
                                    item.update(recovery=draft_result)
                            if completed:
                                changed = False
                                if state != "COMPLETED":
                                    changed = complete_task_from_package(config.zotero.group_id, key, completed,
                                        config.tasks, config.paths.tasks_file, config.paths.lock_file, now=now)["changed"]
                                item.update(status="RECOVERED" if recovered or changed else "SKIPPED",
                                            reason_code="PACKAGE_RECONCILED" if recovered or changed else "EXISTING_CARD",
                                            card_path=str(find_evidence_package(config.paths.evidence_packs_dir, key) / "card.md"))
                            elif state not in {"READY_FOR_EXTRACTION", "RETRY_PENDING"}:
                                item.update(status="BLOCKED", reason_code="STATE_NOT_ELIGIBLE")
                            elif type(task.get("attempt_count")) is not int or task["attempt_count"] < 0:
                                item.update(status="BLOCKED", reason_code="ATTEMPT_COUNT_INVALID")
                            elif task["attempt_count"] >= config.pipeline.max_attempts_per_item:
                                item.update(status="BLOCKED", reason_code="ATTEMPT_LIMIT")
                            elif state == "RETRY_PENDING" and task.get("reason_code") not in RETRYABLE_REASONS:
                                item.update(status="BLOCKED", reason_code="NON_RETRYABLE_FAILURE",
                                            original_reason_code=task.get("reason_code"),
                                            message="非暂时性运行故障，不自动重跑；保留草稿和错误记录")
                            else:
                                updated = _parse_timestamp(task.get("updated_at"))
                                cooling = state == "RETRY_PENDING" and (updated is None or
                                    ((now or _now()) - updated).total_seconds() < config.pipeline.retry_cooldown_seconds)
                                remaining = remaining_seconds()
                                if cooling:
                                    item.update(status="DEFERRED", reason_code="RETRY_COOLDOWN")
                                elif stop_reason:
                                    item.update(status="DEFERRED", reason_code=stop_reason)
                                elif (config.pipeline.max_items_per_run is not None
                                      and report["generation_attempt_count"] >= config.pipeline.max_items_per_run):
                                    item.update(status="DEFERRED", reason_code="RUN_ITEM_LIMIT")
                                elif remaining < 1:
                                    item.update(status="DEFERRED", reason_code="RUN_TIME_LIMIT")
                                else:
                                    phase = "generation"
                                    if not generator_ready:
                                        validate_evidence_templates(config.paths.evidence_card_templates_dir,
                                                                    config.paths.evidence_card_template_catalog_file)
                                        checked = build_card_generator_adapter(config.card_generator, progress=progress).preflight()
                                        if not checked["ok"]:
                                            failure = checked.get("error", {})
                                            raise CardGenerationError(failure.get("code", "GENERATOR_NOT_READY"),
                                                                      failure.get("message", "制卡器预检未通过"))
                                        generator_ready = True
                                    remaining = remaining_seconds()
                                    if remaining < 1:
                                        item.update(status="DEFERRED", reason_code="RUN_TIME_LIMIT")
                                    else:
                                        sync_evidence_packages(config.zotero.group_id, config.tasks, config.paths.tasks_file,
                                            config.paths.lock_file, config.paths.evidence_packs_dir, parent_keys={key}, now=now)
                                        bounded = replace(config.card_generator, generation_timeout_seconds=min(
                                            config.card_generator.generation_timeout_seconds, remaining))
                                        adapter = build_card_generator_adapter(bounded, progress=progress)
                                        report["generation_attempt_count"] += 1
                                        report_progress(progress, "phase", message=f"队列 {queue_index}/{len(tasks)}，本轮第 {report['generation_attempt_count']} 篇制卡：{key}；完成即保存正式 card.md")
                                        generated = generate_evidence_card(config.zotero, config.pdf_gate, config.tasks,
                                            config.paths.tasks_file, config.paths.lock_file, config.paths.evidence_packs_dir,
                                            config.paths.evidence_card_templates_dir, config.paths.evidence_card_template_catalog_file,
                                            config.paths.evidence_card_generation_prompt_file, config.paths.card_generation_output_schema_file,
                                            key, adapter, now=now)
                                        item.update(status="COMPLETED" if generated["action"] == "GENERATED" else "SKIPPED",
                                                    reason_code=generated["action"], card_path=generated.get("card_path"))
                    except KeyboardInterrupt:
                        item.update(status="FAILED", error={"code": "CANCELLED", "message": "本篇处理被用户中止"})
                        report["items"].append(item)
                        raise
                    except (*KNOWN_ERRORS, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                        failure = _error(exc)
                        item.update(status="FAILED" if phase == "generation" else "BLOCKED", error=failure)
                        if phase == "generation" and not generator_ready:
                            stop_reason = "GENERATOR_PREFLIGHT_FAILED"
                        elif failure["code"] in GLOBAL_GENERATOR_ERRORS:
                            stop_reason = "GENERATOR_SERVICE_UNAVAILABLE"
                    report["items"].append(item)
                    report_progress(progress, "phase", message=f"{key}：{item['status']}，{item.get('reason_code') or item.get('error', {}).get('code', '')}")
                    if item.get("card_path"):
                        report_progress(progress, "phase", message=f"正式卡片：{item['card_path']}")
                if config.theme_pipeline.enabled:
                    phase = "themes"
                    if stop_reason or any(item["status"] in {"FAILED", "BLOCKED", "DEFERRED"} or
                            (item["status"] == "WAITING" and item.get("reason_code") in
                             {"PDF_FILE_NOT_SYNCED", "FULLTEXT_NOT_INDEXED", "ACTIVE_LEASE"}) for item in report["items"]):
                        report["theme_pipeline"] = {"ok": False, "status": "DEFERRED",
                            "note": "本轮有失败、阻塞、限额延后或附件同步/索引未就绪；保留已有主题，避免临时不完整集合重复生成。单纯尚未添加PDF的条目不阻塞已有粗卡主题，可用themes-run显式处理已有粗卡。"}
                    else:
                        report["theme_pipeline"] = run_themes(config, progress=progress, remaining_seconds=remaining_seconds)
                        if not report["theme_pipeline"]["ok"]:
                            report.update(ok=False, status="CANCELLED" if report["theme_pipeline"]["status"] == "CANCELLED" else "COMPLETED_WITH_BLOCKERS")
    except (*KNOWN_ERRORS, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        if phase == "acquire_run_lock" and isinstance(exc, TaskStoreError) and exc.code == "TASK_STORE_BUSY":
            report.update(status="ALREADY_RUNNING", note="已有统一运行实例，未扫描 Zotero 或调用模型")
        else:
            report.update(ok=False, status="FAILED", error=_error(exc), failed_stage=phase)
    except KeyboardInterrupt:
        report.update(ok=False, status="CANCELLED", error={"code": "CANCELLED", "message": "本轮已中止；完成结果和待保存记录保留"})
    counts = {name.lower(): sum(item["status"] == name for item in report["items"])
              for name in ("COMPLETED", "RECOVERED", "SKIPPED", "WAITING", "BLOCKED", "FAILED", "DEFERRED")}
    report.update(counts=counts, finished_at=_now().isoformat(), elapsed_seconds=round(clock() - started, 2))
    if report["ok"] and (counts["blocked"] or counts["failed"]):
        report.update(ok=False, status="COMPLETED_WITH_BLOCKERS")
    elif report["ok"] and (counts["waiting"] or counts["deferred"]):
        report.update(status="COMPLETED_WITH_PENDING", pending_count=counts["waiting"] + counts["deferred"],
                      note="本轮可处理部分已完成，仍有等待/延后项；定时调度按冷却与次数上限补查，不代表全部完成")
    if config.activity_reporting.enabled and report["status"] != "ALREADY_RUNNING":
        if observed_snapshot is not None and "before_generation" in monitoring:
            try:
                monitoring["after_generation"] = sync_activity(config, snapshot=observed_snapshot, run_report=report, now=now)
                if not monitoring["after_generation"]["ok"]:
                    monitoring["errors"].append({"stage": "activity_after", "code": "ACTIVITY_PACKAGE_ISSUES"})
            except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
                monitoring["errors"].append({"stage": "activity_after", "code": getattr(exc, "code", "ACTIVITY_FAILED")})
        try:
            report["activity_reporting"] = monitoring
            if monitoring["errors"] and report["ok"]:
                report.update(ok=False, status="COMPLETED_WITH_BLOCKERS")
            monitoring["daily_report"] = daily_report(config, run_report=report, now=now)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
            monitoring["errors"].append({"stage": "daily_report", "code": getattr(exc, "code", "DAILY_REPORT_FAILED")})
        report["activity_reporting"] = monitoring
        if monitoring["errors"]:
            if report["ok"]:
                report.update(ok=False, status="COMPLETED_WITH_BLOCKERS")
            report["monitoring_warning"] = "贡献记录或日报未全部保存；已完成卡片保留，不因此重新调用模型"
    report_path = config.paths.logs_dir / "pipeline-runs" / f"{moment.strftime('%Y%m%dT%H%M%S')}-{report['run_id']}.json"
    report["report_path"] = str(report_path)
    try:
        atomic_text(report_path, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except OSError:
        report.pop("report_path", None)
        report.update(ok=False, report_warning="无法保存本轮摘要；不撤销已完成卡片、不重跑模型")
    return report
