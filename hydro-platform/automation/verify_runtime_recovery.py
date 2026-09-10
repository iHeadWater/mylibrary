"""Live, no-model recovery drill in a NEW local runtime, never a clean-machine claim."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from hydro_platform.config import load_config
from hydro_platform.publication import atomic_text
from hydro_platform.runtime_recovery import recover_runtime


def _sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _protected(config):
    paths = [config.paths.tasks_file, config.paths.snapshot_file]
    for root in (config.paths.evidence_packs_dir, config.paths.themes_dir,
                 config.paths.activity_dir, config.paths.reports_dir, config.paths.members_dir):
        paths.extend(path for path in root.rglob("*") if path.is_file())
    return {str(path): _sha(path) for path in paths if path.is_file()}


def verify(config):
    before = _protected(config)
    trials = config.paths.runtime_dir / "recovery-trials"
    trials.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="recovery-check-", dir=trials)).resolve()
    if root.parent != trials.resolve():
        raise ValueError("验收目录不在指定运行区中")
    paths = replace(config.paths, runtime_dir=root, tasks_file=root / "tasks.json",
                    snapshot_file=root / "zotero-snapshot.json", lock_file=root / "worker.lock",
                    logs_dir=root / "logs", card_trials_dir=root / "card-trials")
    isolated = replace(config, paths=paths, card_generator=replace(config.card_generator, runtime_dir=root))
    first = recover_runtime(isolated)
    first_tasks_hash = _sha(paths.tasks_file) if paths.tasks_file.exists() else None
    second = recover_runtime(isolated) if first["ok"] else None
    same_tasks = first_tasks_hash is not None and _sha(paths.tasks_file) == first_tasks_hash
    unchanged = before == _protected(config)
    ok = first["ok"] and bool(second and second["ok"]) and same_tasks and unchanged
    report = {"schema_version": 1, "ok": ok, "operation": "verify_runtime_recovery",
              "isolated_runtime": str(root), "model_call_count": 0,
              "original_runtime_and_knowledge_unchanged": unchanged,
              "protected_file_count": len(before), "task_registry_idempotent": same_tasks,
              "first_run": first, "second_run": second,
              "scope": "同机新运行目录 + 真实 Zotero；未模拟异机安装、远端备份或调度恢复，不调用模型",
              "report_path": str(root / "verification.json")}
    atomic_text(root / "verification.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="无模型调用的真实恢复验收，保留新建的验收目录")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config" / "config.json"))
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = verify(load_config(args.config, require_group=True))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
