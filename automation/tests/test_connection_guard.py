from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hydro_platform.card_generators.connection_guard import ConnectionGuard
from hydro_platform.card_generators.codex_cli import CodexCliAdapter, _safe_exec_diagnostic, _terminal_failure_events
from hydro_platform.card_generators.streaming import ExecutionStopped, run_streaming_prompt
from hydro_platform.cli import main
from hydro_platform.config import ConfigError, ConnectionGuardConfig, load_config
from hydro_platform.failure_records import save_failure_record
import test_card_generator as fixtures
import test_config as config_fixtures
import test_multi_agent_card_generator as workflow_fixtures


RECONNECT = {"type": "error", "message": "Reconnecting... 1/5 (stream disconnected)"}
COMPLETED = {"type": "turn.completed"}


def pdf_event(kind="item.started"):
    return {"type": kind, "item": {"type": "mcp_tool_call", "server": "reader", "tool": "read_full_source_pdf", "status": "completed"}}


class GuardStateTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.guard = ConnectionGuard(ConnectionGuardConfig(), "reader", clock=lambda: self.now)

    def test_second_reconnect_latches_stop_even_after_late_completion(self):
        self.guard.observe(RECONNECT)
        self.assertIsNone(self.guard.check())
        self.guard.observe(RECONNECT)
        self.guard.observe(COMPLETED)
        self.assertEqual(self.guard.check()[0], "CODEX_RECONNECT_LIMIT_REACHED")

    def test_reconnect_count_does_not_reset_after_tool_progress(self):
        self.guard.observe(RECONNECT)
        self.guard.observe(pdf_event())
        self.assertIsNone(self.guard.recovery_started)
        self.guard.observe(RECONNECT)
        self.assertEqual(self.guard.snapshot()["reconnect_events"], 2)
        self.assertEqual(self.guard.check()[0], "CODEX_RECONNECT_LIMIT_REACHED")

    def test_recovery_deadline_is_not_reset_by_retries_or_local_tool_return(self):
        self.guard.config = replace(self.guard.config, reconnect_event_limit=10)
        self.guard.observe(RECONNECT)
        self.now = 50
        self.guard.observe(RECONNECT)
        self.guard.observe(pdf_event("item.completed"))
        self.now = 60
        self.assertEqual(self.guard.check()[0], "CODEX_RECONNECT_TIMEOUT")

    def test_normal_silent_reasoning_has_separate_idle_budget(self):
        self.guard.observe(pdf_event())
        self.now = 200
        self.assertIsNone(self.guard.check())
        self.now = 300
        self.assertEqual(self.guard.check()[0], "CODEX_NO_PROGRESS_TIMEOUT")

    def test_only_known_progress_resets_idle_budget(self):
        self.now = 280
        self.guard.observe({"type": "heartbeat"})
        self.guard.observe({"type": "unknown"})
        self.guard.observe({"type": "error", "message": "warning"})
        self.now = 300
        self.assertEqual(self.guard.check()[0], "CODEX_NO_PROGRESS_TIMEOUT")

    def test_model_progress_allows_recovery_but_retains_total_reconnect_count(self):
        self.guard.observe(RECONNECT)
        self.now = 50
        self.guard.observe({"type": "item.completed", "item": {"type": "agent_message"}})
        self.now = 100
        self.assertIsNone(self.guard.check())
        self.assertEqual(self.guard.reconnect_events, 1)

    def test_third_whole_pdf_call_stops_loop(self):
        self.guard.observe(pdf_event())
        self.guard.observe(pdf_event())
        self.assertIsNone(self.guard.check())
        self.guard.observe(pdf_event())
        self.assertEqual(self.guard.check()[0], "CODEX_PDF_READ_REPEAT_LIMIT")

    def test_relaxed_profile_allows_nine_reconnects_and_stops_at_ten(self):
        self.guard.config = ConnectionGuardConfig(10, 300, 900, 2)
        for count in range(1, 10):
            self.now = count * 4
            self.guard.observe(RECONNECT)
            self.assertIsNone(self.guard.check())
        self.guard.observe(RECONNECT)
        self.assertEqual(self.guard.check()[0], "CODEX_RECONNECT_LIMIT_REACHED")
        self.assertEqual(self.guard.reconnect_events, 10)

    def test_relaxed_profile_waits_five_minutes_for_recovery(self):
        self.guard.config = ConnectionGuardConfig(10, 300, 900, 2)
        self.guard.observe(RECONNECT)
        self.now = 299
        self.assertIsNone(self.guard.check())
        self.now = 300
        self.assertEqual(self.guard.check()[0], "CODEX_RECONNECT_TIMEOUT")

    def test_relaxed_profile_waits_fifteen_minutes_without_progress(self):
        self.guard.config = ConnectionGuardConfig(10, 300, 900, 2)
        self.now = 899
        self.assertIsNone(self.guard.check())
        self.now = 900
        self.assertEqual(self.guard.check()[0], "CODEX_NO_PROGRESS_TIMEOUT")

    def test_other_tools_and_completion_events_do_not_count_as_pdf_call(self):
        event = pdf_event()
        event["item"]["server"] = "unrelated"
        self.guard.observe(event)
        self.guard.observe(pdf_event("item.completed"))
        self.assertEqual(self.guard.pdf_calls, 0)

    def test_disabled_reconnect_stop_keeps_count_without_count_or_recovery_stop(self):
        self.guard.config = ConnectionGuardConfig(10, 300, 1200, 2, reconnect_stop_enabled=False)
        for count in range(20):
            self.now = count * 10
            self.guard.observe(RECONNECT)
        self.now = 600
        self.assertIsNone(self.guard.check())
        self.assertEqual(self.guard.snapshot()["reconnect_events"], 20)
        self.assertFalse(self.guard.snapshot()["reconnect_stop_enabled"])

    def test_disabled_reconnect_stop_replays_five_minute_failure_without_stopping(self):
        self.guard.config = ConnectionGuardConfig(10, 300, 1200, 2, reconnect_stop_enabled=False)
        sequence = [(0, {"type": "turn.started"}), (28, pdf_event()),
                    (35, pdf_event("item.completed"))]
        sequence += [(timestamp, RECONNECT) for timestamp in (188, 213, 238, 312, 398)]
        for timestamp, event in sequence:
            self.now = timestamp
            self.guard.observe(event)
            self.assertIsNone(self.guard.check())
        self.now = 488
        self.assertIsNone(self.guard.check())
        self.now = 600
        self.guard.observe(COMPLETED)
        self.assertIsNone(self.guard.check())

    def test_disabled_reconnect_stop_keeps_pdf_repeat_protection(self):
        self.guard.config = replace(self.guard.config, reconnect_stop_enabled=False)
        for _ in range(3):
            self.guard.observe(pdf_event())
        self.assertEqual(self.guard.check()[0], "CODEX_PDF_READ_REPEAT_LIMIT")

    def test_disabled_reconnect_stop_keeps_idle_protection(self):
        self.guard.config = ConnectionGuardConfig(10, 300, 1200, 2, reconnect_stop_enabled=False)
        self.guard.observe(RECONNECT)
        self.now = 1199
        self.assertIsNone(self.guard.check())
        self.now = 1200
        self.assertEqual(self.guard.check()[0], "CODEX_NO_PROGRESS_TIMEOUT")

    def test_replays_reported_failure_timeline_and_stops_at_second_retry(self):
        sequence = [
            (0, {"type": "turn.started"}), (23, pdf_event()),
            (23, {"type": "item.completed", "item": {**pdf_event()["item"], "status": "failed"}}),
            (32, pdf_event()), (42, pdf_event("item.completed")),
            (46, RECONNECT), (50, RECONNECT),
        ]
        for timestamp, event in sequence:
            self.now = timestamp
            self.guard.observe(event)
            if timestamp < 50:
                self.assertIsNone(self.guard.check())
        self.assertEqual(self.guard.check()[0], "CODEX_RECONNECT_LIMIT_REACHED")
        self.assertEqual(self.guard.snapshot()["elapsed_seconds"], 50)


class GuardProcessTests(unittest.TestCase):
    def run_stopping_process(self, script, config):
        processes = []
        real_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process

        started = time.monotonic()
        with patch("hydro_platform.card_generators.streaming.subprocess.Popen", side_effect=spawn):
            with self.assertRaises(ExecutionStopped) as raised:
                run_streaming_prompt([sys.executable, "-u", "-c", script], "", 10, connection_guard=config)
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(processes[0].stdout.closed)
        self.assertTrue(processes[0].stderr.closed)
        self.assertLess(time.monotonic() - started, 5)
        return raised.exception

    def test_reconnect_loop_stops_without_progress_callback(self):
        script = f"import time; print({json.dumps(RECONNECT)!r},flush=True); print({json.dumps(RECONNECT)!r},flush=True); time.sleep(20)"
        error = self.run_stopping_process(script, ConnectionGuardConfig())
        self.assertEqual(error.code, "CODEX_RECONNECT_LIMIT_REACHED")
        self.assertIn("Reconnecting", error.result.stdout)
        self.assertEqual(error.diagnostic["reconnect_events"], 2)

    def test_single_error_then_silence_stops_on_recovery_deadline(self):
        script = f"import time; print({json.dumps(RECONNECT)!r},flush=True); time.sleep(20)"
        error = self.run_stopping_process(script, ConnectionGuardConfig(recovery_timeout_seconds=0.2))
        self.assertEqual(error.code, "CODEX_RECONNECT_TIMEOUT")

    def test_silent_process_stops_on_idle_deadline(self):
        error = self.run_stopping_process("import time; time.sleep(20)", ConnectionGuardConfig(idle_timeout_seconds=0.2))
        self.assertEqual(error.code, "CODEX_NO_PROGRESS_TIMEOUT")

    def test_recovery_before_limit_can_complete_normally(self):
        script = f"print({json.dumps(RECONNECT)!r}); print({json.dumps(COMPLETED)!r})"
        result = run_streaming_prompt([sys.executable, "-u", "-c", script], "", 5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(_terminal_failure_events([json.loads(line) for line in result.stdout.splitlines()]), [])

    def test_relaxed_profile_completes_after_nine_reconnects(self):
        events = [RECONNECT] * 9 + [COMPLETED]
        script = "\n".join(f"print({json.dumps(event)!r}, flush=True)" for event in events)
        result = run_streaming_prompt(
            [sys.executable, "-u", "-c", script], "", 5,
            connection_guard=ConnectionGuardConfig(10, 300, 900, 2),
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(_terminal_failure_events([json.loads(line) for line in result.stdout.splitlines()]), [])


    def test_disabled_reconnect_stop_allows_more_than_ten_retries_then_completion(self):
        events = [RECONNECT] * 20 + [COMPLETED]
        script = "\n".join(f"print({json.dumps(event)!r}, flush=True)" for event in events)
        result = run_streaming_prompt(
            [sys.executable, "-u", "-c", script], "", 5,
            connection_guard=ConnectionGuardConfig(reconnect_stop_enabled=False),
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(_terminal_failure_events([json.loads(line) for line in result.stdout.splitlines()]), [])

    def test_disabled_reconnect_stop_keeps_total_deadline_and_cleans_up_child(self):
        script = f"import time; print({json.dumps(RECONNECT)!r}, flush=True); time.sleep(20)"
        processes = []
        real_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process

        with patch("hydro_platform.card_generators.streaming.subprocess.Popen", side_effect=spawn):
            with self.assertRaises(subprocess.TimeoutExpired):
                run_streaming_prompt(
                    [sys.executable, "-u", "-c", script], "", 0.5,
                    connection_guard=ConnectionGuardConfig(reconnect_stop_enabled=False),
                )
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(processes[0].stdout.closed)
        self.assertTrue(processes[0].stderr.closed)


class GeneratorRecoveryTests(unittest.TestCase):
    def test_smoke_probe_also_accepts_recovered_reconnection(self):
        runner = fixtures.SequenceRunner([
            fixtures.command_result([], stdout="codex-cli 1.0"),
            fixtures.command_result([], stdout="Logged in using ChatGPT"),
            fixtures.command_result([], stdout=fixtures.smoke_jsonl(extra_events=[RECONNECT])),
        ])
        adapter = CodexCliAdapter(fixtures.generator_config(), executable_finder=lambda _: "codex", runner=runner)
        self.assertTrue(adapter.smoke_test()["ok"])

    def generate(self, *, events=None, returncode=0, exception=None, progress=None, default_runner=False, receipt=True):
        output = {"schema_version": 2, "source_read_status": "FULL_PDF_REVIEWED", "source_page_count": 12,
                  "visual_content_status": "REVIEWED", "source_read_evidence": "fixture", "card_body_markdown": "# fixture"}
        response = fixtures.command_result(["codex", "exec"], returncode=returncode, stdout=fixtures.smoke_jsonl(message=json.dumps(output), extra_events=events))
        prompt_runner = fixtures.PromptSequenceRunner([exception or response], write_receipt=receipt)
        kwargs = {} if default_runner else {"prompt_runner": prompt_runner}
        adapter = CodexCliAdapter(fixtures.generator_config(), executable_finder=lambda _: "codex", progress=progress,
            runner=fixtures.SequenceRunner([
                fixtures.command_result(["codex", "--version"], stdout="codex-cli 1.0"),
                fixtures.command_result(["codex", "login", "status"], stdout="Logged in using ChatGPT"),
            ]), **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"%PDF-1.7 fixture")
            schema = root / "schema.json"
            schema.write_text("{}", encoding="utf-8")
            return adapter.generate("fixture", working_directory=root, source_pdf_path=pdf, zotero_parent_key="CEXH4PQA", output_schema_path=schema)

    def test_recovered_reconnect_passes_all_existing_result_and_pdf_gates(self):
        self.assertTrue(self.generate(events=[RECONNECT])["ok"])

    def test_recovered_reconnect_does_not_bypass_pdf_receipt_gate(self):
        result = self.generate(events=[RECONNECT], receipt=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_PDF_NOT_ACCESSED")

    def test_recovered_reconnect_does_not_bypass_tool_policy(self):
        result = self.generate(events=[RECONNECT, {"type": "item.completed", "item": {"type": "file_change"}}])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_GENERATION_UNEXPECTED_ACTIVITY")

    def test_nonzero_exit_is_still_failure_even_with_completion_event(self):
        self.assertFalse(self.generate(events=[RECONNECT], returncode=1)["ok"])

    def test_real_terminal_failure_is_not_ignored(self):
        for event in ({"type": "turn.failed", "error": {"message": "stream disconnected"}}, {"type": "error", "message": "invalid output"}):
            with self.subTest(event=event):
                self.assertFalse(self.generate(events=[event])["ok"])
        self.assertEqual(_terminal_failure_events([COMPLETED, RECONNECT]), [RECONNECT])

    def test_guard_failure_has_specific_code_and_diagnostic(self):
        stopped = ExecutionStopped("CODEX_RECONNECT_LIMIT_REACHED", "stopped", {"reconnect_events": 2})
        stopped.result = fixtures.command_result([], returncode=-1, stdout=json.dumps(RECONNECT))
        result = self.generate(exception=stopped)
        self.assertEqual(result["error"]["code"], stopped.code)
        self.assertEqual(result["diagnostic"]["connection_guard"]["reconnect_events"], 2)

    def test_default_adapter_uses_guard_even_when_progress_is_none(self):
        with patch("hydro_platform.card_generators.codex_cli.run_streaming_prompt", return_value=fixtures.command_result([], returncode=1)) as stream:
            self.generate(default_runner=True)
        self.assertEqual(stream.call_count, 1)
        self.assertEqual(stream.call_args.kwargs["connection_guard"], ConnectionGuardConfig())
        self.assertIsNone(stream.call_args.kwargs["progress"])

    def test_timeout_retains_partial_diagnostic(self):
        timeout = subprocess.TimeoutExpired([], 20, output=json.dumps(RECONNECT).encode(), stderr=b"network error")
        result = self.generate(exception=timeout)
        self.assertEqual(result["error"]["code"], "CODEX_GENERATION_TIMEOUT")
        self.assertIn("Reconnecting", result["diagnostic"]["first_error"])

    def test_provider_stop_prevents_next_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = workflow_fixtures.WorkflowFixture(Path(directory))
            provider = Mock()
            provider.generate.return_value = {"ok": False, "error": {"code": "CODEX_RECONNECT_LIMIT_REACHED", "message": "stopped"}}
            result = fixture.run(provider)
        self.assertEqual(provider.generate.call_count, 1)
        self.assertEqual(result["diagnostic"]["stage"], "fact_extractor_a")


class FailureRecordTests(unittest.TestCase):
    def test_cli_failure_saves_in_configured_log_directory(self):
        config = fixtures.GeneratorPreflightCliTests._generation_app_config()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            config.paths.logs_dir = Path(directory) / "configured-logs"
            with (patch("hydro_platform.cli.load_config", return_value=config),
                  patch("hydro_platform.cli.preflight", return_value={"ok": False, "error": {"code": "ORIGINAL"}}),
                  redirect_stdout(output), redirect_stderr(io.StringIO())):
                code = main(["evidence-generate-trial", "--item-key", "CEXH4PQA", "--json"])
            result = json.loads(output.getvalue())
            record_path = Path(result["diagnostic_log_path"])
            self.assertEqual(record_path.parent, config.paths.logs_dir)
            self.assertEqual(json.loads(record_path.read_text(encoding="utf-8"))["result"]["error"]["code"], "ORIGINAL")
        self.assertEqual(code, 3)

    def test_first_tool_error_and_final_error_survive_long_reconnect_summary(self):
        events = [{"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "reader", "tool": "read_full_source_pdf",
                  "status": "failed", "error": {"message": "invalid arguments api_key=sk-super-secret-123456"}}}]
        events += [{"type": "item.completed", "item": {"type": "agent_message", "text": "PRIVATE_PAPER_BODY"}}]
        events += [{"type": "error", "message": f"Reconnecting... {n}: " + "network " * 80} for n in range(15)]
        events += [{"type": "turn.failed", "error": {"message": "final network error"}}]
        diagnostic = _safe_exec_diagnostic(fixtures.command_result([], returncode=1, stdout="\n".join(json.dumps(e) for e in events)), "CODEX_SERVICE_UNAVAILABLE")
        self.assertIn("invalid arguments", diagnostic["first_tool_error"]["summary"])
        self.assertIn("final network error", diagnostic["last_error"])
        self.assertLessEqual(len(diagnostic["summary"]), 1600)
        with tempfile.TemporaryDirectory() as directory:
            path = save_failure_record(Path(directory), "evidence-generate-trial", "CEXH4PQA", {"ok": False, "diagnostic": diagnostic})
            saved = path.read_text(encoding="utf-8")
            self.assertNotIn("sk-super-secret", saved)
            self.assertNotIn("PRIVATE_PAPER_BODY", saved)
            self.assertEqual(json.loads(saved)["item_key"], "CEXH4PQA")

    def test_records_are_unique_and_do_not_overwrite_earlier_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            first = save_failure_record(Path(directory), "trial", "A", {"ok": False})
            second = save_failure_record(Path(directory), "trial", "A", {"ok": False})
            self.assertNotEqual(first, second)
            self.assertTrue(first.is_file() and second.is_file())

    def test_record_io_failure_does_not_replace_original_error(self):
        config = fixtures.GeneratorPreflightCliTests._generation_app_config()
        config.paths.logs_dir = Path("unused")
        output = io.StringIO()
        with (patch("hydro_platform.cli.load_config", return_value=config),
              patch("hydro_platform.cli.preflight", return_value={"ok": False, "error": {"code": "ORIGINAL"}}),
              patch("hydro_platform.cli.save_failure_record", side_effect=PermissionError()),
              redirect_stdout(output), redirect_stderr(io.StringIO())):
            code = main(["evidence-generate-trial", "--item-key", "CEXH4PQA", "--json"])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 3)
        self.assertEqual(result["error"]["code"], "ORIGINAL")
        self.assertIn("diagnostic_log_warning", result)


class GuardConfigTests(unittest.TestCase):
    def test_existing_config_defaults_and_explicit_overrides(self):
        custom = ConnectionGuardConfig(1, 30, 180, 1)
        for value in (None, custom, ConnectionGuardConfig(10, 300, 900, 2),
                      ConnectionGuardConfig(10, 300, 1200, 2, reconnect_stop_enabled=False)):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                overrides = {} if value is None else {"card_generator": {"connection_guard": asdict(value)}}
                config = load_config(config_fixtures.write_config(Path(directory), overrides))
                self.assertEqual(config.card_generator.connection_guard, value or ConnectionGuardConfig())

    def test_shipped_example_disables_reconnect_stop(self):
        example = Path(__file__).resolve().parents[2] / "config" / "config.example.json"
        guard = json.loads(example.read_text(encoding="utf-8"))["card_generator"]["connection_guard"]
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(config_fixtures.write_config(
                Path(directory), {"card_generator": {"connection_guard": guard}},
            ))
        self.assertEqual(config.card_generator.connection_guard,
                         ConnectionGuardConfig(10, 300, 1500, 2, reconnect_stop_enabled=False))

    def test_old_four_field_config_keeps_reconnect_stop_enabled(self):
        guard = asdict(ConnectionGuardConfig(10, 300, 900, 2))
        guard.pop("reconnect_stop_enabled")
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(config_fixtures.write_config(
                Path(directory), {"card_generator": {"connection_guard": guard}},
            ))
        self.assertTrue(config.card_generator.connection_guard.reconnect_stop_enabled)

    def test_invalid_missing_unknown_and_unbounded_fields_rejected(self):
        cases = [None, {}, {**asdict(ConnectionGuardConfig()), "unknown": 1}]
        for name in asdict(ConnectionGuardConfig()):
            if name == "reconnect_stop_enabled":
                continue
            for value in (0, -1, True, "2", float("nan"), float("inf"), 10000):
                cases.append({**asdict(ConnectionGuardConfig()), name: value})
        cases.append({**asdict(ConnectionGuardConfig()), "reconnect_event_limit": 2.5})
        for value in (None, 0, 1, "false", "true", [], {}):
            cases.append({**asdict(ConnectionGuardConfig()), "reconnect_stop_enabled": value})
        for value in cases:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ConfigError):
                    load_config(config_fixtures.write_config(Path(directory), {"card_generator": {"connection_guard": value}}))


if __name__ == "__main__":
    unittest.main()
