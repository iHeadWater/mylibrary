"""Real local Zotero + isolated project copies; model and app launch calls are forbidden."""
from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hydro_platform.config import load_config
from hydro_platform.publication import atomic_text
from hydro_platform.scheduled import scheduled_tick
from verify_runtime_recovery import _protected


def _pids():
    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq zotero.exe", "/FO", "CSV", "/NH"],
        capture_output=True, timeout=10, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    rows = csv.reader(io.StringIO(result.stdout.decode("utf-8", errors="replace")))
    return sorted(int(row[1]) for row in rows if len(row) > 1 and row[0].lower() == "zotero.exe" and row[1].isdigit())


def verify(config):
    before = _protected(config)
    pids_before = _pids()
    trials = config.paths.runtime_dir / "readiness-trials"
    trials.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="readiness-check-", dir=trials)).resolve()
    if root.parent != trials.resolve():
        raise ValueError("isolated runtime outside configured trials")
    copy_paths = {}
    for field in ("evidence_packs_dir", "themes_dir", "activity_dir", "reports_dir", "members_dir"):
        source = getattr(config.paths, field)
        target = root / "project-copy" / source.name
        if source.exists():
            shutil.copytree(source, target, symlinks=True)
        copy_paths[field] = target
    runtime = root / "runtime"
    runtime.mkdir()
    paths = replace(config.paths, **copy_paths, runtime_dir=runtime, tasks_file=runtime / "tasks.json",
        snapshot_file=runtime / "snapshot.json", lock_file=runtime / "worker.lock",
        logs_dir=runtime / "logs", card_trials_dir=runtime / "card-trials")
    for source, destination in ((config.paths.tasks_file, paths.tasks_file),
                                (config.paths.snapshot_file, paths.snapshot_file)):
        if source.exists():
            shutil.copy2(source, destination)
    isolated = replace(config, paths=paths, scheduler=replace(config.scheduler, enabled=True),
        zotero=replace(config.zotero, startup=replace(config.zotero.startup,
            enabled=True, launch_if_missing=False, wait_timeout_seconds=10, poll_interval_seconds=1)),
        card_generator=replace(config.card_generator, runtime_dir=runtime))
    report = {"schema_version": 1, "operation": "verify_zotero_readiness", "ok": False,
        "isolated_root": str(root), "protected_file_count": len(before), "model_call_count": 0,
        "scope": "真实本机Zotero就绪+隔离副本调度去重；禁止模型和启动调用，不证明真实关闭应用后启动或云端同步完成",
        "report_path": str(root / "verification.json")}
    with ExitStack() as stack:
        guards = [stack.enter_context(patch(target, side_effect=AssertionError("forbidden in no-model readiness drill")))
            for target in ("hydro_platform.pipeline.build_card_generator_adapter",
                           "hydro_platform.themes.CodexTextAdapter.generate",
                           "hydro_platform.themes.CodexLocalPdfAdapter.generate",
                           "hydro_platform.zotero_readiness.launch_zotero")]
        try:
            first = scheduled_tick(isolated)
            second = scheduled_tick(isolated) if first["ok"] else None
            pipeline_path = first.get("pipeline_report_path")
            pipeline = json.loads(Path(pipeline_path).read_text(encoding="utf-8")) if pipeline_path else None
            report.update(first_tick=first, second_tick=second, pipeline_report=pipeline,
                forbidden_call_count=sum(guard.call_count for guard in guards))
            report["ok"] = bool(first["ok"] and first["status"] == "COMPLETED" and second
                and second["status"] == "ALREADY_COMPLETED" and pipeline and pipeline["zotero_readiness"]["ok"]
                and pipeline["generation_attempt_count"] == 0
                and (pipeline.get("theme_pipeline") or {}).get("model_call_count", 0) == 0
                and report["forbidden_call_count"] == 0)
        except Exception as exc:
            report["error"] = {"code": "READINESS_DRILL_FAILED", "exception_type": type(exc).__name__}
        finally:
            report["original_runtime_and_knowledge_unchanged"] = before == _protected(config)
            report["zotero_processes_unchanged"] = pids_before == _pids() and bool(pids_before)
            report["ok"] = report["ok"] and report["original_runtime_and_knowledge_unchanged"] and report["zotero_processes_unchanged"]
            atomic_text(root / "verification.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="只读真实Zotero、隔离项目副本的无模型就绪/去重验收")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config/config.json"))
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = verify(load_config(args.config, require_group=True))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
