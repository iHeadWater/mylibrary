from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.cli import main
from hydro_platform.config import PdfDirectTrialConfig, load_config
from hydro_platform.doctor import _python_probe, doctor
from test_card_generation import GenerationFixture
from test_config import write_config


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = GenerationFixture(self.root)
        self.path = write_config(self.root)
        config = load_config(self.path)
        config.deployment.dependency_lock_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).resolve().parents[1] / "setup/dependencies.lock.json",
                        config.deployment.dependency_lock_file)
        self.config = replace(config,
            card_generator=replace(config.card_generator, workflow_mode="single_agent",
                pdf_reader=replace(config.card_generator.pdf_reader, adapter="local_path")),
            paths=replace(config.paths, evidence_card_generation_prompt_file=self.f.prompt))
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("hydro_platform.doctor.preflight", return_value={"ok": True}))
        self.provider = Mock()
        self.provider.preflight.return_value = {"ok": True}
        self.provider.generate.side_effect = AssertionError("No models")
        self.provider.smoke_test.side_effect = AssertionError("No models")
        self.stack.enter_context(patch("hydro_platform.doctor.build_card_generator_adapter", return_value=self.provider))

    def files(self):
        return {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def test_checks_are_read_only_and_never_invoke_model(self):
        before = self.files()
        with patch("hydro_platform.doctor._python_probe", return_value={"ok": True}):
            result = doctor(self.config)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["checks"]), 8)
        self.assertEqual(before, self.files())
        self.provider.generate.assert_not_called()
        self.provider.smoke_test.assert_not_called()

    def test_bad_assets_and_provider_failure_are_both_reported(self):
        self.provider.preflight.return_value = {"ok": False, "error": {"code": "CLI_MISSING"}}
        self.config = replace(self.config, paths=replace(self.config.paths, evidence_card_generation_prompt_file=self.root / "missing"))
        with patch("hydro_platform.doctor._python_probe", return_value={"ok": True}):
            result = doctor(self.config)
        failed = [row["name"] for row in result["checks"] if row["status"] == "fail"]
        self.assertEqual(failed, ["generation_assets", "codex_and_pdf_tools"])
        self.assertFalse(result["ok"])

    def test_missing_runtime_is_healthy_without_creating_it(self):
        paths = replace(self.config.paths, tasks_file=self.root / "new" / "tasks.json", snapshot_file=self.root / "new" / "snapshot.json")
        with patch("hydro_platform.doctor._python_probe", return_value={"ok": True}):
            result = doctor(replace(self.config, paths=paths))
        self.assertTrue(result["ok"], result)
        self.assertFalse((self.root / "new").exists())

    def probe_config(self):
        direct = PdfDirectTrialConfig(prompt_file=self.f.prompt, schema_file=self.f.schema,
                                      timeout_seconds=120, text_extractor="pypdf", python_executable="configured-python")
        return replace(self.config, card_generator=replace(self.config.card_generator, pdf_direct_trial=direct))

    def test_python_probe_uses_configured_interpreter_and_fixed_script(self):
        completed = subprocess.CompletedProcess([], 0, b'{"python":[3,12,14],"pypdf":"6.18.0"}', b'')
        with patch("hydro_platform.doctor.shutil.which", return_value="configured-python") as find, \
             patch("hydro_platform.doctor.subprocess.run", return_value=completed) as run:
            result = _python_probe(self.probe_config())
        self.assertTrue(result["ok"], result)
        find.assert_called_once_with("configured-python")
        self.assertEqual(run.call_args.args[0][:3], ["configured-python", "-B", "-c"])

    def test_failed_probe_does_not_expose_stderr(self):
        completed = subprocess.CompletedProcess([], 1, b'', b'credential-like-secret')
        with patch("hydro_platform.doctor.shutil.which", return_value="python"), \
             patch("hydro_platform.doctor.subprocess.run", return_value=completed):
            result = _python_probe(self.probe_config())
        self.assertFalse(result["ok"])
        self.assertNotIn("credential-like-secret", json.dumps(result))

    def test_dependency_version_drift_is_warning_not_installation(self):
        completed = subprocess.CompletedProcess([], 0, b'{"python":[3,12,14],"pypdf":"6.9.0"}', b'')
        with patch("hydro_platform.doctor.shutil.which", return_value="python"), \
             patch("hydro_platform.doctor.subprocess.run", return_value=completed):
            result = _python_probe(self.probe_config())
        self.assertTrue(result["ok"])
        self.assertIn("warning", result)

    def test_enabled_reporting_checks_ledger_without_creating_it(self):
        config = replace(self.config, activity_reporting=replace(self.config.activity_reporting, enabled=True))
        with patch("hydro_platform.doctor._python_probe", return_value={"ok": True}):
            result = doctor(config)
        self.assertTrue(result["ok"], result)
        activity = next(row for row in result["checks"] if row["name"] == "activity_records")
        self.assertFalse(activity["result"]["ledger_initialized"])
        self.assertFalse(config.paths.activity_dir.exists())

    def test_cli_failure_is_json_and_exit_three(self):
        with patch("hydro_platform.cli.doctor", return_value={"ok": False}) as check, redirect_stdout(io.StringIO()) as out:
            code = main(["doctor", "--config", str(self.path), "--json"])
        self.assertEqual(code, 3)
        self.assertFalse(json.loads(out.getvalue())["ok"])
        check.assert_called_once()

    def test_enabled_scheduler_is_checked_but_not_installed_or_run(self):
        config = replace(self.config, scheduler=replace(self.config.scheduler, enabled=True))
        with patch("hydro_platform.doctor._python_probe", return_value={"ok": True}), \
             patch("hydro_platform.doctor.manage_schedule", return_value={"ok": False, "status": "ABSENT"}) as schedule:
            result = doctor(config)
        self.assertFalse(result["ok"])
        schedule.assert_called_once_with(config, "status")
        self.assertEqual(result["checks"][-1]["name"], "windows_schedule")

    def test_startup_check_is_path_only_and_cannot_launch_zotero(self):
        config = replace(self.config, zotero=replace(self.config.zotero,
            startup=replace(self.config.zotero.startup, enabled=True)))
        with patch("hydro_platform.doctor._python_probe", return_value={"ok": True}), \
             patch("hydro_platform.doctor.resolve_startup_executable", return_value="zotero.exe") as resolve, \
             patch("hydro_platform.zotero_readiness.launch_zotero") as launch:
            result = doctor(config)
        self.assertTrue(result["ok"])
        resolve.assert_called_once_with(config.zotero.startup)
        launch.assert_not_called()
        self.assertEqual(len(result["checks"]), 9)

    def test_selected_native_tools_are_verified_not_installed(self):
        config = replace(self.config, card_generator=replace(self.config.card_generator,
            pdf_reader=replace(self.config.card_generator.pdf_reader,
                pdfinfo_executable=str(self.config.deployment.native_tools_dir / "Library/bin/pdfinfo.exe"))))
        before = self.files()
        with patch("hydro_platform.doctor._python_probe", return_value={"ok": True}), \
             patch("hydro_platform.doctor.bootstrap_native", return_value={"ok": False,
                "error": {"code": "NATIVE_NOT_INSTALLED"}}) as native:
            result = doctor(config)
        self.assertFalse(result["ok"])
        native.assert_called_once_with(config, verify=True)
        self.assertEqual(before, self.files())
        self.assertEqual(result["checks"][-1]["name"], "native_pdf_tools")

    def test_external_native_tools_do_not_trigger_project_install(self):
        with patch("hydro_platform.doctor._python_probe", return_value={"ok": True}), \
             patch("hydro_platform.doctor.bootstrap_native") as native:
            doctor(self.config)
        native.assert_not_called()


if __name__ == "__main__":
    unittest.main()
