from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.cli import main
from hydrolitagent.cards.config import ConfigError, ProgressConfig, load_config
from hydrolitagent.cards.progress import ConsoleProgress
import test_config as config_fixtures

class ProgressTests(unittest.TestCase):
    def test_default_heartbeat_waits_sixty_seconds_without_delaying_events(self):
        stream = io.StringIO()
        progress = ConsoleProgress(stream=stream)
        self.assertEqual(progress.interval, 60)
        # Simulate the wait so the test itself does not spend 60 seconds idle.
        progress._stop = Mock()
        progress._stop.is_set.return_value = False
        progress._stop.wait.side_effect = [False, True]
        progress._heartbeat()
        self.assertEqual([call.args[0] for call in progress._stop.wait.call_args_list], [60, 60])
        self.assertEqual(stream.getvalue().count("等待中"), 1)
        progress({"event": "phase", "message": "正式卡片已保存"})
        self.assertIn("正式卡片已保存", stream.getvalue())

    def test_pipeline_partial_failure_is_not_misreported_as_last_card_save_failure(self):
        stream = io.StringIO()
        progress = ConsoleProgress(stream=stream)
        progress({"event": "workflow_completed"})
        progress.finish({"operation": "run_once", "ok": False, "status": "COMPLETED_WITH_BLOCKERS",
            "counts": {"completed": 1, "skipped": 3, "failed": 1, "deferred": 2},
            "items": [{"parent_key": "FAILED01", "status": "FAILED", "error": {"code": "CODEX_GENERATION_TIMEOUT"}},
                      {"parent_key": "COOLDOWN", "status": "DEFERRED", "reason_code": "RETRY_COOLDOWN"},
                      {"parent_key": "SUCCESS1", "status": "COMPLETED"}],
            "theme_pipeline": {"status": "DEFERRED"}, "report_path": "local-report.json"})
        output = stream.getvalue()
        self.assertIn("[整轮汇总] 本轮结束，仍有失败或阻塞", output)
        self.assertIn("本轮新完成 1", output)
        self.assertIn("未完成项 FAILED01：FAILED，CODEX_GENERATION_TIMEOUT", output)
        self.assertIn("延后 2", output)
        self.assertIn("主题流程暂缓", output)
        self.assertIn("运行报告：local-report.json", output)
        self.assertNotIn("未完成项 SUCCESS1", output)
        self.assertNotIn("失败，停在本阶段", output)

    def test_pipeline_pending_or_cancelled_never_claims_all_saved(self):
        for status in ("COMPLETED_WITH_PENDING", "CANCELLED", "ALREADY_RUNNING", "LOCAL_PREVIEW"):
            with self.subTest(status=status):
                stream = io.StringIO()
                ConsoleProgress(stream=stream).finish({"operation": "run_once", "ok": True, "status": status})
                self.assertIn("[整轮汇总]", stream.getvalue())
                self.assertNotIn("处理完成，结果已保存", stream.getvalue())

    def test_heartbeat_is_visible_before_finish_and_stops_afterwards(self):
        heartbeat = threading.Event()

        class Stream(io.StringIO):
            def write(self, value):
                result = super().write(value)
                if "等待中" in value:
                    heartbeat.set()
                return result

        stream = Stream()
        with ConsoleProgress(stream=stream, heartbeat_interval_seconds=0.01) as progress:
            progress({"event": "role_started", "role": "fact_extractor_a", "index": 1, "total": 6})
            self.assertTrue(heartbeat.wait(2))
            progress.finish({"ok": False, "error": {"code": "CARD_QUALITY_CONTRACT_FAILED"}})
        output = stream.getvalue()
        self.assertIn("1/6 事实提取 A", output)
        self.assertIn("距最近进展事件", output)
        self.assertIn("失败，停在本阶段", output)
        self.assertNotIn("%", output)
        self.assertFalse(progress._thread.is_alive())

    def test_disabled_progress_writes_nothing(self):
        stream = io.StringIO()
        with ConsoleProgress(enabled=False, stream=stream) as progress:
            progress({"event": "phase", "message": "hidden"})
            progress.finish({"ok": True})
        self.assertEqual(stream.getvalue(), "")
        self.assertIsNone(progress._thread)

    def test_broken_terminal_does_not_fail_generation(self):
        stream = Mock()
        stream.write.side_effect = BrokenPipeError()
        with ConsoleProgress(stream=stream) as progress:
            progress.finish({"ok": True})
        self.assertFalse(progress.enabled)

    def test_exception_stops_heartbeat_and_reports_abort(self):
        stream = io.StringIO()
        with self.assertRaises(RuntimeError):
            with ConsoleProgress(stream=stream) as progress:
                raise RuntimeError("fixture")
        self.assertFalse(progress._thread.is_alive())
        self.assertIn("异常中止", stream.getvalue())

class ProgressConfigTests(unittest.TestCase):
    def test_missing_progress_uses_sixty_second_default(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(config_fixtures.write_config(Path(directory)))
        self.assertEqual(config.card_generator.progress, ProgressConfig(True, 60))

    def test_shipped_generation_and_idle_limits_are_twenty_five_minutes(self):
        root = ASSETS_DIR
        for name in ("config.json", "config.example.json"):
            with self.subTest(config=name):
                config = load_config(root / "config" / name, group_id=42)
                self.assertEqual(config.card_generator.progress.heartbeat_interval_seconds, 60)
                self.assertEqual(config.card_generator.generation_timeout_seconds, 1500)
                self.assertGreater(config.tasks.lease_seconds, config.card_generator.generation_timeout_seconds)

    def test_explicit_old_interval_remains_configurable(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(config_fixtures.write_config(Path(directory), {
                "card_generator": {"progress": {"enabled": True, "heartbeat_interval_seconds": 15}},
            }))
        self.assertEqual(config.card_generator.progress.heartbeat_interval_seconds, 15)

    def test_custom_progress_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(config_fixtures.write_config(Path(directory), {
                "card_generator": {"progress": {"enabled": False, "heartbeat_interval_seconds": 3}},
            }))
        self.assertEqual(config.card_generator.progress, ProgressConfig(False, 3))

    def test_invalid_progress_configuration_rejected(self):
        for progress in (None, {}, {"enabled": "false", "heartbeat_interval_seconds": 15},
                         *({"enabled": True, "heartbeat_interval_seconds": value} for value in (0, 301, True, "15", float("nan"), float("inf")))):
            with self.subTest(progress=progress), tempfile.TemporaryDirectory() as directory:
                config_file = config_fixtures.write_config(Path(directory), {"card_generator": {"progress": progress}})
                with self.assertRaises(ConfigError):
                    load_config(config_file)

if __name__ == "__main__":
    unittest.main()
