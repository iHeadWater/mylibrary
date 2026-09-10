from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

AUTOMATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION))
sys.path.insert(0, str(AUTOMATION / "src"))
from verify_setup import copy_shared, verify, _run_json
from hydro_platform.config import load_config
from test_config import write_config


class SetupVerifierTests(unittest.TestCase):
    def test_helpers_import_in_isolated_python_from_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as cwd:
            for script in ("verify_setup.py", "verify_deployment.py", "verify_native_deployment.py", "verify_zotero_readiness.py"):
                with self.subTest(script=script):
                    result = subprocess.run([sys.executable, "-I", str(AUTOMATION / script), "--help"],
                        cwd=cwd, capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))

    def test_copy_excludes_runtime_credentials_and_original_pdfs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            for name in ("automation/run.py", "automation/.env", "automation/__pycache__/a.pyc",
                         "config/config.local.json", "evidence-packs/EV-A/card.md", "evidence-packs/EV-A/paper.pdf",
                         ".runtime/tasks.json", ".venv/private.txt", ".tools/pdfinfo.exe"):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture")
            target = root / "copy"
            copy_shared(source, target)
            self.assertEqual(sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()),
                ["automation/run.py", "evidence-packs/EV-A/card.md"])

    def test_unknown_resume_owner_never_replaces_report(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(write_config(Path(directory)))
            root = config.paths.runtime_dir / "setup-trials" / "unknown"
            root.mkdir(parents=True)
            (root / "owner.json").write_text('{}')
            (root / "verification.json").write_text('personal')
            with self.assertRaises(ValueError):
                verify(config, resume=root)
            self.assertEqual((root / "verification.json").read_text(), "personal")
            self.assertEqual(len(list(root.iterdir())), 2)

    def test_utf8_json_child_output_from_windows_process(self):
        code = "import sys,json;sys.stdout.reconfigure(encoding='utf-8');print(json.dumps({'ok':True,'内容':'主题'},ensure_ascii=False))"
        result = _run_json([sys.executable, "-I", "-c", code], cwd=AUTOMATION, timeout=20)
        self.assertEqual(result["内容"], "主题")


if __name__ == "__main__":
    unittest.main()
