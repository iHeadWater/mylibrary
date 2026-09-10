from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.config import ConfigError, ZoteroConfig, ZoteroStartupConfig, load_config
from hydro_platform.zotero import ZoteroClient, preflight
from hydro_platform.zotero_readiness import (
    ensure_zotero_ready, launch_zotero, resolve_startup_executable, ZoteroStartupError,
)
from test_config import write_config
from test_preflight import ZoteroServer


def failure(code):
    return {"ok": False, "error": {"code": code, "message": "fixture"}}


class Clock:
    def __init__(self):
        self.value = 0
    def now(self):
        return self.value
    def sleep(self, seconds):
        self.value += seconds


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.settings = ZoteroStartupConfig(enabled=True, wait_timeout_seconds=12, poll_interval_seconds=3)
        self.config = ZoteroConfig(group_id=42, startup=self.settings)
        self.clock = Clock()
        self.probe = Mock(return_value={"ok": True, "group_id": 42})
        self.process = Mock(pid=1234)
        self.process.poll.return_value = None
        self.launch = Mock(return_value=self.process)
        self.events = []

    def run_readiness(self, **kw):
        return ensure_zotero_ready(self.config, probe=self.probe, launcher=self.launch,
            clock=self.clock.now, sleep=self.clock.sleep, progress=self.events.append, **kw)

    def test_already_ready_no_launch_no_sleep(self):
        result = self.run_readiness()
        self.assertTrue(result["ok"])
        self.launch.assert_not_called()
        self.assertEqual(result["startup"]["poll_count"], 1)
        self.assertEqual(self.clock.value, 0)
        self.assertIn("不证明云端同步完成", result["startup"]["note"])

    def test_disabled_preserves_one_shot_preflight(self):
        self.config = replace(self.config, startup=replace(self.settings, enabled=False))
        self.probe.return_value = failure("ZOTERO_NOT_RUNNING")
        result = self.run_readiness()
        self.assertEqual(result, self.probe.return_value)
        self.probe.assert_called_once_with(self.config)
        self.launch.assert_not_called()

    def test_missing_launches_once_then_waits_for_group(self):
        self.probe.side_effect = [failure("ZOTERO_NOT_RUNNING"), failure("ZOTERO_NOT_RUNNING"),
                                 failure("LOCAL_API_UNAVAILABLE"), {"ok": True}]
        result = self.run_readiness()
        self.assertTrue(result["ok"])
        self.launch.assert_called_once_with(self.settings)
        self.assertEqual(result["startup"]["launched_pid"], 1234)
        self.assertEqual(self.clock.value, 9)
        self.assertTrue(self.events)

    def test_running_api_not_ready_does_not_launch_another(self):
        self.probe.side_effect = [failure("LOCAL_API_UNAVAILABLE"), failure("GROUP_NOT_AVAILABLE"), {"ok": True}]
        self.assertTrue(self.run_readiness()["ok"])
        self.launch.assert_not_called()

    def test_launch_can_be_disabled_but_wait_is_retained(self):
        self.config = replace(self.config, startup=replace(self.settings, launch_if_missing=False))
        self.probe.side_effect = [failure("ZOTERO_NOT_RUNNING"), {"ok": True}]
        self.assertTrue(self.run_readiness()["ok"])
        self.launch.assert_not_called()

    def test_timeout_has_cause_and_finite_budget(self):
        self.probe.return_value = failure("LOCAL_API_UNAVAILABLE")
        result = self.run_readiness()
        self.assertEqual(result["error"]["code"], "ZOTERO_READY_TIMEOUT")
        self.assertEqual(result["error"]["cause_code"], "LOCAL_API_UNAVAILABLE")
        self.assertEqual(self.clock.value, 12)
        self.assertEqual(self.probe.call_count, 4)
        self.launch.assert_not_called()

    def test_run_budget_bounds_readiness_and_each_probe(self):
        self.probe.return_value = failure("LOCAL_API_UNAVAILABLE")
        result = self.run_readiness(wait_budget=4)
        self.assertFalse(result["ok"])
        self.assertEqual(self.clock.value, 4)
        self.assertLessEqual(self.probe.call_args.args[0].timeout_seconds, 1 / 3)
        self.assertLessEqual(self.probe.call_args.args[0].process_timeout_seconds, 1 / 3)

    def test_zero_remaining_budget_does_not_launch_or_probe(self):
        self.assertFalse(self.run_readiness(wait_budget=0)["ok"])
        self.launch.assert_not_called()
        self.probe.assert_not_called()

    def test_slow_probe_does_not_add_sleep_after_budget(self):
        def slow(_):
            self.clock.value += 12
            return failure("LOCAL_API_UNAVAILABLE")
        self.probe.side_effect = slow
        self.assertFalse(self.run_readiness()["ok"])
        self.assertEqual(self.clock.value, 12)
        self.probe.assert_called_once()

    def test_exhausted_probe_budget_cannot_launch_a_late_app(self):
        def slow(_):
            self.clock.value += 12
            return failure("ZOTERO_NOT_RUNNING")
        self.probe.side_effect = slow
        self.assertFalse(self.run_readiness()["ok"])
        self.launch.assert_not_called()

    def test_permission_and_invalid_api_do_not_retry(self):
        for code in ("GROUP_PERMISSION_DENIED", "INVALID_API_RESPONSE", "ZOTERO_HTTP_ERROR"):
            with self.subTest(code=code):
                self.probe.reset_mock()
                self.probe.return_value = failure(code)
                result = self.run_readiness()
                self.assertEqual(result["error"]["code"], code)
                self.probe.assert_called_once()
        self.launch.assert_not_called()

    def test_launch_failure_is_explicit_no_retry(self):
        self.probe.return_value = failure("ZOTERO_NOT_RUNNING")
        self.launch.side_effect = ZoteroStartupError("ZOTERO_EXECUTABLE_NOT_FOUND", "missing")
        self.assertEqual(self.run_readiness()["error"]["code"], "ZOTERO_EXECUTABLE_NOT_FOUND")
        self.launch.assert_called_once()

    def test_launcher_exit_does_not_mean_zotero_handoff_failed(self):
        self.process.poll.return_value = 0
        self.probe.side_effect = [failure("ZOTERO_NOT_RUNNING"), failure("LOCAL_API_UNAVAILABLE"), {"ok": True}]
        result = self.run_readiness()
        self.assertTrue(result["ok"])
        self.launch.assert_called_once()
        self.process.terminate.assert_not_called()
        self.process.kill.assert_not_called()

    def test_actual_local_http_group_becomes_visible_without_library_writes(self):
        routes = {"/api/users/0/groups": (200, [], {}),
                  "/api/groups/42/items/top?limit=1": (200, [], {"Total-Results": "0"})}
        with ZoteroServer(routes) as server:
            config = replace(self.config, base_url=server.base_url)
            def after_poll(seconds):
                self.clock.sleep(seconds)
                routes["/api/users/0/groups"] = (200, [{"id": 42, "name": "fixture"}], {})
            result = ensure_zotero_ready(config, probe=lambda cfg: preflight(cfg, process_checker=lambda: True),
                launcher=self.launch, clock=self.clock.now, sleep=after_poll)
        self.assertTrue(result["ok"])
        self.assertEqual(result["startup"]["poll_count"], 2)
        self.launch.assert_not_called()

    def test_windows_launch_is_argument_list_hidden_no_shell_or_profile_options(self):
        with patch("hydro_platform.zotero_readiness.resolve_startup_executable", return_value=r"C:\Program Files\Zotero\zotero.exe"), \
             patch("hydro_platform.zotero_readiness.subprocess.Popen", return_value=self.process) as popen:
            self.assertIs(launch_zotero(self.settings), self.process)
        self.assertEqual(popen.call_args.args[0], [r"C:\Program Files\Zotero\zotero.exe"])
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertEqual(popen.call_args.kwargs["startupinfo"].wShowWindow, subprocess.SW_HIDE)
        self.assertEqual(popen.call_args.kwargs["stdout"], subprocess.DEVNULL)

    def test_windows_launch_error_has_no_raw_secret_text(self):
        with patch("hydro_platform.zotero_readiness.resolve_startup_executable", return_value="zotero.exe"), \
             patch("hydro_platform.zotero_readiness.subprocess.Popen", side_effect=OSError("secret fixture")):
            with self.assertRaises(ZoteroStartupError) as caught:
                launch_zotero(self.settings)
        self.assertNotIn("secret fixture", str(caught.exception))

    def test_resolver_does_not_fallback_from_explicit_bad_path(self):
        with patch("hydro_platform.zotero_readiness.platform.system", return_value="Windows"):
            for value in ("missing-zotero.exe", "https://example.test/zotero.exe", "zotero.exe --other-profile"):
                with self.subTest(value=value), self.assertRaises(ZoteroStartupError):
                    resolve_startup_executable(replace(self.settings, executable=value))

    def test_explicit_executable_is_resolved_but_scripts_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "zotero.exe"
            exe.write_bytes(b"fixture, not executed")
            script = root / "zotero.cmd"
            script.write_text("fixture, not executed")
            with patch("hydro_platform.zotero_readiness.platform.system", return_value="Windows"):
                self.assertEqual(resolve_startup_executable(replace(self.settings, executable=str(exe))), str(exe.resolve()))
                with self.assertRaises(ZoteroStartupError):
                    resolve_startup_executable(replace(self.settings, executable=str(script)))

    def test_config_rejects_unbounded_wait_typos_and_string_switches(self):
        for override in ({"enabled": "true"}, {"launch_if_missing": 1}, {"oops": 1},
                         {"wait_timeout_seconds": float("inf")}, {"wait_timeout_seconds": 601},
                         {"poll_interval_seconds": float("nan")}, {"poll_interval_seconds": 31},
                         {"wait_timeout_seconds": True}, {"poll_interval_seconds": 0},
                         {"wait_timeout_seconds": 1, "poll_interval_seconds": 5}):
            with self.subTest(override=override), tempfile.TemporaryDirectory() as directory:
                path = write_config(Path(directory))
                data = json.loads(path.read_text())
                data["zotero"]["startup"] = override
                path.write_text(json.dumps(data))
                with self.assertRaises(ConfigError):
                    load_config(path)

    def test_relative_config_path_is_project_relative(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_config(root)
            data = json.loads(path.read_text())
            data["zotero"]["startup"] = {"executable": "tools/zotero.exe"}
            path.write_text(json.dumps(data))
            self.assertEqual(load_config(path).zotero.startup.executable, str((root / "tools/zotero.exe").resolve()))


if __name__ == "__main__":
    unittest.main()
