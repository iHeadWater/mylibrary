"""Relocate only source/shared knowledge; rebuild dependencies and disposable state without models."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hydro_platform.config import load_config
from hydro_platform.publication import atomic_text
from verify_runtime_recovery import _protected

DIRECTORIES = ("automation", "templates", "evidence-packs", "themes", "members", "activity", "reports")
EXCLUDED = {"__pycache__", ".runtime", ".venv", ".tools", ".git"}
NO_MODEL_RUN = r'''
import json,sys
sys.stdout.reconfigure(encoding='utf-8')
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(sys.argv[1]) / 'automation/src'))
from hydro_platform.config import load_config
from hydro_platform.pipeline import run_once
config=load_config(Path(sys.argv[1]) / 'config/config.json', require_group=True)
with ExitStack() as stack:
    guards=[stack.enter_context(patch(target, side_effect=AssertionError('models/launch/schedule forbidden in relocation drill')))
        for target in ('hydro_platform.pipeline.build_card_generator_adapter',
                       'hydro_platform.themes.CodexTextAdapter.generate',
                       'hydro_platform.themes.CodexLocalPdfAdapter.generate',
                       'hydro_platform.zotero_readiness.launch_zotero',
                       'hydro_platform.windows_schedule.native_call')]
    first=run_once(config)
    second=run_once(config) if first['ok'] else None
    calls=sum(g.call_count for g in guards)
print(json.dumps({'ok':bool(first['ok'] and second and second['ok'] and calls==0),
                 'forbidden_call_count':calls,'first':first,'second':second},ensure_ascii=False))
'''


def copy_shared(source, target):
    """Whitelist excludes runtime, credentials and PDFs; reject links rather than follow them."""
    target.mkdir(parents=True, exist_ok=False)
    for name in DIRECTORIES:
        directory = source / name
        if not directory.exists():
            continue
        for path in [directory, *directory.rglob("*")]:
            relative = path.relative_to(source)
            if any(part in EXCLUDED for part in relative.parts):
                continue
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ValueError("shared input contains redirected path")
            if path.is_dir():
                continue
            if path.suffix.lower() in {".pdf", ".key", ".pem", ".pyc", ".log"} or path.name.startswith(".env"):
                continue
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    # The selected complete config is copied explicitly by verify; local config/credentials aren't copied.


def _run_json(argv, *, cwd, timeout):
    process = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=timeout,
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    result = json.loads(process.stdout.decode("utf-8-sig"))
    if process.returncode and result.get("ok"):
        raise ValueError("process/result mismatch")
    return result


def verify(config, *, resume=None):
    before = _protected(config)
    trials = config.paths.runtime_dir / "setup-trials"
    trials.mkdir(parents=True, exist_ok=True)
    root = Path(resume).resolve() if resume else trials / ("relocated-" + uuid4().hex)
    if root.parent != trials.resolve() or root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
        raise ValueError("trial path outside setup trials")
    project = root / "project"
    report = {"schema_version": 1, "operation": "verify_setup", "ok": False,
        "trial_root": str(root), "project_copy": str(project), "resumed": bool(resume), "model_call_count": 0,
        "scope": "同机新项目路径；不复制旧运行/依赖，仍使用已有基础Python、Zotero、Codex及登录；不注册自动任务",
        "report_path": str(root / "verification.json")}
    owner = {"owner": "hydro-setup-trial-v1", "source": str(config.paths.project_root.resolve()), "project": str(project)}
    if resume and json.loads((root / "owner.json").read_text(encoding="utf-8")) != owner:
        raise ValueError("unknown trial owner")  # Never write a report into an unknown supplied directory.
    if resume and (root / "verification.json").is_file():
        atomic_text(root / ("verification-before-resume-" + uuid4().hex + ".json"),
                    (root / "verification.json").read_text(encoding="utf-8"))
    try:
        if not resume:
            root.mkdir(exist_ok=False)  # Normal inherited ACL, not a private 0700 executable directory.
            atomic_text(root / "owner.json", json.dumps(owner))
            copy_shared(config.paths.project_root, project)
            data = json.loads(config.source_file.read_text(encoding="utf-8"))
            data["paths"]["project_root"] = ".."
            data["scheduler"]["enabled"] = False
            data["zotero"]["startup"]["launch_if_missing"] = False
            data["deployment"]["base_python"] = str(Path(sys._base_executable).resolve())
            data["deployment"]["download_timeout_seconds"] = 60
            atomic_text(project / "config/config.json", json.dumps(data, ensure_ascii=False, indent=2))
        trial = load_config(project / "config/config.json", require_group=True)
        if trial.paths.project_root != project or trial.scheduler.enabled or trial.zotero.startup.launch_if_missing:
            raise ValueError("trial must remain isolated and cannot schedule/launch")
        base = trial.deployment.base_python
        runner = str(project / "automation/run.py")
        limit = max(600, config.deployment.install_timeout_seconds * 4)
        report["current_stage"] = "plan"
        report["plan"] = _run_json([base, "-I", runner, "setup", "--json"], cwd=root, timeout=limit)
        if not report["plan"]["ok"]:
            return report
        report["current_stage"] = "first_setup"
        report["first_setup"] = _run_json([base, "-I", runner, "setup", "--apply", "--no-progress", "--json"], cwd=root, timeout=limit)
        if not report["first_setup"]["ok"]:
            return report
        python = str(trial.deployment.environment_dir / "Scripts/python.exe")
        report["current_stage"] = "second_setup"
        report["second_setup"] = _run_json([python, "-I", runner, "setup", "--apply", "--no-progress", "--json"], cwd=root, timeout=limit)
        if not report["second_setup"]["ok"]:
            return report
        report["current_stage"] = "pipeline"
        report["pipeline"] = _run_json([python, "-I", "-c", NO_MODEL_RUN, str(project)], cwd=root, timeout=limit)
        if not report["pipeline"]["ok"]:
            return report
        keys = [item["parent_key"] for step in report["first_setup"]["steps"] if step["name"] == "runtime_recovery"
                for item in step["result"]["items"] if item["state"] == "COMPLETED"]
        if keys:
            report["current_stage"] = "pdf_compatibility"
            argv = [python, "-I", str(project / "automation/verify_deployment.py")]
            for key in keys:
                argv.extend(["--item-key", key])
            report["pdf_compatibility"] = _run_json(argv, cwd=root, timeout=limit)
        report["ok"] = report["pipeline"]["ok"] and report.get("pdf_compatibility", {"ok": True})["ok"]
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        report["error"] = {"code": "SETUP_DRILL_FAILED", "exception_type": type(exc).__name__,
            "message": "新路径恢复演练未完成；保留目录和阶段结果，可按原trial路径继续，未复制凭据或重跑模型"}
    finally:
        report["protected_file_count"] = len(before)
        report["original_runtime_and_knowledge_unchanged"] = before == _protected(config)
        report["ok"] = report["ok"] and report["original_runtime_and_knowledge_unchanged"]
        # Keep every attempt, including the failed report; resume must not erase evidence.
        attempt = root / ("verification-" + uuid4().hex + ".json")
        report["attempt_report_path"] = str(attempt)
        atomic_text(attempt, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        atomic_text(root / "verification.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="同机新目录完整安装/恢复演练；无模型，无系统任务")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config/config.json"))
    parser.add_argument("--resume", help="上次返回的trial_root；继续已确认终止的本项目演练，不用于仍运行的进程")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = verify(load_config(args.config, require_group=True), resume=args.resume)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
