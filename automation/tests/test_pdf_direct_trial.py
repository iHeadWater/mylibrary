from __future__ import annotations

import hashlib
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

from hydro_platform.card_generators.codex_cli import CodexCliAdapter
from hydro_platform.card_generators.streaming import _status_event
from hydro_platform.cli import main
from hydro_platform.config import ConfigError, load_config
from hydro_platform.pdf_delivery import PdfDelivery
from hydro_platform.pdf_direct_trial import PdfDirectTrialError, run_pdf_direct_trial
from test_card_generator import SequenceRunner, command_result, smoke_jsonl
from test_config import write_config


ASSETS = Path(__file__).resolve().parents[1]


class PdfDirectTrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config_path = write_config(self.root)
        self.config = load_config(self.config_path)
        self.config = replace(self.config, card_generator=replace(
            self.config.card_generator, model="gpt-5.6-sol", reasoning_effort="high"))
        for name, folder in (("prompt_file", "prompts"), ("schema_file", "schemas")):
            path = getattr(self.config.card_generator.pdf_direct_trial, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ASSETS / folder / path.name).read_bytes())
        source = self.root / "Zotero 原文.pdf"
        source.write_bytes(b"%PDF-fixture-only")
        self.delivery = PdfDelivery(
            42, "PARENT01", "ATTACH01", "TASK-fixture",
            hashlib.sha256(source.read_bytes()).hexdigest(), source, source.stat().st_size,
            self.root / "evidence-packs" / "EV-PARENT01",
            self.root / "evidence-packs" / "EV-PARENT01" / "manifest.json", "2026-09-08Z",
        )
        self.formal = [self.delivery.evidence_package_path / "card.md", self.delivery.manifest_path,
                       self.config.paths.tasks_file]
        for path in self.formal:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("do not modify", encoding="utf-8")
        self.report = {
            "read_status": "COMPLETE", "source_page_count": 3,
            "claimed_text_pages": [1, 2, 3], "claimed_visual_pages": [1, 2, 3],
            "visual_findings": [{"page": 2, "label": "Figure 1", "observation": "Fixture observation, not verified."}],
            "limitations": ["Vision interpretation needs sample review."],
        }
        self.adapter = Mock()
        self.adapter.preflight.return_value = {"ok": True, "resolved_executable": "codex-test"}
        self.runner = Mock(side_effect=self.run_model)
        self.local = Mock(side_effect=self.run_local)
        self.finder = Mock(side_effect=lambda name: str(self.root / name))
        self.sandbox_check = Mock(return_value={"ok": True, "model_invoked": False, "checks": []})
        self.command = None
        self.prompt = None
        self.workspace = None

    def run_model(self, command, prompt, timeout, **kwargs):
        self.command, self.prompt = command, prompt
        self.workspace = Path(command[command.index("--cd") + 1])
        self.assertTrue(self.workspace.is_dir())
        self.assertTrue(self.workspace.is_relative_to(self.config.paths.runtime_dir))
        (self.workspace / "rendered-page.png").write_bytes(b"fixture")
        return command_result(command, stdout=smoke_jsonl(message=json.dumps(self.report), extra_events=[
            {"type": "item.completed", "item": {"type": "command_execution", "status": "completed",
             "command": "PRIVATE_COMMAND", "aggregated_output": "PRIVATE_TOOL_OUTPUT", "exit_code": 0}},
        ]))

    def run_local(self, command, timeout):
        # Outside the separate sandbox preflight, no post-model text extraction is needed.
        self.assertEqual(Path(command[0]).name, "pdfinfo")
        return "Title: fixture\nPages: 3\n"

    def run_trial(self, **options):
        return run_pdf_direct_trial(self.config, self.delivery, adapter=self.adapter,
                                    runner=self.runner, local_runner=self.local,
                                    executable_finder=self.finder, sandbox_checker=self.sandbox_check, **options)

    def test_success_is_limited_and_only_writes_trial_outputs(self):
        result = self.run_trial()
        self.assertTrue(result["ok"])
        self.assertTrue(result["source_unchanged"])
        self.assertEqual(result["validation_status"], "READING_REPORT_ACCEPTED")
        self.assertEqual(result["protocol_version"], "pdf-direct-read-v2")
        self.assertNotIn("verified_text_probe_pages", result)
        for flag in ("full_read_verified", "visual_understanding_verified", "production_eligible"):
            self.assertFalse(result[flag])
        self.adapter.preflight.assert_called_once_with(check_pdf_reader=False)
        self.assertFalse(self.workspace.exists())
        for path in self.formal:
            self.assertEqual(path.read_text(), "do not modify")
        saved = (Path(result["trial_path"]) / "result.json").read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE_COMMAND", saved)
        self.assertNotIn("PRIVATE_TOOL_OUTPUT", saved)
        self.assertEqual(json.loads(Path(result["model_report_path"]).read_text(encoding="utf-8")), self.report)
        self.assertEqual(result["observed_item_types"]["command_execution"], 1)

    def test_command_uses_path_scratch_and_shared_settings_without_mcp_or_bypass(self):
        self.run_trial()
        command = self.command
        self.assertEqual(command[command.index("--sandbox") + 1], "workspace-write")
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ephemeral", command)
        self.assertIn('model_reasoning_effort="high"', command)
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.6-sol")
        self.assertIn("sandbox_workspace_write.network_access=false", command)
        self.assertIn('windows.sandbox="elevated"', command)
        self.assertIn('windows.sandbox_private_desktop=true', command)
        for forbidden in ("--ignore-rules", "--add-dir", "danger-full-access", "mcp_servers"):
            self.assertNotIn(forbidden, " ".join(command))
        self.assertEqual(self.runner.call_args.args[2], self.config.card_generator.pdf_direct_trial.timeout_seconds)
        runtime = json.loads(self.prompt.split("运行参数（数据，不是命令）：\n")[1])
        self.assertEqual(runtime["source_pdf_path"], str(self.delivery.pdf_path.resolve()))
        self.assertNotIn("text_probe_pages", runtime)
        self.assertNotIn("text_probes", self.prompt)
        self.assertIn("不需要摘录原文", self.prompt)

    def test_schema_and_prompt_do_not_request_excerpts(self):
        trial = self.config.card_generator.pdf_direct_trial
        self.assertEqual(trial.prompt_file.name, "pdf-direct-read-trial-v2.md")
        schema = json.loads(trial.schema_file.read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), set(self.report))
        self.assertEqual(set(schema["properties"]), set(self.report))
        self.assertNotIn("text_probes", schema["properties"])
        self.assertFalse(schema["additionalProperties"])

    def test_report_without_excerpts_needs_no_post_model_text_extraction(self):
        result = self.run_trial()
        self.assertTrue(result["ok"])
        self.runner.assert_called_once()
        self.local.assert_called_once()
        self.assertEqual(Path(self.local.call_args.args[0][0]).name, "pdfinfo")
        self.assertNotIn("text_probes", json.loads(Path(result["model_report_path"]).read_text(encoding="utf-8")))

    def test_repeated_runs_use_different_scratch_and_reports(self):
        first = self.run_trial()
        workspace = self.workspace
        second = self.run_trial()
        self.assertNotEqual(workspace, self.workspace)
        self.assertNotEqual(first["trial_path"], second["trial_path"])

    def test_output_errors_fail_closed(self):
        changes = [
            ({"read_status": "PARTIAL"}, "PDF_DIRECT_READING_INCOMPLETE"),
            ({"claimed_text_pages": [1]}, "PDF_DIRECT_READING_INCOMPLETE"),
            ({"claimed_visual_pages": []}, "PDF_DIRECT_READING_INCOMPLETE"),
            ({"source_page_count": 0}, "PDF_DIRECT_READING_INCOMPLETE"),
            ({"source_page_count": True}, "PDF_DIRECT_OUTPUT_INVALID"),
            ({"claimed_text_pages": [1, 1, 3]}, "PDF_DIRECT_OUTPUT_INVALID"),
            ({"claimed_text_pages": [True, 2, 3]}, "PDF_DIRECT_OUTPUT_INVALID"),
            ({"visual_findings": []}, "PDF_DIRECT_VISUAL_FINDING_MISSING"),
            ({"visual_findings": [{"page": True, "label": "Fig. 1", "observation": "fixture"}]}, "PDF_DIRECT_OUTPUT_INVALID"),
            ({"visual_findings": [{"page": 2, "label": "Fig. 1", "observation": ""}]}, "PDF_DIRECT_OUTPUT_INVALID"),
            ({"extra_field": "not allowed"}, "PDF_DIRECT_OUTPUT_INVALID"),
        ]
        original = self.report
        for delta, code in changes:
            with self.subTest(code=code, fields=list(delta)):
                self.report = {**original, **delta}
                result = self.run_trial()
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], code)
                self.assertFalse(self.workspace.exists())

    def test_missing_source_and_tools_stop_before_model(self):
        self.finder.return_value = None
        self.finder.side_effect = None
        with self.assertRaises(PdfDirectTrialError) as error:
            self.run_trial()
        self.assertEqual(error.exception.code, "PDF_DIRECT_TOOL_NOT_FOUND")
        self.delivery.pdf_path.unlink()
        with self.assertRaises(PdfDirectTrialError) as error:
            self.run_trial()
        self.assertEqual(error.exception.code, "PDF_DIRECT_SOURCE_UNAVAILABLE")
        self.runner.assert_not_called()

    def test_changed_input_and_invalid_assets_stop_before_model(self):
        self.delivery.pdf_path.write_bytes(b"changed")
        with self.assertRaises(PdfDirectTrialError) as error:
            self.run_trial()
        self.assertEqual(error.exception.code, "PDF_INPUT_CHANGED")
        self.delivery.pdf_path.write_bytes(b"%PDF-fixture-only")
        self.config.card_generator.pdf_direct_trial.schema_file.write_text("invalid")
        with self.assertRaises(PdfDirectTrialError) as error:
            self.run_trial()
        self.assertEqual(error.exception.code, "PDF_DIRECT_ASSET_INVALID")
        self.runner.assert_not_called()

    def test_preflight_failure_does_not_call_model(self):
        self.adapter.preflight.return_value = {"ok": False, "error": {"code": "CODEX_NOT_LOGGED_IN"}}
        result = self.run_trial()
        self.assertFalse(result["model_invoked"])
        self.runner.assert_not_called()

    def test_bad_events_missing_completion_and_bad_report(self):
        cases = [
            ("not-json", "PDF_DIRECT_EVENTS_INVALID"),
            ('{"type":"turn.started"}', "PDF_DIRECT_TURN_INCOMPLETE"),
            (smoke_jsonl(message="not-json"), "PDF_DIRECT_OUTPUT_INVALID"),
        ]
        for stdout, code in cases:
            with self.subTest(code=code):
                self.runner.side_effect = None
                self.runner.return_value = command_result([], stdout=stdout)
                result = self.run_trial()
                self.assertEqual(result["error"]["code"], code)

    def test_process_error_and_timeout_do_not_retry(self):
        for failure, code in [(OSError("private"), "PDF_DIRECT_EXEC_IO_ERROR"),
                              (subprocess.TimeoutExpired("codex", 1), "PDF_DIRECT_TIMEOUT")]:
            with self.subTest(code=code):
                self.runner.reset_mock()
                self.runner.side_effect = failure
                result = self.run_trial()
                self.assertEqual(result["error"]["code"], code)
                self.runner.assert_called_once()
                self.assertNotIn("private", json.dumps(result))

    def test_nonzero_exit_classified_even_without_json_events(self):
        self.runner.side_effect = None
        self.runner.return_value = command_result([], returncode=1, stderr="stream disconnected before completion")
        result = self.run_trial()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_SERVICE_UNAVAILABLE")

    def test_recovered_reconnect_is_not_terminal_failure(self):
        self.runner.side_effect = None
        self.runner.return_value = command_result([], stdout=smoke_jsonl(message=json.dumps(self.report), extra_events=[
            {"type": "error", "message": "Reconnecting... 1/5"},
        ]))
        self.assertTrue(self.run_trial()["ok"])

    def test_source_change_during_model_call_overrides_success(self):
        def mutate(*args, **kwargs):
            response = self.run_model(*args, **kwargs)
            self.delivery.pdf_path.write_bytes(b"changed externally")
            return response
        self.runner.side_effect = mutate
        result = self.run_trial()
        self.assertFalse(result["ok"])
        self.assertFalse(result["source_unchanged"])
        self.assertNotIn("validation_status", result)

    def test_cli_route_does_not_build_production_adapter(self):
        output = io.StringIO()
        with patch("hydro_platform.cli.load_config", return_value=self.config), \
             patch("hydro_platform.cli.preflight", return_value={"ok": True}), \
             patch("hydro_platform.cli.prepare_pdf_delivery", return_value=self.delivery) as delivery, \
             patch("hydro_platform.cli.run_pdf_direct_trial", return_value={"ok": True, "operation": "pdf_direct_read_trial"}) as run, \
             patch("hydro_platform.cli.build_card_generator_adapter") as production, redirect_stdout(output):
            self.assertEqual(main(["pdf-direct-read-trial", "--item-key", "PARENT01", "--json", "--no-progress"]), 0)
        production.assert_not_called()
        self.assertTrue(delivery.call_args.kwargs["allow_trial_states"])
        self.assertEqual(run.call_args.args, (self.config, self.delivery))
        self.assertTrue(json.loads(output.getvalue())["ok"])

    def test_direct_cli_preflight_does_not_require_mcp_script(self):
        runner = SequenceRunner([command_result([], stdout="codex-cli fixture"),
                                 command_result([], stdout="Logged in using ChatGPT")])
        adapter = CodexCliAdapter(self.config.card_generator, runner=runner, executable_finder=lambda _: "codex")
        self.assertFalse(self.config.card_generator.pdf_reader.server_file.exists())
        result = adapter.preflight(check_pdf_reader=False)
        self.assertTrue(result["ok"])
        self.assertEqual(len(runner.calls), 2)
        self.assertNotIn("pdf_reader", result)

    def test_local_command_status_does_not_leak_payload_or_claim_visual_access(self):
        events = []
        for status in ("started", "completed"):
            _status_event(json.dumps({"type": "item." + status, "item": {
                "type": "command_execution", "command": "SECRET", "aggregated_output": "SECRET",
                "status": "completed", "exit_code": 0,
            }}), events.append, "reader")
        rendered = json.dumps(events, ensure_ascii=False)
        self.assertIn("本机读取/处理命令已开始", rendered)
        self.assertIn("不代表已读完", rendered)
        self.assertNotIn("SECRET", rendered)

    def test_configuration_defaults_and_custom_paths(self):
        self.assertEqual(self.config.card_generator.pdf_direct_trial.timeout_seconds, 1200)
        data = json.loads(self.config_path.read_text())
        data["card_generator"]["pdf_direct_trial"] = {
            "prompt_file": "automation/prompts/custom.md", "schema_file": "automation/schemas/custom.json",
            "timeout_seconds": 1800,
        }
        self.config_path.write_text(json.dumps(data))
        trial = load_config(self.config_path).card_generator.pdf_direct_trial
        self.assertEqual(trial.prompt_file, self.root / "automation/prompts/custom.md")
        self.assertEqual(trial.timeout_seconds, 1800)
        for delta in ({"prompt_file": "../escape.md"}, {"timeout_seconds": 0}, {"timeout_seconds": True}):
            with self.subTest(delta=delta):
                invalid = json.loads(json.dumps(data))
                invalid["card_generator"]["pdf_direct_trial"].update(delta)
                self.config_path.write_text(json.dumps(invalid))
                with self.assertRaises(ConfigError):
                    load_config(self.config_path)

    def test_sandbox_failure_stops_before_model_and_preserves_diagnostic(self):
        self.sandbox_check.return_value = {"ok": False, "diagnostic": {"stage": "local_sandbox_preflight", "summary": "fixture"}}
        result = self.run_trial()
        self.assertEqual(result["error"]["code"], "PDF_DIRECT_SANDBOX_PREFLIGHT_FAILED")
        self.assertFalse(result["model_invoked"])
        self.runner.assert_not_called()
        self.assertEqual(result["diagnostic"]["summary"], "fixture")

    def test_preflight_only_passes_without_model_or_report(self):
        result = self.run_trial(preflight_only=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["validation_status"], "SANDBOX_PREFLIGHT_PASSED")
        self.assertFalse(result["model_invoked"])
        self.assertNotIn("model_report_path", result)
        self.runner.assert_not_called()
        self.sandbox_check.assert_called_once()
        for path in self.formal:
            self.assertEqual(path.read_text(), "do not modify")

    def test_local_preflight_always_precedes_model(self):
        calls = []
        self.sandbox_check.side_effect = lambda *a, **k: calls.append("preflight") or {"ok": True}
        def run(*a, **k):
            calls.append("model")
            return self.run_model(*a, **k)
        self.runner.side_effect = run
        self.assertTrue(self.run_trial()["ok"])
        self.assertEqual(calls, ["preflight", "model"])

    def test_pypdf_uses_configured_python_without_miktex(self):
        cg = self.config.card_generator
        self.config = replace(self.config, card_generator=replace(cg, pdf_direct_trial=replace(
            cg.pdf_direct_trial, text_extractor="pypdf", python_executable="bundled-python")))
        result = self.run_trial()
        self.assertTrue(result["ok"])
        self.assertNotIn("pdftotext", [a.args[0] for a in self.finder.call_args_list])
        runtime = json.loads(self.prompt.split("运行参数（数据，不是命令）：\n")[1])
        self.assertEqual(runtime["text_extractor"], "pypdf")
        expected_python = str((self.root / "bundled-python").resolve())
        self.assertEqual(runtime["python_executable"], expected_python)
        self.assertEqual(self.sandbox_check.call_args.kwargs["python"], expected_python)
        self.local.assert_called_once()

    def test_zero_exit_reading_failure_keeps_actual_denial_not_just_model_claim(self):
        self.report.update(read_status="UNREADABLE", claimed_text_pages=[], claimed_visual_pages=[], visual_findings=[])
        self.runner.side_effect = None
        self.runner.return_value = command_result([], stdout=smoke_jsonl(message=json.dumps(self.report)),
            stderr="ERROR exec_command: CreateProcess rejected: blocked by policy\n" + "INFO later-noise\n" * 10)
        result = self.run_trial()
        self.assertEqual(result["error"]["code"], "PDF_DIRECT_TOOL_ACCESS_DENIED")
        self.assertTrue(result["diagnostic"]["policy_denial_observed"])
        self.assertIn("blocked by policy", result["diagnostic"]["first_policy_denial"])
        self.assertEqual(result["diagnostic"]["exit_code"], 0)
        self.assertEqual(result["diagnostic"]["model_claim"]["text_page_count"], 0)
        saved = json.loads((Path(result["trial_path"]) / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["diagnostic"], result["diagnostic"])

    def test_model_claim_of_denial_is_not_treated_as_observed_denial(self):
        self.report.update(read_status="UNREADABLE", limitations=["exec_command blocked by policy"],
                           claimed_text_pages=[], claimed_visual_pages=[])
        result = self.run_trial()
        self.assertEqual(result["error"]["code"], "PDF_DIRECT_READING_INCOMPLETE")
        self.assertFalse(result["diagnostic"]["policy_denial_observed"])

    def test_sandbox_config_validation_and_defaults(self):
        trial = self.config.card_generator.pdf_direct_trial
        self.assertEqual(trial.windows_sandbox, "elevated")
        data = json.loads(self.config_path.read_text())
        original = {"prompt_file": "automation/prompts/pdf-direct-read-trial-v2.md",
                    "schema_file": "automation/schemas/pdf-direct-read-trial-output.schema.json", "timeout_seconds": 1200}
        for delta in ({"windows_sandbox": "disabled"}, {"preflight_timeout_seconds": 0},
                      {"shell_executable": ""}, {"python_executable": 123}, {"text_extractor": "auto"}):
            with self.subTest(delta=delta):
                data["card_generator"]["pdf_direct_trial"] = {**original, **delta}
                self.config_path.write_text(json.dumps(data))
                with self.assertRaises(ConfigError):
                    load_config(self.config_path)


if __name__ == "__main__":
    unittest.main()
