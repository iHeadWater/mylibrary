"""Rebuild only disposable local state. Never call AI or modify shared knowledge."""
from __future__ import annotations

import json
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from hydro_platform.evidence_packages import (
    EvidencePackageError, find_evidence_package, load_evidence_manifest, validate_evidence_task,
)
from hydro_platform.pdf_gate import PdfGateError, evaluate_pdf_gate
from hydro_platform.publication import atomic_text, identity, validate_saved_package
from hydro_platform.snapshot import SnapshotError, fetch_snapshot, load_snapshot, save_snapshot
from hydro_platform.tasks import (
    PipelineRunLock, RuntimeLock, TaskStoreError, _lease_expired, load_task_registry,
    reconcile_completed_package, reconcile_tasks, save_task_registry,
)
from hydro_platform.zotero import ZoteroApiError, preflight

KNOWN_ERRORS = (EvidencePackageError, PdfGateError, SnapshotError, TaskStoreError, ZoteroApiError)


def _error(exc):
    if isinstance(exc, KNOWN_ERRORS):
        return {"code": exc.code, "message": str(exc)}
    return {"code": "RECOVERY_LOCAL_ERROR", "message": "本地记录或文件访问失败；未删除任何现有记录，可修复后重复对账"}


def _reconcile_package(config, registry, key, *, now):
    task = registry["tasks"][key]
    item = {"parent_key": key, "title": task.get("title"), "state": task["state"]}
    if task["state"] in {"REMOVED", "BLOCKED"} or task["state"].startswith("WAITING"):
        return {**item, "reason_code": task["reason_code"]}
    normalized = validate_evidence_task(task, config.zotero.group_id)
    root = config.paths.evidence_packs_dir
    package = find_evidence_package(root, key) if root.exists() else None
    if package is None:
        if task["state"] == "COMPLETED":
            raise EvidencePackageError("EVIDENCE_PACKAGE_MISSING", "已完成任务的证据包缺失，不自动重复制卡")
        return {**item, "reason_code": "NO_SAVED_CARD"}
    expected = {name: normalized[name] for name in ("group_id", "parent_key", "attachment_key", "pdf_sha256")}
    expected.update(source_task_id=normalized["task_id"], evidence_id=f"EV-{key}")
    manifest = load_evidence_manifest(package / "manifest.json")
    if identity(manifest) != expected:
        raise EvidencePackageError("EVIDENCE_INPUT_MISMATCH", "当前 PDF 来源与已保存证据包不同，保留旧卡和运行记录")
    completed = validate_saved_package(package)
    if completed is None:
        if task["state"] == "COMPLETED":
            raise EvidencePackageError("EVIDENCE_PACKAGE_INCONSISTENT", "任务已完成但证据包仍为占位卡")
        return {**item, "reason_code": "PLACEHOLDER", "package_path": str(package)}
    result = reconcile_completed_package(registry, key, completed, config.tasks, now=now)
    return {**item, "state": "COMPLETED", "reason_code": "PACKAGE_RECONCILED",
            "completion_restored": result["changed"], "card_path": str(package / "card.md")}


def recover_runtime(config, *, dry_run=False, now=None):
    moment = now or datetime.now(timezone.utc)
    paths = config.paths
    report = {"schema_version": 1, "ok": False, "operation": "recover", "run_id": uuid4().hex,
              "started_at": moment.isoformat(), "group_id": config.zotero.group_id,
              "dry_run": dry_run, "model_invoked": False, "model_call_count": 0,
              "shared_files_modified": False, "git_modified": False, "contribution_events_written": 0,
              "state_files_written": [], "items": []}
    try:
        with ExitStack() as stack:
            if not dry_run:
                # Same ordering as run-once -> themes-run; do not steal a live instance.
                for suffix in (".pipeline", ".themes"):
                    stack.enter_context(PipelineRunLock(paths.lock_file.with_name(paths.lock_file.name + suffix)))
                stack.enter_context(RuntimeLock(paths.lock_file, stale_seconds=config.tasks.lock_stale_seconds))
            before = load_task_registry(paths.tasks_file, config.zotero.group_id, now=moment)
            baseline = load_snapshot(paths.snapshot_file)
            if baseline is not None and baseline.get("group_id") != config.zotero.group_id:
                raise SnapshotError("SNAPSHOT_GROUP_MISMATCH", "已有快照属于另一个共享库，不能覆盖")
            if any(task.get("state") == "PROCESSING" and not _lease_expired(task, moment)
                   for task in before["tasks"].values()):
                raise TaskStoreError("TASK_NOT_CLAIMABLE", "仍有有效处理租约；恢复不抢占正在运行的任务")
            readiness = preflight(config.zotero)
            if not readiness.get("ok"):
                report.update(status="BLOCKED", error=readiness.get("error") or {
                    "code": "ZOTERO_NOT_READY", "message": "Zotero 或目标共享库尚未就绪"})
            else:
                snapshot = fetch_snapshot(config.zotero, page_size=config.scan.page_size)
                gates = {key: evaluate_pdf_gate(config.zotero, config.pdf_gate, key) for key in snapshot["parents"]}
                registry = deepcopy(before)
                reconcile_tasks(registry, snapshot, gates, config.tasks, now=moment)
                for key in sorted(registry["tasks"]):
                    try:
                        report["items"].append(_reconcile_package(config, registry, key, now=moment))
                    except KNOWN_ERRORS as exc:
                        report["items"].append({"parent_key": key, "state": "CONFLICT", "error": _error(exc)})
                report["counts"] = dict(Counter(item["state"] for item in report["items"]))
                report["changed_task_count"] = sum(task != before["tasks"].get(key)
                                                   for key, task in registry["tasks"].items())
                report["baseline_mode"] = "RESTORE_WITHOUT_HISTORICAL_EVENTS"
                if report["counts"].get("CONFLICT", 0):
                    report.update(status="BLOCKED", error={"code": "RECOVERY_CONFLICT",
                        "message": "证据包对账存在冲突；未保存本轮任务或快照，未覆盖共享内容"})
                else:
                    if not dry_run:
                        if registry != before or not paths.tasks_file.exists():
                            save_task_registry(paths.tasks_file, registry)
                            report["state_files_written"].append(str(paths.tasks_file))
                        # Save a baseline, never feed the initial diff into a contribution stream.
                        save_snapshot(paths.snapshot_file, snapshot)
                        report["state_files_written"].append(str(paths.snapshot_file))
                    report.update(ok=True, status="PREVIEW" if dry_run else "RECOVERED")
                    report["note"] = ("仅恢复任务和扫描基线；未制卡、未补写中断发布文件、未运行主题或安装调度。"
                                      "主题已完成步骤仍由共享文件复用；本命令不代表主题结果已复核。")
    except (*KNOWN_ERRORS, OSError, ValueError, TypeError, KeyError) as exc:
        report.update(ok=False, status="BLOCKED", error=_error(exc))
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    if not dry_run:
        log = paths.logs_dir / "recovery-runs" / (report["run_id"] + ".json")
        report["report_path"] = str(log)
        try:
            atomic_text(log, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        except OSError:
            report.pop("report_path", None)
            report["report_warning"] = "恢复报告未能写入日志，请保留本次输出；以 state_files_written 判断已保存的状态文件"
    return report
