from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hydrolitagent.cards.card_generators.streaming import _status_event, run_streaming_prompt
from hydrolitagent.cards.cli import main
from hydrolitagent.cards.config import ConfigError, ProgressConfig, REQUIRED_CARD_WORKFLOW_ROLES, load_config
from hydrolitagent.cards.progress import ConsoleProgress
import test_card_generator as generator_fixtures
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

class CodexStreamingTests(unittest.TestCase):
    def test_only_known_status_is_shown_without_model_or_tool_payload(self):
        events = []
        private = "PRIVATE_MODEL_TEXT_AND_SECRET"
        for line in ("not-json", "[]", "{}", json.dumps({"type": "unknown", "text": private})):
            _status_event(line, events.append, "configured_reader")
        self.assertEqual(events, [])
        for status in ("started", "completed"):
            event = {
                "type": f"item.{status}",
                "item": {"type": "mcp_tool_call", "server": "configured_reader",
                         "tool": "read_full_source_pdf", "status": "completed", "result": private},
            }
            _status_event(json.dumps(event), events.append, "different_reader")
            self.assertEqual(len(events), 0 if status == "started" else 1)
            _status_event(json.dumps(event), events.append, "configured_reader")
        _status_event(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": private}}), events.append, "configured_reader")
        rendered = json.dumps(events, ensure_ascii=False)
        self.assertNotIn(private, rendered)
        self.assertIn("完整性仍须由程序校验", rendered)
        self.assertEqual(len(events), 3)

    def test_reconnection_and_tool_failure_are_not_reported_as_success(self):
        events = []
        _status_event('{"type":"error","message":"Reconnecting... sk-private"}', events.append, "reader")
        _status_event(json.dumps({"type": "item.completed", "item": {
            "type": "mcp_tool_call", "server": "reader", "tool": "read_full_source_pdf", "status": "failed",
        }}), events.append, "reader")
        rendered = json.dumps(events, ensure_ascii=False)
        self.assertIn("连接重试", rendered)
        self.assertIn("PDF 工具调用失败", rendered)
        self.assertNotIn("sk-private", rendered)
        self.assertNotIn("校验通过", rendered)

    def test_event_delivered_before_child_can_exit_and_all_output_preserved(self):
        # The child cannot complete until a live callback acknowledges its event.
        script = """
import json, os, sys, time
from pathlib import Path
print(json.dumps({'type': 'turn.started'}), flush=True)
ack = Path(sys.argv[1])
limit = time.monotonic() + 4
while not ack.exists() and time.monotonic() < limit:
    time.sleep(.01)
if not ack.exists():
    sys.exit(7)
sys.stderr.write('E' * 300000)
sys.stderr.flush()
text = sys.stdin.read()
print(json.dumps({'input_size': len(text), 'custom_env': os.environ['HYDRO_TEST_STREAM']}))
"""
        events = []
        with tempfile.TemporaryDirectory() as directory:
            ack = Path(directory) / "ack"

            def progress(event):
                events.append(event)
                if "模型回合已开始" in event.get("message", ""):
                    ack.touch()

            result = run_streaming_prompt(
                [sys.executable, "-u", "-c", script, str(ack)], "中" * 300000, 8,
                {"HYDRO_TEST_STREAM": "ok", "PYTHONIOENCODING": "utf-8"}, progress=progress,
            )
        self.assertEqual(result.returncode, 0)
        lines = result.stdout.splitlines()
        self.assertEqual(json.loads(lines[0])["type"], "turn.started")
        self.assertEqual(json.loads(lines[1]), {"input_size": 300000, "custom_env": "ok"})
        self.assertEqual(result.stderr, "E" * 300000)

    def test_nonzero_exit_retains_raw_output_for_existing_diagnostics(self):
        result = run_streaming_prompt(
            [sys.executable, "-u", "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"],
            "", 5,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (3, "out\n", "err\n"))

    def test_timeout_terminates_owned_child(self):
        children = []
        real_popen = subprocess.Popen

        def create(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            children.append(process)
            return process

        with patch("hydrolitagent.cards.card_generators.streaming.subprocess.Popen", side_effect=create):
            with self.assertRaises(subprocess.TimeoutExpired):
                run_streaming_prompt([sys.executable, "-c", "import time; time.sleep(10)"], "", 0.3)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed)
        self.assertTrue(children[0].stderr.closed)

    def test_keyboard_interrupt_terminates_owned_child(self):
        children = []
        real_popen = subprocess.Popen

        def create(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            if not children:
                original_wait = process.wait
                first = True

                def wait(*args, **kwargs):
                    nonlocal first
                    if first:
                        first = False
                        raise KeyboardInterrupt()
                    return original_wait(*args, **kwargs)

                process.wait = wait
            children.append(process)
            return process

        with patch("hydrolitagent.cards.card_generators.streaming.subprocess.Popen", side_effect=create):
            with self.assertRaises(KeyboardInterrupt):
                run_streaming_prompt([sys.executable, "-c", "import time; time.sleep(10)"], "", 5)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed)
        self.assertTrue(children[0].stderr.closed)

class ProgressConfigTests(unittest.TestCase):
    def test_missing_progress_uses_sixty_second_default(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(config_fixtures.write_config(Path(directory)))
        self.assertEqual(config.card_generator.progress, ProgressConfig(True, 60))

    def test_shipped_generation_and_idle_limits_are_twenty_five_minutes(self):
        root = Path(__file__).resolve().parents[2]
        for name in ("config.json", "config.example.json"):
            with self.subTest(config=name):
                config = load_config(root / "config" / name, group_id=42)
                self.assertEqual(config.card_generator.progress.heartbeat_interval_seconds, 60)
                self.assertEqual(config.card_generator.generation_timeout_seconds, 1500)
                self.assertEqual(config.card_generator.connection_guard.idle_timeout_seconds, 1500)
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
