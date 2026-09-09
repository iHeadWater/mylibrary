"""Explicit, no-model compatibility drill for a project venv and selected real PDFs."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hydro_platform.config import load_config
from hydro_platform.deployment import bootstrap, load_dependency_lock, _probe, _verified
from hydro_platform.pdf_delivery import prepare_pdf_delivery
from hydro_platform.pdf_direct_trial import run_pdf_direct_trial
from hydro_platform.publication import atomic_text
from verify_runtime_recovery import _protected, _sha

TEXT_PROBE = """import json,sys,pypdf
r=pypdf.PdfReader(sys.argv[1]); counts=[len((p.extract_text() or '').strip()) for p in r.pages]
print(json.dumps({'pypdf':pypdf.__version__,'page_count':len(counts),'page_character_counts':counts,'character_count':sum(counts)}))
"""


def verify(config, keys):
    plan = bootstrap(config)
    if not plan["ok"] or plan.get("existing_status") != "READY":
        return {"ok": False, "model_call_count": 0, "error": {"code": "DEPLOYMENT_NOT_READY",
                "message": "请先完成 bootstrap --install；本验证命令不安装依赖"}, "bootstrap": plan}
    lock, _ = load_dependency_lock(config)
    python = plan["python_executable"]
    probe = _probe(python, lock["packages"], config.deployment.install_timeout_seconds)
    if not _verified(probe, lock, Path(plan["environment_dir"])):
        raise ValueError("项目环境与依赖锁不一致")
    before = _protected(config)
    trials = config.paths.runtime_dir / "deployment-trials"
    trials.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="deployment-check-", dir=trials)).resolve()
    trial = replace(config, card_generator=replace(config.card_generator,
        pdf_direct_trial=replace(config.card_generator.pdf_direct_trial, python_executable=python)))
    report = {"schema_version": 1, "operation": "verify_deployment", "ok": False,
              "model_call_count": 0, "python_verification": probe, "items": [],
              "scope": "同机新虚拟环境，真实原始 PDF 全页文字提取及沙箱首图渲染；不证明异机部署或模型理解",
              "report_path": str(root / "verification.json")}
    for key in dict.fromkeys(keys):
        row = {"parent_key": key, "ok": False}
        report["items"].append(row)
        try:
            delivery = prepare_pdf_delivery(config.zotero, config.pdf_gate, config.tasks,
                config.paths.tasks_file, config.paths.lock_file, config.paths.evidence_packs_dir,
                key, allow_trial_states=True)
            source_before = _sha(delivery.pdf_path)
            completed = subprocess.run([python, "-I", "-B", "-c", TEXT_PROBE, str(delivery.pdf_path)],
                capture_output=True, check=True, timeout=config.card_generator.pdf_reader.tool_timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            row["text_extraction"] = json.loads(completed.stdout.decode("utf-8"))
            row["sandbox"] = run_pdf_direct_trial(trial, delivery, preflight_only=True)
            row["source_sha256"] = source_before
            row["source_unchanged"] = _sha(delivery.pdf_path) == source_before
            source_pages = next((c["page_count"] for c in row["sandbox"]["sandbox_preflight"]["checks"]
                                 if c["name"] == "pdfinfo"), None)
            row["ok"] = (row["sandbox"]["ok"] and row["source_unchanged"] and
                         row["text_extraction"]["page_count"] == source_pages and row["text_extraction"]["character_count"] > 0)
            # Retain one readable PNG per sample for a human/agent visual spot check.
            renderer = shutil.which(config.card_generator.pdf_reader.pdftoppm_executable)
            subprocess.run([renderer, "-f", "1", "-l", "1", "-singlefile", "-r", "100", "-png",
                            str(delivery.pdf_path), str(root / key)], capture_output=True, check=True,
                           timeout=config.card_generator.pdf_reader.tool_timeout_seconds,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            row["preview_path"] = str(root / (key + ".png"))
            row["source_unchanged"] = _sha(delivery.pdf_path) == source_before
            row["ok"] = row["ok"] and row["source_unchanged"]
        except Exception as exc:
            row.update(ok=False, error={"code": getattr(exc, "code", "DEPLOYMENT_PROBE_FAILED"),
                       "message": "本机验证失败；未调用模型，未输出论文正文或原始进程日志", "type": type(exc).__name__})
    report["original_runtime_and_knowledge_unchanged"] = before == _protected(config)
    report["protected_file_count"] = len(before)
    report["ok"] = bool(report["items"]) and all(i["ok"] for i in report["items"]) and report["original_runtime_and_knowledge_unchanged"]
    atomic_text(root / "verification.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="使用新项目环境验证指定 PDF；不调用模型、不修改总配置")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config/config.json"))
    parser.add_argument("--item-key", action="append", required=True)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = verify(load_config(args.config, require_group=True), args.item_key)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
