from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydrolitagent.cards.config import load_config
from hydrolitagent.cards.pdf_sandbox import PROBE_SCRIPT, build_sandbox_probe_command, check_pdf_sandbox
from test_config import write_config


class SandboxPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = load_config(write_config(self.root))
        self.workspace = self.root / "work"
        self.workspace.mkdir()
        self.source = self.root / "中文 ' 引号 $ 论文.pdf"
        self.tools = {n: str(self.root / (n + ".exe")) for n in ("pdfinfo", "pdftotext", "pdftoppm")}
        self.args = ("codex", self.config, self.workspace, self.source, self.tools, 16, "a" * 64)
        self.kwargs = {"shell": "powershell", "python": "python"}
        self.checks = [{"name": n, "status": "pass"} for n in ("source_read", "pdfinfo", "text_extract", "page_render")]

    def test_command_preserves_paths_as_data_and_keeps_native_sandbox(self):
        command = build_sandbox_probe_command(*self.args, **self.kwargs)
        self.assertEqual(command[:4], ["codex", "sandbox", "-P", ":workspace"])
        self.assertIn("--include-managed-config", command)
        self.assertIn('windows.sandbox="elevated"', command)
        self.assertIn("-NoProfile", command)
        self.assertNotIn("exec", command)
        self.assertNotIn("--ignore-rules", command)
        self.assertNotIn("danger-full-access", " ".join(command))
        wrapper = base64.b64decode(command[-1]).decode("utf-16-le")
        self.assertNotIn(str(self.source), wrapper)
        self.assertNotIn('"source":', wrapper)
        self.assertIn("base64.b64decode", wrapper)
        self.assertIn("exit $LASTEXITCODE", wrapper)

    def test_probe_script_is_valid_python(self):
        compile(PROBE_SCRIPT, "probe", "exec")

    def test_success_requires_every_check_and_no_model_call(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps({"ok": True, "checks": self.checks}), ""))
        result = check_pdf_sandbox(*self.args, **self.kwargs, runner=runner)
        self.assertTrue(result["ok"])
        self.assertFalse(result["model_invoked"])
        self.assertEqual(runner.call_args.args[1], "")
        self.assertEqual(runner.call_args.args[2], 120)
        self.assertEqual(runner.call_args.args[0][1], "sandbox")

    def test_partial_or_invalid_probe_never_passes(self):
        for output in ("bad-json", "{}", json.dumps({"ok": True, "checks": self.checks[:2]}),
                       json.dumps({"ok": False, "checks": self.checks})):
            with self.subTest(output=output):
                runner = Mock(return_value=subprocess.CompletedProcess([], 0, output, ""))
                self.assertFalse(check_pdf_sandbox(*self.args, **self.kwargs, runner=runner)["ok"])

    def test_tool_error_keeps_step_and_safe_diagnostic(self):
        payload = {"ok": False, "checks": self.checks[:2], "failure_type": "RuntimeError",
                   "failure_reason": "local_pdf_tool_failed:pdftotext:exit=1"}
        runner = Mock(return_value=subprocess.CompletedProcess([], 3, json.dumps(payload), "ERROR Please finish the setup before proceeding."))
        result = check_pdf_sandbox(*self.args, **self.kwargs, runner=runner)
        self.assertFalse(result["ok"])
        self.assertEqual(result["diagnostic"]["probe_failure"]["failure_reason"], payload["failure_reason"])
        self.assertIn("finish the setup", result["diagnostic"]["summary"])

    def test_timeout_and_spawn_error_do_not_retry(self):
        for error in (subprocess.TimeoutExpired("sandbox", 1), OSError("private-path")):
            with self.subTest(error=type(error).__name__):
                runner = Mock(side_effect=error)
                result = check_pdf_sandbox(*self.args, **self.kwargs, runner=runner)
                self.assertFalse(result["ok"])
                self.assertNotIn("private-path", json.dumps(result))
                runner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
