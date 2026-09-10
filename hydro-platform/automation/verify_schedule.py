"""Create/run/remove a uniquely owned no-model Windows task; never use production input."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from hydro_platform.config import load_config
from hydro_platform.publication import atomic_text
from hydro_platform.windows_schedule import native_call, ownership, task_xml
from verify_runtime_recovery import _protected


def verify(config, token=None):
    resume = token is not None
    if resume:
        import re
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            raise ValueError("invalid probe token")
    token = token or uuid4().hex
    name = "HydroPlatform-Probe-" + token
    root = config.paths.runtime_dir / "schedule-probes"
    report_path = root / ("verification-" + token + ".json")
    receipt_path = root / (token + ".json")
    report = {"schema_version": 1, "ok": False, "operation": "verify_schedule", "task_name": name,
              "probe_token": token, "model_call_count": 0, "registered": False, "started": False,
              "completed": False, "removed": False, "report_path": str(report_path)}
    before = _protected(config)
    def call(op, **kwargs):
        return native_call(config, op, task_name=name, **kwargs)
    try:
        existing = call("query")
        if existing["exists"] and not resume:
            raise ValueError("Unique probe task already exists")
        if resume and (not existing["exists"] or existing.get("description") != ownership(config)
                       or token not in existing.get("xml", "")):
            raise ValueError("Original probe handle missing or changed; do not restart")
        created = existing if resume else call("install", xml=task_xml(config, existing["user_sid"], probe_token=token))
        report["registered"] = bool(created["exists"] and created["description"] == ownership(config))
        if not report["registered"]:
            raise ValueError("Probe registration unverified")
        # 0x41303 is Task Scheduler's never-run state. Other observed states are only polled.
        if not resume or (created.get("last_task_result") == 0x41303 and not receipt_path.exists()):
            call("run")
        report["started"] = True
        # A start timeout never causes another start; observe the same named task/nonce.
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            current = call("query")
            report["native_state"] = current.get("state")
            report["last_task_result"] = current.get("last_task_result")
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if receipt.get("probe_token") != token or receipt.get("model_call_count") != 0:
                    raise ValueError("Probe receipt mismatch")
                report["receipt"] = receipt
                if current.get("state") != "Running":
                    report["completed"] = current.get("last_task_result") == 0
                    break
            time.sleep(1)
        report["ok"] = report["completed"]
    except Exception as exc:
        report["error"] = {"code": getattr(exc, "code", "SCHEDULE_PROBE_ERROR"),
                           "message": "Windows 调度探针未通过；未读取论文或调用模型", "type": type(exc).__name__,
                           "diagnostic": getattr(exc, "diagnostic", None)}
    finally:
        if report["registered"]:
            try:
                current = call("query")
                if current.get("exists") and current.get("state") != "Running" and current.get("description") == ownership(config):
                    report["removed"] = not call("remove")["exists"]
                else:
                    report["cleanup_note"] = "探针仍运行或状态不明，保留原任务句柄；只继续观察，不重新创建/启动"
            except Exception:
                report["cleanup_note"] = "清理状态未知；须按 task_name 查询原任务，不重复创建"
        report["original_runtime_and_knowledge_unchanged"] = before == _protected(config)
        report["protected_file_count"] = len(before)
        report["ok"] = report["ok"] and report["removed"] and report["original_runtime_and_knowledge_unchanged"]
        atomic_text(report_path, json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description="注册、运行并移除一个独立探针任务；不调用模型、不修改生产计划")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config/config.json"))
    parser.add_argument("--resume-token", help="仅继续观察已创建的原探针；只有系统明确从未运行时才首次启动")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = verify(load_config(args.config, require_group=True), args.resume_token)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
