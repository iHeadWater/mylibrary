"""Read-only project health checks. No model probes, installation or repairs."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from hydro_platform.card_generators import build_card_generator_adapter
from hydro_platform.evidence_templates import validate_evidence_templates
from hydro_platform.snapshot import load_snapshot
from hydro_platform.tasks import load_task_registry
from hydro_platform.themes import ASSETS
from hydro_platform.zotero import preflight
from hydro_platform.zotero_readiness import resolve_startup_executable
from hydro_platform.activity import load_ledger, member_mapping
from hydro_platform.deployment import load_dependency_lock
from hydro_platform.native_deployment import bootstrap_native
from hydro_platform.windows_schedule import manage_schedule


def _python_probe(config):
    settings = config.card_generator.pdf_direct_trial
    if settings is None:
        return {"ok": False, "error": {"code": "CONFIG_ERROR", "message": "当前路径读取工作流缺少 PDF 读取配置"}}
    executable = shutil.which(settings.python_executable or sys.executable)
    if executable is None:
        return {"ok": False, "error": {"code": "PYTHON_NOT_FOUND", "message": "找不到配置的 PDF 读取 Python"}}
    # Execute only a fixed, credential-free dependency probe, never user/model text.
    script = "import json,sys; data={'python':list(sys.version_info[:3])}; "
    if settings.text_extractor == "pypdf":
        script += "import pypdf; data['pypdf']=pypdf.__version__; "
    script += "print(json.dumps(data))"
    try:
        result = subprocess.run([executable, "-B", "-c", script], capture_output=True,
                                timeout=config.card_generator.preflight_timeout_seconds, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            return {"ok": False, "resolved_python": executable, "error": {
                "code": "PDF_PYTHON_DEPENDENCY_MISSING", "message": "配置的 Python 不能导入 PDF 依赖；未自动安装"}}
        data = json.loads(result.stdout.decode("utf-8"))
        version = data["python"]
        compatible = (3, 12) <= tuple(version[:2]) < (3, 15)
        report = {"ok": compatible, "resolved_python": executable, "versions": data}
        if not compatible:
            report["error"] = {"code": "PYTHON_VERSION_UNSUPPORTED", "message": "读取器 Python 需要 >=3.12,<3.15"}
        lock, _ = load_dependency_lock(config)
        expected = next((p["version"] for p in lock["packages"] if p["name"] == "pypdf"), None)
        report["locked_pypdf"] = expected
        if data.get("pypdf") not in {None, expected}:
            report["warning"] = f"pypdf 可导入，但与项目依赖锁版本 {expected} 不同；未自动更改环境"
        return report
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError):
        return {"ok": False, "error": {"code": "PDF_PYTHON_PROBE_FAILED", "message": "PDF 读取 Python 探测失败或超时；未输出原始 stderr"}}


def _assets(config):
    paths = [config.paths.evidence_card_generation_prompt_file, config.paths.card_generation_output_schema_file]
    if config.theme_pipeline.enabled:
        root = config.theme_pipeline.assets_dir or config.paths.templates_dir / "themes"
        paths.extend(root / name for name in ASSETS)
    for path in paths:
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            raise ValueError("配置的提示词或结构文件为空")
        if path.suffix == ".json" and not isinstance(json.loads(content), dict):
            raise ValueError("输出结构文件必须是 JSON 对象")
    return {"ok": True, "file_count": len(paths), "paths": [str(path) for path in paths]}


def _local_state(config):
    registry = load_task_registry(config.paths.tasks_file, config.zotero.group_id)
    snapshot = load_snapshot(config.paths.snapshot_file)
    if snapshot is not None and snapshot.get("group_id") != config.zotero.group_id:
        return {"ok": False, "error": {"code": "SNAPSHOT_GROUP_MISMATCH", "message": "现有扫描快照不属于配置的共享库"}}
    return {"ok": True, "task_count": len(registry["tasks"]),
            "tasks_exist": config.paths.tasks_file.exists(), "snapshot_exists": snapshot is not None,
            "note": "运行记录缺失允许用 recover 重建；本项只检查可解析性和群组，不验证每份知识文件"}


def doctor(config):
    checks = []

    def check(name, action):
        try:
            result = action()
            checks.append({"name": name, "status": "fail" if not result.get("ok") else
                           "warning" if result.get("warning") else "pass", "result": result})
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            checks.append({"name": name, "status": "fail", "error": {
                "code": getattr(exc, "code", "DOCTOR_CHECK_FAILED"),
                "message": f"{name} 检查失败（{type(exc).__name__}）；请检查总配置中对应路径和依赖"}})

    check("automation_python", lambda: {"ok": (3, 12) <= sys.version_info[:2] < (3, 15),
                                         "executable": sys.executable, "version": list(sys.version_info[:3])})
    check("workflow", lambda: {"ok": config.card_generator.workflow_mode == "single_agent"
                               and config.card_generator.pdf_reader.adapter == "local_path",
                               "mode": config.card_generator.workflow_mode,
                               "pdf_reader": config.card_generator.pdf_reader.adapter})
    check("evidence_templates", lambda: validate_evidence_templates(
        config.paths.evidence_card_templates_dir, config.paths.evidence_card_template_catalog_file))
    check("generation_assets", lambda: _assets(config))
    check("runtime_records", lambda: _local_state(config))
    check("zotero_group", lambda: preflight(config.zotero))
    if config.zotero.startup.enabled and config.zotero.startup.launch_if_missing:
        check("zotero_startup", lambda: {"ok": True,
            "resolved_executable": resolve_startup_executable(config.zotero.startup),
            "note": "只核对启动路径；未启动/重启应用，不证明账号同步完成"})
    check("codex_and_pdf_tools", lambda: build_card_generator_adapter(config.card_generator).preflight())
    check("pdf_python", lambda: _python_probe(config))
    native_root = config.deployment.native_tools_dir
    if native_root and any(Path(getattr(config.card_generator.pdf_reader, name)).is_relative_to(native_root)
                           for name in ("pdfinfo_executable", "pdftoppm_executable", "pdftotext_executable")):
        check("native_pdf_tools", lambda: bootstrap_native(config, verify=True))
    if config.activity_reporting.enabled:
        def reporting():
            path, ledger = load_ledger(config)
            mapping = member_mapping(config)
            return {"ok": True, "ledger_initialized": ledger is not None,
                    "event_count": len(ledger["events"]) if ledger else 0,
                    "mapped_member_count": len(mapping), "ledger_path": str(path),
                    "note": "只验证事件记录与可选成员映射；缺基线将在首次运行建立，不代表个人归属已齐全或调度已启用"}
        check("activity_records", reporting)
    if config.scheduler.enabled:
        check("windows_schedule", lambda: manage_schedule(config, "status"))
    ok = all(row["status"] != "fail" for row in checks)
    result = {"schema_version": 1, "ok": ok, "operation": "doctor",
              "checked_at": datetime.now(timezone.utc).isoformat(), "checks": checks,
              "model_invoked": False, "model_call_count": 0,
              "knowledge_files_modified": False, "runtime_state_modified": False,
              "note": "只读检查配置、依赖、登录和本地 Zotero；启用调度时另核对 Windows 定义与当前状态。不调用模型，不证明论文理解、实际日历/登录触发或异机部署已通过"}
    if not ok:
        result["error"] = {"code": "DOCTOR_FAILED", "message": "部分运行检查未通过，详见 checks；未自动修复或安装"}
    return result
