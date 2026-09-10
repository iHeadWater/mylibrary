"""Fresh native download/install + real PDFs with the old tool PATH removed. No models."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hydro_platform.config import load_config
from hydro_platform.native_deployment import bootstrap_native
from hydro_platform.publication import atomic_text
from verify_deployment import verify as verify_pdfs
from verify_runtime_recovery import _protected, _sha


def verify(config, keys, *, reuse_installed=False):
    before = _protected(config)
    old_tools = {str(path): _sha(path) for name in ("pdfinfo_executable", "pdftoppm_executable", "pdftotext_executable")
                 if (path := Path(getattr(config.card_generator.pdf_reader, name))).is_file()}
    trials = config.paths.runtime_dir / "native-trials"
    trials.mkdir(parents=True, exist_ok=True)
    # Match a normal project installation's inherited ACL. On Windows Python 3.14,
    # mkdtemp's private 0700 directory denies the separate Codex sandbox identity
    # execution even when every downloaded binary is valid. Do not weaken an
    # existing private directory or grant permissions to unrelated paths.
    root = (trials / ("native-check-" + uuid.uuid4().hex)).resolve()
    if root.parent != trials.resolve():
        raise ValueError("native trial escaped runtime")
    root.mkdir(exist_ok=False)
    # Both empty paths make this a real downloader/installer test, not a copy from the Codex bundle.
    isolated = config if reuse_installed else replace(config, deployment=replace(config.deployment,
        native_tools_dir=root / "poppler", native_cache_dir=root / "download"))
    report = {"schema_version": 1, "operation": "verify_native_deployment", "ok": False,
        "model_call_count": 0, "trial_root": str(root), "report_path": str(root / "verification.json"),
        "fresh_download_requested": not reuse_installed,
        "scope": ("同机现有项目原生工具校验" if reuse_installed else "同机全新原生工具/缓存下载安装")
                 + "、隔离PATH与真实PDF沙箱验证；非干净新机或模型质量验收"}
    first = bootstrap_native(isolated, verify=True) if reuse_installed else bootstrap_native(isolated, install=True)
    report["installation"] = first
    if first["ok"]:
        second = bootstrap_native(isolated, install=True)
        report["repeated_install"] = second
        tools = first["tools"]
        cg = config.card_generator
        trial = replace(isolated, card_generator=replace(cg, executable=shutil.which(cg.executable),
            pdf_reader=replace(cg.pdf_reader, **{name + "_executable": path for name, path in tools.items()}),
            pdf_direct_trial=replace(cg.pdf_direct_trial, shell_executable=shutil.which(cg.pdf_direct_trial.shell_executable))))
        # Existing base software and login are deliberately retained; old native/DLL directories are not.
        system_root = Path(os.environ["SystemRoot"])
        path_value = os.pathsep.join((str(Path(tools["pdfinfo"]).parent), str(system_root / "System32"),
                                     str(system_root), str(Path(sys.executable).parent)))
        with patch.dict(os.environ, {"PATH": path_value}), \
             patch("hydro_platform.card_generators.codex_local_pdf.CodexLocalPdfAdapter.generate",
                   side_effect=AssertionError("no models in deployment drill")), \
             patch("hydro_platform.card_generators.codex_text.CodexTextAdapter.generate",
                   side_effect=AssertionError("no models in deployment drill")):
            report["pdf_verification"] = verify_pdfs(trial, keys)
        report["old_native_path_removed_for_pdf_probe"] = True
        report["ok"] = second["ok"] and second["status"] == "REUSED" and report["pdf_verification"]["ok"]
    report["original_runtime_and_knowledge_unchanged"] = before == _protected(config)
    report["protected_file_count"] = len(before)
    report["original_tools_unchanged"] = all(Path(p).is_file() and _sha(Path(p)) == value for p, value in old_tools.items())
    report["ok"] = report["ok"] and report["original_runtime_and_knowledge_unchanged"] and report["original_tools_unchanged"]
    atomic_text(root / "verification.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="全新下载/安装原生工具，并用真实PDF做无模型验证")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config/config.json"))
    parser.add_argument("--item-key", action="append", required=True)
    parser.add_argument("--reuse-installed", action="store_true", help="只核对已有项目工具，不再下载或解压")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = verify(load_config(args.config, require_group=True), args.item_key, reuse_installed=args.reuse_installed)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
