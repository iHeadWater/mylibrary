from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.cli import main
from hydro_platform.config import load_config, PdfDirectTrialConfig
from hydro_platform.workstation_setup import setup_workstation
from hydro_platform.tasks import PipelineRunLock
from test_config import write_config


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = write_config(self.root)
        config = load_config(self.path)
        direct = PdfDirectTrialConfig(prompt_file=self.root / "p.md", schema_file=self.root / "s.json", timeout_seconds=120,
            python_executable=str(config.deployment.environment_dir / "Scripts/python.exe"))
        self.config = replace(config, scheduler=replace(config.scheduler, enabled=True),
            card_generator=replace(config.card_generator, workflow_mode="single_agent", pdf_direct_trial=direct,
                pdf_reader=replace(config.card_generator.pdf_reader, adapter="local_path", **{
                    name + "_executable": str(config.deployment.native_tools_dir / "Library/bin" / (name + ".exe"))
                    for name in ("pdfinfo", "pdftotext", "pdftoppm")})))
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.mocks = {}
        for name in ("bootstrap", "bootstrap_native", "preflight", "ensure_zotero_ready", "doctor", "recover_runtime", "manage_schedule"):
            self.mocks[name] = stack.enter_context(patch("hydro_platform.workstation_setup." + name,
                return_value={"ok": True, "status": "REUSED", "checks": [], "counts": {"COMPLETED": 3}}))
        self.provider = Mock()
        self.provider.preflight.return_value = {"ok": True}
        self.provider.generate.side_effect = AssertionError("no model")
        stack.enter_context(patch("hydro_platform.workstation_setup.CodexCliAdapter", return_value=self.provider))

    def files(self):
        return {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_plan_never_installs_recovers_launches_or_registers(self):
        before = self.files()
        result = setup_workstation(self.config)
        self.assertEqual(result["status"], "PLAN", result)
        self.assertEqual(before, self.files())
        self.mocks["bootstrap"].assert_called_once_with(self.config)
        self.mocks["bootstrap_native"].assert_called_once_with(self.config)
        for name in ("ensure_zotero_ready", "doctor", "recover_runtime", "manage_schedule"):
            self.mocks[name].assert_not_called()
        self.provider.preflight.assert_called_once_with(check_pdf_reader=False)

    def test_apply_order_and_final_scheduled_readiness(self):
        events = []
        result = setup_workstation(self.config, apply=True, progress=events.append)
        self.assertEqual(result["status"], "READY_SCHEDULED", result)
        self.assertEqual([s["name"] for s in result["steps"]], ["configuration_bindings", "python_plan", "native_plan",
            "codex_login", "zotero_ready", "python_install", "native_install", "environment_check",
            "runtime_recovery", "schedule_install", "final_check"])
        self.assertFalse(self.mocks["doctor"].call_args_list[0].args[0].scheduler.enabled)
        self.assertTrue(self.mocks["doctor"].call_args_list[1].args[0].scheduler.enabled)
        self.mocks["manage_schedule"].assert_called_once_with(self.config, "install")
        self.assertEqual(result["model_call_count"], 0)
        self.assertEqual(len(events), 22)
        self.assertTrue(Path(result["report_path"]).is_file())
        self.provider.generate.assert_not_called()

    def test_configuration_mismatch_stops_before_any_probe_or_install(self):
        config = replace(self.config, card_generator=replace(self.config.card_generator,
            pdf_reader=replace(self.config.card_generator.pdf_reader, pdfinfo_executable="wrong")))
        result = setup_workstation(config, apply=True)
        self.assertEqual(result["error"]["code"], "SETUP_READER_BINDING_MISMATCH")
        self.mocks["bootstrap"].assert_not_called()
        self.mocks["manage_schedule"].assert_not_called()

    def test_missing_login_stops_before_install(self):
        self.provider.preflight.return_value = {"ok": False, "error": {"code": "LOGIN_REQUIRED"}}
        result = setup_workstation(self.config, apply=True)
        self.assertEqual(result["failed_step"], "codex_login")
        self.assertEqual(self.mocks["bootstrap"].call_count, 1)
        self.mocks["ensure_zotero_ready"].assert_not_called()

    def test_zotero_not_ready_keeps_completed_probes_and_stops(self):
        self.mocks["ensure_zotero_ready"].return_value = {"ok": False, "error": {"code": "ZOTERO_READY_TIMEOUT"}}
        result = setup_workstation(self.config, apply=True)
        self.assertEqual(result["failed_step"], "zotero_ready")
        self.assertEqual(self.mocks["bootstrap_native"].call_count, 1)
        self.mocks["recover_runtime"].assert_not_called()

    def test_python_install_failure_stops_native_install(self):
        self.mocks["bootstrap"].side_effect = [{"ok": True}, {"ok": False, "error": {"code": "BOOTSTRAP_TIMEOUT"}}]
        result = setup_workstation(self.config, apply=True)
        self.assertEqual(result["failed_step"], "python_install")
        self.assertEqual(self.mocks["bootstrap_native"].call_count, 1)
        self.mocks["doctor"].assert_not_called()

    def test_native_install_failure_does_not_recover_or_register(self):
        self.mocks["bootstrap_native"].side_effect = [{"ok": True}, {"ok": False, "error": {"code": "NATIVE_INSTALL_FAILED"}}]
        result = setup_workstation(self.config, apply=True)
        self.assertEqual(result["failed_step"], "native_install")
        self.mocks["recover_runtime"].assert_not_called()
        self.mocks["manage_schedule"].assert_not_called()

    def test_environment_failure_keeps_installations_and_stops_recovery(self):
        self.mocks["doctor"].return_value = {"ok": False, "checks": []}
        result = setup_workstation(self.config, apply=True)
        self.assertEqual(result["failed_step"], "environment_check")
        self.mocks["recover_runtime"].assert_not_called()

    def test_recovery_conflict_never_registers_schedule(self):
        self.mocks["recover_runtime"].return_value = {"ok": False, "error": {"code": "RECOVERY_CONFLICT"}}
        result = setup_workstation(self.config, apply=True)
        self.assertEqual(result["error"]["code"], "RECOVERY_CONFLICT")
        self.mocks["manage_schedule"].assert_not_called()

    def test_schedule_failure_preserves_recovered_state_in_report(self):
        self.mocks["manage_schedule"].return_value = {"ok": False, "error": {"code": "SCHEDULE_COMMAND_UNCERTAIN"}}
        result = setup_workstation(self.config, apply=True)
        self.assertEqual(result["failed_step"], "schedule_install")
        self.assertEqual(result["recovered_state_counts"], {"COMPLETED": 3})
        self.assertEqual(self.mocks["manage_schedule"].call_count, 1)

    def test_disabled_schedule_is_manual_not_automatic_success(self):
        result = setup_workstation(replace(self.config, scheduler=replace(self.config.scheduler, enabled=False)), apply=True)
        self.assertEqual(result["status"], "READY_MANUAL")
        self.mocks["manage_schedule"].assert_not_called()

    def test_concurrent_setup_does_not_start_install(self):
        lock = self.config.paths.lock_file.with_name(self.config.paths.lock_file.name + ".setup")
        with PipelineRunLock(lock):
            result = setup_workstation(self.config, apply=True)
        self.assertEqual(result["error"]["code"], "TASK_STORE_BUSY")
        self.mocks["bootstrap"].assert_not_called()

    def test_changed_config_stops_following_steps(self):
        def change(*args):
            self.path.write_text("changed", encoding="utf-8")
            return {"ok": True}
        self.mocks["bootstrap"].side_effect = change
        result = setup_workstation(self.config, apply=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_step"], "python_plan")
        self.mocks["bootstrap_native"].assert_not_called()

    def test_cancelled_install_and_log_failure_preserve_diagnostic(self):
        self.mocks["bootstrap"].side_effect = [{"ok": True}, KeyboardInterrupt()]
        with patch("hydro_platform.workstation_setup.atomic_text", side_effect=OSError("secret")):
            result = setup_workstation(self.config, apply=True)
        self.assertEqual(result["status"], "CANCELLED")
        self.assertIn("report_warning", result)
        self.assertNotIn("secret", json.dumps(result))

    def test_final_doctor_failure_not_ready(self):
        self.mocks["doctor"].side_effect = [{"ok": True, "checks": []}, {"ok": False, "checks": []}]
        result = setup_workstation(self.config, apply=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_step"], "final_check")

    def test_cli_apply_has_separate_progress_and_cancel_exit(self):
        response = {"ok": False, "status": "CANCELLED", "operation": "setup", "steps": []}
        with patch("hydro_platform.cli.setup_workstation", return_value=response) as setup, \
             redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            code = main(["setup", "--config", str(self.path), "--apply", "--json"])
        self.assertEqual(code, 130)
        self.assertTrue(setup.call_args.kwargs["apply"])
        self.assertEqual(json.loads(out.getvalue())["status"], "CANCELLED")
        self.assertNotIn("AI进度", err.getvalue())


if __name__ == "__main__":
    unittest.main()
