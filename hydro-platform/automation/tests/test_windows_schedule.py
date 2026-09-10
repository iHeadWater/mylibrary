from __future__ import annotations

import base64
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.config import ConfigError, load_config
from hydro_platform.cli import main
from hydro_platform.windows_schedule import (ScheduleError, task_xml, comparable, ownership, native_call, manage_schedule)
from test_config import write_config


class WindowsScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scheduler 中文 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = write_config(self.root)
        config = load_config(self.path)
        self.config = replace(config, scheduler=replace(config.scheduler, enabled=True))
        for file in (self.config.deployment.environment_dir / "Scripts/pythonw.exe", self.root / "automation/scheduled_run.py"):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("fixture")
        self.xml = task_xml(self.config, "S-1-5-21-test")
        self.current = {"ok": True, "exists": True, "user_sid": "S-1-5-21-test", "state": "Ready",
                        "description": ownership(self.config), "xml": self.xml}

    def test_xml_is_least_privilege_windowless_catchup_and_exclusive(self):
        for token in ("InteractiveToken", "LeastPrivilege", "IgnoreNew", "LogonTrigger", "09:00:00",
                      "pythonw.exe", "StartWhenAvailable", "PT30M", "P1D"):
            self.assertIn(token, self.xml)
        self.assertNotIn("Password", self.xml)
        self.assertNotIn("HighestAvailable", self.xml)
        self.assertNotIn("Bypass", self.xml)

    def test_plan_does_not_register(self):
        backend = Mock(return_value={"ok": True, "exists": False, "user_sid": "S-1-5-21-test"})
        result = manage_schedule(self.config, "plan", backend=backend)
        self.assertTrue(result["ok"])
        backend.assert_called_once_with("query")

    def test_missing_status_is_not_reported_healthy(self):
        backend = Mock(return_value={"ok": True, "exists": False, "user_sid": "S-1-5-21-test"})
        result = manage_schedule(self.config, backend=backend)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "ABSENT")

    def test_matching_install_reuses_without_external_mutation(self):
        backend = Mock(return_value=self.current)
        self.assertTrue(manage_schedule(self.config, "install", backend=backend)["ok"])
        backend.assert_called_once_with("query")

    def test_install_reads_back_actual_definition(self):
        backend = Mock(side_effect=[{"ok": True, "exists": False, "user_sid": "S-1-5-21-test"}, self.current])
        self.assertTrue(manage_schedule(self.config, "install", backend=backend)["ok"])
        self.assertEqual(backend.call_args_list[1].args, ("install",))
        self.assertEqual(backend.call_args_list[1].kwargs["xml"], self.xml)

    def test_drift_detects_edited_command_and_trigger(self):
        for xml in (self.xml.replace("pythonw.exe", "another.exe"), self.xml.replace("09:00:00", "10:00:00")):
            backend = Mock(return_value=dict(self.current, xml=xml))
            result = manage_schedule(self.config, backend=backend)
            self.assertEqual(result["status"], "DRIFTED")
            self.assertFalse(result["ok"])

    def test_other_project_task_never_changed_or_deleted(self):
        for operation in ("install", "remove"):
            backend = Mock(return_value=dict(self.current, description="other project"))
            result = manage_schedule(self.config, operation, backend=backend)
            self.assertEqual(result["error"]["code"], "SCHEDULE_OWNERSHIP_CONFLICT")
            backend.assert_called_once_with("query")

    def test_remove_leaves_runtime_and_knowledge_alone(self):
        backend = Mock(side_effect=[self.current, {"ok": True, "exists": False}])
        result = manage_schedule(self.config, "remove", backend=backend)
        self.assertEqual(result["status"], "REMOVED")
        self.assertEqual(backend.call_args_list[1].args, ("remove",))

    def test_probe_definition_is_ondemand_and_no_model_branch(self):
        xml = task_xml(self.config, "SID", probe_token="a" * 32)
        self.assertIn("--probe-token", xml)
        self.assertNotIn("CalendarTrigger", xml)
        self.assertNotIn("LogonTrigger", xml)

    def test_config_rejects_unsafe_names_bad_times_and_unbounded_retries(self):
        original = json.loads(self.path.read_text())
        for values in ({"task_name": "Windows-task"}, {"task_name": "HydroPlatform-*"}, {"daily_time": "25:01"},
                       {"max_attempts_per_slot": 0}, {"retry_interval_minutes": -1}, {"enabled": "true"},
                       {"command_timeout_seconds": float("inf")}, {"unknown": 1}):
            self.path.write_text(json.dumps(dict(original, scheduler=values)))
            with self.subTest(values=values), self.assertRaises(ConfigError):
                load_config(self.path)

    def test_native_data_is_encoded_and_no_shell_bypass(self):
        completed = subprocess.CompletedProcess([], 0, b'{"ok":true,"exists":false}', b'')
        with patch("hydro_platform.windows_schedule.shutil.which", return_value="powershell"), \
             patch("hydro_platform.windows_schedule.subprocess.run", return_value=completed) as run:
            native_call(self.config, "query")
        argv = run.call_args.args[0]
        script = base64.b64decode(argv[-1]).decode("utf-16-le")
        self.assertNotIn("__REQUEST__", script)
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        self.assertNotIn("ExecutionPolicy", script)

    def test_timeout_is_uncertain_not_permission_to_restart(self):
        with patch("hydro_platform.windows_schedule.shutil.which", return_value="powershell"), \
             patch("hydro_platform.windows_schedule.subprocess.run", side_effect=subprocess.TimeoutExpired([], 1)):
            with self.assertRaises(ScheduleError) as exc:
                native_call(self.config, "install", xml=self.xml)
        self.assertEqual(exc.exception.code, "SCHEDULE_COMMAND_UNCERTAIN")

    def test_cli_routes_all_schedule_operations(self):
        for command in ("plan", "status", "install", "remove"):
            with patch("hydro_platform.cli.manage_schedule", return_value={"ok": True}) as manage, redirect_stdout(io.StringIO()):
                self.assertEqual(main(["schedule-" + command, "--config", str(self.path), "--json"]), 0)
            self.assertEqual(manage.call_args.args[1], command)

    def test_config_disable_changes_task_definition(self):
        off = replace(self.config, scheduler=replace(self.config.scheduler, enabled=False))
        self.assertNotEqual(comparable(task_xml(off, "S-1-5-21-test")), comparable(self.xml))

    def test_windows_export_equivalent_defaults_names_and_durations(self):
        exported = self.xml.replace("<RunLevel>LeastPrivilege</RunLevel>", "").replace("<Enabled>true</Enabled>", "")
        exported = exported.replace("<StopAtDurationEnd>false</StopAtDurationEnd>", "").replace("PT120S", "PT2M")
        exported = exported.replace("<RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>", "")
        exported = exported.replace("<AllowStartOnDemand>true</AllowStartOnDemand>", "").replace("<WakeToRun>false</WakeToRun>", "")
        exported = exported.replace("S-1-5-21-test", "HOST\\operator")
        self.assertEqual(comparable(exported, user_sid="S-1-5-21-test", user_name="HOST\\operator"), comparable(self.xml))
        self.assertNotEqual(comparable(exported, user_sid="S-1-5-21-test", user_name="HOST\\someone"), comparable(self.xml))
        self.assertNotEqual(comparable(self.xml.replace("LeastPrivilege", "HighestAvailable")), comparable(self.xml))

    def test_demand_only_probe_allows_null_next_run_time(self):
        from hydro_platform.windows_schedule import PS_BRIDGE
        self.assertIn("if ($info.NextRunTime)", PS_BRIDGE)


if __name__ == "__main__":
    unittest.main()
