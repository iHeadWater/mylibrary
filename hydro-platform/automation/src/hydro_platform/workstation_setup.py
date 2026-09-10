"""One ordered project setup/recovery entry. Never generate knowledge or log in for a user."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from hydro_platform.card_generators.codex_cli import CodexCliAdapter
from hydro_platform.deployment import bootstrap
from hydro_platform.doctor import doctor
from hydro_platform.native_deployment import bootstrap_native, TOOLS
from hydro_platform.progress import report_progress
from hydro_platform.publication import atomic_text
from hydro_platform.runtime_recovery import recover_runtime
from hydro_platform.tasks import PipelineRunLock
from hydro_platform.windows_schedule import manage_schedule
from hydro_platform.zotero import preflight
from hydro_platform.zotero_readiness import ensure_zotero_ready


class SetupStopped(RuntimeError):
    pass


LABELS = {"configuration_bindings": "配置与读取路径", "python_plan": "Python安装计划",
    "native_plan": "PDF工具安装计划", "codex_login": "Codex程序和登录", "zotero_ready": "Zotero共享库就绪",
    "python_install": "安装或复用项目Python", "native_install": "安装或复用PDF工具",
    "environment_check": "环境检查", "runtime_recovery": "恢复本地状态", "schedule_install": "恢复每日计划",
    "final_check": "最终检查"}


def _bindings(config):
    """Do not install unused tools or silently replace the user's selected reader."""
    direct, reader = config.card_generator.pdf_direct_trial, config.card_generator.pdf_reader
    expected_python = config.deployment.environment_dir / "Scripts/python.exe"
    expected = {name: config.deployment.native_tools_dir / path for name, path in TOOLS.items()}
    matches = bool(direct and direct.python_executable and
                   Path(direct.python_executable).resolve() == expected_python.resolve() and
                   all(Path(getattr(reader, name + "_executable")).resolve() == path.resolve()
                       for name, path in expected.items()))
    mode = config.card_generator.workflow_mode == "single_agent" and reader.adapter == "local_path"
    result = {"ok": matches and mode, "python_executable": str(expected_python),
              "tools": {k: str(v) for k, v in expected.items()}}
    if not result["ok"]:
        result["error"] = {"code": "SETUP_READER_BINDING_MISMATCH", "message":
            "统一安装要求当前单Agent路径模式，且读取器指向deployment的项目环境/工具；请在总配置对齐路径，不会自动改配置"}
    return result


def setup_workstation(config, *, apply=False, progress=None):
    started = time.monotonic()
    report = {"schema_version": 1, "operation": "setup", "ok": False,
        "run_id": uuid4().hex, "started_at": datetime.now(timezone.utc).isoformat(),
        "apply_requested": apply, "steps": [], "model_call_count": 0,
        "config_modified": False, "shared_files_modified": False, "git_modified": False,
        "note": "安装/对账本身不调用模型；启用的每日计划随后可按原配置调用模型。不代登录、不安装基础软件、不推Git。"}
    source_hash = None
    try:
        if config.source_file is None:
            raise ValueError("setup requires a saved complete config")
        source_hash = hashlib.sha256(config.source_file.read_bytes()).hexdigest()
        report["config_sha256"] = source_hash

        def step(name, action):
            if hashlib.sha256(config.source_file.read_bytes()).hexdigest() != source_hash:
                raise ValueError("configuration changed during setup")
            row = {"name": name, "status": "RUNNING"}
            report["steps"].append(row)
            report_progress(progress, "phase", stage=LABELS[name], message="开始：" + LABELS[name] + "（不调用模型）")
            when = time.monotonic()
            result = action()
            if hashlib.sha256(config.source_file.read_bytes()).hexdigest() != source_hash:
                raise ValueError("configuration changed during setup")
            row.update(status="PASS" if result.get("ok") else "FAIL", result=result,
                       elapsed_seconds=round(time.monotonic() - when, 2))
            if not result.get("ok"):
                report["failed_step"] = name
                report["error"] = result.get("error") or {"code": "SETUP_CHECK_FAILED",
                    "message": name + "未通过；保留已完成步骤，修复后重复同一命令"}
                raise SetupStopped(name)
            report_progress(progress, "phase", message=LABELS[name] + "通过")
            return result

        def workflow():
            step("configuration_bindings", lambda: _bindings(config))
            step("python_plan", lambda: bootstrap(config))
            step("native_plan", lambda: bootstrap_native(config))
            step("codex_login", lambda: CodexCliAdapter(config.card_generator).preflight(check_pdf_reader=False))
            step("zotero_ready", lambda: ensure_zotero_ready(config.zotero, progress=progress)
                 if apply else preflight(config.zotero))
            report["planned_actions"] = ["python_install", "native_install", "environment_check", "runtime_recovery"]
            if config.scheduler.enabled:
                report["planned_actions"].append("schedule_install")
            report["planned_actions"].append("final_check")
            if not apply:
                report.update(ok=True, status="PLAN")
                return
            step("python_install", lambda: bootstrap(config, install=True))
            step("native_install", lambda: bootstrap_native(config, install=True))
            # An absent schedule on a fresh computer must not fail the dependency check.
            unscheduled = replace(config, scheduler=replace(config.scheduler, enabled=False))
            step("environment_check", lambda: doctor(unscheduled))
            restored = step("runtime_recovery", lambda: recover_runtime(config))
            report["recovered_state_counts"] = restored.get("counts", {})
            report["schedule_enabled"] = config.scheduler.enabled
            if config.scheduler.enabled:
                step("schedule_install", lambda: manage_schedule(config, "install"))
            else:
                report["schedule_note"] = "配置未启用调度；不创建或修改Windows任务，仍可手动run-once"
            final = step("final_check", lambda: doctor(config))
            report["warnings"] = [row["name"] for row in final["checks"] if row["status"] == "warning"]
            report.update(ok=True, status="READY_SCHEDULED" if config.scheduler.enabled else "READY_MANUAL")

        if apply:
            with PipelineRunLock(config.paths.lock_file.with_name(config.paths.lock_file.name + ".setup")):
                workflow()
        else:
            workflow()
    except SetupStopped:
        report.update(status="BLOCKED")
    except KeyboardInterrupt:
        report.update(status="CANCELLED", error={"code": "SETUP_CANCELLED", "message": "安装被中止；保留已完成步骤，不自动删除或重新生成"})
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        code = getattr(exc, "code", "SETUP_LOCAL_ERROR")
        report.update(status="BLOCKED", error={"code": code if isinstance(code, str) else "SETUP_LOCAL_ERROR",
            "message": "安装/恢复或配置核对失败；保留已有环境、知识和计划，检查失败阶段后重复同一命令",
            "exception_type": type(exc).__name__})
    finally:
        running = [row for row in report["steps"] if row["status"] == "RUNNING"]
        if running:
            running[-1]["status"] = "CANCELLED" if report.get("status") == "CANCELLED" else "FAIL"
            report["failed_step"] = running[-1]["name"]
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        if apply:
            path = config.paths.logs_dir / "setup-runs" / (report["run_id"] + ".json")
            report["report_path"] = str(path)
            try:
                atomic_text(path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            except OSError:
                report.pop("report_path", None)
                report["report_warning"] = "无法保存安装报告；请保留终端结果，不代表先前步骤已回滚"
    return report
