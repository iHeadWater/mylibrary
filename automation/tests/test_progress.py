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

from hydro_platform.card_generators.streaming import _status_event, run_streaming_prompt
from hydro_platform.cli import main
from hydro_platform.config import ConfigError, ProgressConfig, REQUIRED_CARD_WORKFLOW_ROLES, load_config
from hydro_platform.progress import ConsoleProgress
import test_card_generator as generator_fixtures
import test_config as config_fixtures
import test_multi_agent_card_generator as workflow_fixtures


class ProgressTests(unittest.TestCase):
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

        with patch("hydro_platform.card_generators.streaming.subprocess.Popen", side_effect=create):
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

        with patch("hydro_platform.card_generators.streaming.subprocess.Popen", side_effect=create):
            with self.assertRaises(KeyboardInterrupt):
                run_streaming_prompt([sys.executable, "-c", "import time; time.sleep(10)"], "", 5)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed)
        self.assertTrue(children[0].stderr.closed)


class WorkflowProgressTests(unittest.TestCase):
    def test_all_roles_emit_start_then_validated_completion_in_order(self):
        events = []
        with tempfile.TemporaryDirectory() as directory:
            fixture = workflow_fixtures.WorkflowFixture(Path(directory))
            result = fixture.run(workflow_fixtures.FakeProvider(fixture.outputs()), progress=events.append)
        self.assertTrue(result["ok"])
        lifecycle = [(e["event"], e["role"]) for e in events if e["event"] in {"role_started", "role_completed"}]
        self.assertEqual(lifecycle, [(event, role) for role in REQUIRED_CARD_WORKFLOW_ROLES for event in ("role_started", "role_completed")])
        self.assertEqual(events[-1]["event"], "workflow_completed")

    def test_quality_failure_does_not_complete_role_or_start_next(self):
        events = []
        with tempfile.TemporaryDirectory() as directory:
            fixture = workflow_fixtures.WorkflowFixture(Path(directory))
            outputs = fixture.outputs()
            outputs["fact_extractor_a"]["facts"][0]["fact_id"] = ""
            result = fixture.run(workflow_fixtures.FakeProvider(outputs), progress=events.append)
        self.assertFalse(result["ok"])
        self.assertEqual([e["role"] for e in events if e["event"] == "role_started"], ["fact_extractor_a"])
        self.assertFalse(any(e["event"] in {"role_completed", "workflow_completed"} for e in events))


class ProgressConfigTests(unittest.TestCase):
    def test_default_preserves_existing_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(config_fixtures.write_config(Path(directory)))
        self.assertEqual(config.card_generator.progress, ProgressConfig(True, 15))

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


class ProgressCliTests(unittest.TestCase):
    def run_cli(self, *, options=(), enabled=True, failure=False, cancel=False):
        config = generator_fixtures.GeneratorPreflightCliTests._generation_app_config()
        config.card_generator = replace(config.card_generator, progress=ProgressConfig(enabled=enabled))
        expected = {"schema_version": 1, "ok": True, "operation": "evidence_generate_trial"}
        stdout, stderr = io.StringIO(), io.StringIO()
        callback = None

        def build(config, *, progress):
            nonlocal callback
            callback = progress
            return Mock()

        def generate(*args, **kwargs):
            callback({"event": "role_started", "role": "fact_extractor_b", "index": 2, "total": 6})
            if cancel:
                raise KeyboardInterrupt()
            if failure:
                from hydro_platform.card_generation import CardGenerationError
                raise CardGenerationError("CARD_QUALITY_CONTRACT_FAILED", "fixture")
            return expected

        with (tempfile.TemporaryDirectory() as directory,
              patch("hydro_platform.cli.load_config", return_value=config),
              patch("hydro_platform.cli.preflight", return_value={"ok": True}),
              patch("hydro_platform.cli.build_card_generator_adapter", side_effect=build),
              patch("hydro_platform.cli.generate_evidence_card_trial", side_effect=generate),
              redirect_stdout(stdout), redirect_stderr(stderr)):
            config.paths.logs_dir = Path(directory) / "logs"
            code = main(["evidence-generate-trial", "--item-key", "CEXH4PQA", "--json", *options])
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    def test_progress_is_on_stderr_and_stdout_is_one_json_result(self):
        code, result, progress = self.run_cli()
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertIn("2/6 事实提取 B", progress)
        self.assertIn("试运行完成并保存", progress)

    def test_flag_and_config_can_each_disable_progress(self):
        for options, enabled in ((["--no-progress"], True), ([], False)):
            with self.subTest(options=options, enabled=enabled):
                code, result, progress = self.run_cli(options=options, enabled=enabled)
                self.assertEqual(code, 0)
                self.assertTrue(result["ok"])
                self.assertEqual(progress, "")

    def test_failure_reports_current_role_without_success(self):
        code, result, progress = self.run_cli(failure=True)
        self.assertEqual(code, 3)
        self.assertFalse(result["ok"])
        self.assertIn("[2/6 事实提取 B] 失败", progress)
        self.assertNotIn("完成并保存", progress)

    def test_cancel_returns_json_and_stops_reporter(self):
        code, result, progress = self.run_cli(cancel=True)
        self.assertEqual(code, 130)
        self.assertEqual(result["error"]["code"], "CANCELLED")
        self.assertNotIn("完成并保存", progress)


if __name__ == "__main__":
    unittest.main()
