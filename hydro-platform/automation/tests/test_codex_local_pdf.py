from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.card_generators import build_card_generator_adapter
from hydro_platform.card_generators.codex_local_pdf import CodexLocalPdfAdapter
from hydro_platform.card_generators.multi_agent import MultiAgentCardGeneratorAdapter
from hydro_platform.card_generation import CardGenerationError, _validate_workflow_result
from hydro_platform.config import ConfigError, LOCAL_PATH_PROTOCOL_VERSION, REQUIRED_CARD_WORKFLOW_ROLES, load_config
from hydro_platform.evidence_packages import EvidencePackageError, load_evidence_manifest
from hydro_platform.source_access import source_access_acceptable
from test_card_generator import command_result, smoke_jsonl
from test_config import write_config
from test_multi_agent_card_generator import WorkflowFixture, common
from test_card_generation import FakeAdapter, GenerationFixture, PARENT_KEY, PDF_HASH, VALID_BODY

ASSETS = Path(__file__).resolve().parents[1]


def local_access(digest, parent=PARENT_KEY):
    return {"method": "local_pdf_path", "verified": False, "source_identity_verified": True,
            "source_sha256": digest, "parent_key": parent, "page_count": 12, "source_unchanged": True,
            "sandbox_preflight_passed": True, "model_reading_report_accepted": True,
            "model_claim_full_text": True, "model_claim_visuals": True, "command_event_count": 2,
            "full_read_verified": False, "visual_understanding_verified": False}


class LocalProviderFixture:
    def __init__(self, root):
        self.config_file = write_config(root / "project")
        app = load_config(self.config_file)
        cg = app.card_generator
        self.config = replace(cg, runtime_dir=root / ".runtime", pdf_reader=replace(cg.pdf_reader,
            adapter="local_path", server_file=root / "missing-mcp.py"), pdf_direct_trial=replace(cg.pdf_direct_trial,
            text_extractor="pypdf", python_executable="bundled-python",
            reading_prompt_file=ASSETS / "prompts/pdf-local-reading-v1.md"))
        self.pdf = root / "原文 paper.pdf"
        self.pdf.write_bytes(b"%PDF-fixture")
        self.schema = root / "output.schema.json"
        self.schema.write_text('{"type":"object"}')
        self.outputs = [common()]
        self.calls = []
        self.workspaces = []
        self.check_order = []
        self.sandbox = Mock(side_effect=lambda *a, **k: self.check_order.append("preflight") or {"ok": True, "model_invoked": False})
        self.local = Mock(return_value="Pages: 12\n")
        self.runner = Mock(side_effect=self.model)
        self.finder = Mock(side_effect=lambda value: str(root / value))
        def cli(command, timeout):
            return command_result(command, stdout="codex-cli fixture" if "--version" in command else "Logged in using ChatGPT")
        self.adapter = CodexLocalPdfAdapter(self.config, runner=cli, prompt_runner=self.runner,
            executable_finder=self.finder, sandbox_checker=self.sandbox, local_runner=self.local)

    def model(self, command, prompt, timeout, environment):
        self.check_order.append("model")
        self.calls.append((command, prompt, timeout, environment))
        directory = Path(command[command.index("--cd") + 1])
        self.workspaces.append(directory)
        assert directory.is_dir() and directory.is_relative_to(self.config.runtime_dir)
        (directory / "page.png").write_bytes(b"temporary-render")
        output = self.outputs[len(self.calls) - 1]
        return command_result(command, stdout=smoke_jsonl(message=json.dumps(output), extra_events=[
            {"type": "item.completed", "item": {"type": "command_execution", "status": "completed", "exit_code": 0}},
        ]))

    def run(self, **kwargs):
        return self.adapter.generate("本角色任务", working_directory=self.pdf.parent, source_pdf_path=self.pdf,
            zotero_parent_key=PARENT_KEY, output_schema_path=self.schema, **kwargs)


class LocalPdfProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = LocalProviderFixture(self.root)

    def test_role_reuses_path_reading_without_receipts_or_excerpts(self):
        result = self.f.run(model="model-role", reasoning_effort="xhigh", timeout_seconds=321, run_label="fact_extractor_a")
        self.assertTrue(result["ok"])
        self.assertTrue(source_access_acceptable(result["source_access"], expected_sha256=hashlib.sha256(self.f.pdf.read_bytes()).hexdigest()))
        self.assertFalse(result["source_access"]["verified"])
        self.assertNotIn("pages_served", result["source_access"])
        command, prompt, timeout, environment = self.f.calls[0]
        for forbidden in ("--ignore-rules", "--add-dir", "danger-full-access", "mcp_servers"):
            self.assertNotIn(forbidden, " ".join(command))
        self.assertEqual(command[command.index("--sandbox") + 1], "workspace-write")
        self.assertEqual(command[command.index("--model") + 1], "model-role")
        self.assertIn('model_reasoning_effort="xhigh"', command)
        self.assertIn("sandbox_workspace_write.network_access=false", command)
        self.assertIn("不需要固定页原文摘录", prompt)
        self.assertNotIn("text_probes", prompt)
        self.assertEqual(environment, {})
        self.assertEqual(timeout, 321)
        self.assertEqual(self.f.check_order, ["preflight", "model"])
        self.assertFalse(self.f.workspaces[0].exists())
        self.assertNotIn("pdftotext", [c.args[0] for c in self.f.finder.call_args_list])

    def test_preflight_failure_does_not_invoke_model(self):
        self.f.sandbox.side_effect = None
        self.f.sandbox.return_value = {"ok": False, "diagnostic": {"summary": "denied"}}
        result = self.f.run()
        self.assertEqual(result["error"]["code"], "PDF_DIRECT_SANDBOX_PREFLIGHT_FAILED")
        self.assertFalse(result["model_invoked"])
        self.f.runner.assert_not_called()

    def test_missing_reading_prompt_fails_before_model(self):
        self.f.adapter.config = replace(self.f.config, pdf_direct_trial=replace(self.f.config.pdf_direct_trial,
            reading_prompt_file=self.root / "missing.md"))
        self.assertEqual(self.f.run()["error"]["code"], "PDF_DIRECT_ASSET_INVALID")
        self.f.runner.assert_not_called()

    def test_incomplete_wrong_page_and_invalid_json_are_not_accepted(self):
        for changes, code in [({"source_read_status": "UNREADABLE"}, "PDF_DIRECT_READING_INCOMPLETE"),
                              ({"visual_content_status": "UNREADABLE"}, "PDF_DIRECT_READING_INCOMPLETE"),
                              ({"source_read_evidence": ""}, "PDF_DIRECT_READING_INCOMPLETE"),
                              ({"source_page_count": True}, "CODEX_PDF_PAGE_COUNT_MISMATCH"),
                              ({"source_page_count": 11}, "CODEX_PDF_PAGE_COUNT_MISMATCH")]:
            with self.subTest(changes=changes):
                self.f.outputs.append({**common(), **changes})
                self.f.outputs[len(self.f.calls)] = {**common(), **changes}
                self.assertEqual(self.f.run()["error"]["code"], code)
        self.f.runner.side_effect = None
        self.f.runner.return_value = command_result([], stdout=smoke_jsonl(message="bad json", extra_events=[
            {"type": "item.completed", "item": {"type": "command_execution"}}]))
        self.assertEqual(self.f.run()["error"]["code"], "CODEX_GENERATION_OUTPUT_INVALID")

    def test_claim_only_has_no_reading_activity(self):
        self.f.runner.side_effect = None
        self.f.runner.return_value = command_result([], stdout=smoke_jsonl(message=json.dumps(common())))
        self.assertEqual(self.f.run()["error"]["code"], "CODEX_PDF_NOT_ACCESSED")

    def test_mcp_network_and_nested_agents_are_not_allowed(self):
        self.f.runner.side_effect = None
        for kind in ("mcp_tool_call", "web_search", "collab_agent_tool_call"):
            with self.subTest(kind=kind):
                self.f.runner.return_value = command_result([], stdout=smoke_jsonl(message=json.dumps(common()), extra_events=[
                    {"type": "item.completed", "item": {"type": kind}}]))
                self.assertEqual(self.f.run()["error"]["code"], "CODEX_GENERATION_UNEXPECTED_ACTIVITY")

    def test_source_change_rejects_report(self):
        def mutate(*args):
            result = self.f.model(*args)
            self.f.pdf.write_bytes(b"changed")
            return result
        self.f.runner.side_effect = mutate
        self.assertEqual(self.f.run()["error"]["code"], "PDF_INPUT_CHANGED")

    def test_failure_timeout_and_recovered_reconnect(self):
        self.f.runner.side_effect = subprocess.TimeoutExpired("codex", 1)
        self.assertEqual(self.f.run()["error"]["code"], "CODEX_GENERATION_TIMEOUT")
        self.f.runner.assert_called_once()
        self.f.runner.side_effect = None
        self.f.runner.return_value = command_result([], returncode=1, stderr="stream disconnected before completion")
        self.assertEqual(self.f.run()["error"]["code"], "CODEX_SERVICE_UNAVAILABLE")
        self.f.runner.return_value = command_result([], stdout=smoke_jsonl(message=json.dumps(common()), extra_events=[
            {"type": "error", "message": "Reconnecting... 1/5"},
            {"type": "item.completed", "item": {"type": "command_execution"}}]))
        self.assertTrue(self.f.run()["ok"])

    def test_six_real_provider_roles_are_isolated_and_audited(self):
        directory = self.root / "workflow"
        directory.mkdir()
        workflow = WorkflowFixture(directory)
        workflow.config = replace(workflow.config, protocol_version=LOCAL_PATH_PROTOCOL_VERSION)
        self.f.outputs = [workflow.outputs()[r] for r in REQUIRED_CARD_WORKFLOW_ROLES]
        result = workflow.run(self.f.adapter)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(set(self.f.workspaces)), 6)
        self.assertTrue(all(not d.exists() for d in self.f.workspaces))
        self.assertEqual(self.f.check_order, ["preflight", "model"] * 6)
        self.assertNotIn("extractor_a_output", self.f.calls[1][1])
        self.assertNotIn("A：研究短历时降雨变化", self.f.calls[1][1])
        for index, role in enumerate(REQUIRED_CARD_WORKFLOW_ROLES):
            command = self.f.calls[index][0]
            self.assertEqual(command[command.index("--model") + 1], "model-" + role)
        self.assertFalse(result["workflow"]["gates"]["full_pdf_access_each_role"])
        _validate_workflow_result(result)
        corrupted = deepcopy(result)
        corrupted["quality_audit"]["roles"]["fact_extractor_b"]["execution"]["source_access"]["source_sha256"] = "a" * 64
        with self.assertRaises(CardGenerationError):
            _validate_workflow_result(corrupted)

    def test_failed_role_stops_workflow_before_next_agent(self):
        directory = self.root / "workflow"
        directory.mkdir()
        workflow = WorkflowFixture(directory)
        workflow.config = replace(workflow.config, protocol_version=LOCAL_PATH_PROTOCOL_VERSION)
        self.f.outputs = [workflow.outputs()[r] for r in REQUIRED_CARD_WORKFLOW_ROLES]
        self.f.outputs[1]["source_read_status"] = "UNREADABLE"
        result = workflow.run(self.f.adapter)
        self.assertFalse(result["ok"])
        self.assertEqual(len(self.f.calls), 2)
        self.assertEqual(result["diagnostic"]["stage"], "fact_extractor_b")

    def test_old_mcp_prompt_is_rejected_before_model(self):
        directory = self.root / "workflow"
        directory.mkdir()
        workflow = WorkflowFixture(directory)
        workflow.config = replace(workflow.config, protocol_version=LOCAL_PATH_PROTOCOL_VERSION)
        workflow.config.fact_extraction_prompt_file.write_text(
            '---\nprompt_version: "old"\n---\n调用 hydro_pdf_reader.read_full_source_pdf', encoding="utf-8")
        result = workflow.run(self.f.adapter)
        self.assertEqual(result["error"]["code"], "MULTI_AGENT_WORKFLOW_CONFIG_INVALID")
        self.f.runner.assert_not_called()

    def test_shipped_configuration_selects_local_path_and_new_prompts(self):
        for name in ("config.json", "config.example.json"):
            app = load_config(ASSETS.parent / "config" / name, group_id=42)
            adapter = build_card_generator_adapter(app.card_generator)
            self.assertIsInstance(adapter.delegate, CodexLocalPdfAdapter)
            from hydro_platform.card_generators.single_agent import SingleAgentCardGeneratorAdapter
            self.assertIsInstance(adapter, SingleAgentCardGeneratorAdapter)
            self.assertEqual(app.card_generator.workflow_mode, "single_agent")
            self.assertIsNone(app.card_generator.multi_agent_workflow)
            self.assertEqual(app.paths.evidence_card_generation_prompt_file.name, "evidence-card-generation-v8.md")

    def test_mismatched_adapter_protocol_and_escaping_prompt_rejected(self):
        data = json.loads(self.f.config_file.read_text())
        data["card_generator"]["pdf_reader"]["adapter"] = "local_path"
        self.f.config_file.write_text(json.dumps(data))
        with self.assertRaises(ConfigError):
            load_config(self.f.config_file)
        data["card_generator"]["multi_agent_workflow"]["protocol_version"] = LOCAL_PATH_PROTOCOL_VERSION
        self.f.config_file.write_text(json.dumps(data))
        self.assertEqual(load_config(self.f.config_file).card_generator.pdf_reader.adapter, "local_path")
        data["card_generator"]["pdf_direct_trial"] = {"prompt_file": "automation/prompts/pdf-direct-read-trial-v2.md",
            "schema_file": "automation/schemas/pdf-direct-read-trial-output.schema.json", "timeout_seconds": 1200,
            "reading_prompt_file": "../outside.md"}
        self.f.config_file.write_text(json.dumps(data))
        with self.assertRaises(ConfigError):
            load_config(self.f.config_file)


class DirectGenerationAdapter(FakeAdapter):
    def generate(self, prompt, **kwargs):
        result = super().generate(prompt, **kwargs)
        access = local_access(PDF_HASH)
        result["source_access"] = access
        result["workflow"]["protocol_version"] = LOCAL_PATH_PROTOCOL_VERSION
        result["workflow"]["gates"].update(full_pdf_access_each_role=False, source_identity_each_role=True, reading_report_each_role=True)
        result["quality_audit"].update(source_pdf_sha256=PDF_HASH, roles={role: {
            "execution": {"isolated": True, "source_access": deepcopy(access)}} for role in REQUIRED_CARD_WORKFLOW_ROLES})
        return result


class DirectCardPersistenceTests(unittest.TestCase):
    def test_full_provider_formal_write_remains_loadable_and_idempotent(self):
        digest = hashlib.sha256(b"%PDF-1.7\nfixture").hexdigest()
        with tempfile.TemporaryDirectory() as directory, patch("test_card_generation.PDF_HASH", digest):
            root = Path(directory)
            card = GenerationFixture(root)
            (root / "workflow").mkdir()
            workflow = WorkflowFixture(root / "workflow")
            local = LocalProviderFixture(root / "provider")
            outputs = workflow.outputs()
            outputs["card_synthesizer"]["card_body_markdown"] = VALID_BODY
            local.outputs = [outputs[r] for r in REQUIRED_CARD_WORKFLOW_ROLES]
            adapter = MultiAgentCardGeneratorAdapter(local.adapter, replace(workflow.config, protocol_version=LOCAL_PATH_PROTOCOL_VERSION))
            self.assertEqual(card.generate(adapter)["action"], "GENERATED")
            manifest = load_evidence_manifest(card.package / "manifest.json")
            self.assertEqual(manifest["generation"]["generator_adapter"], "codex_cli")
            self.assertFalse(manifest["generation"]["source_access_verified"])
            self.assertEqual(card.generate(adapter)["action"], "SKIPPED_EXISTING_CARD")
            self.assertEqual(len(local.calls), 6)

    def test_full_six_role_path_pipeline_saves_trial_with_real_orchestrators(self):
        digest = hashlib.sha256(b"%PDF-1.7\nfixture").hexdigest()
        with tempfile.TemporaryDirectory() as directory, patch("test_card_generation.PDF_HASH", digest):
            root = Path(directory)
            card = GenerationFixture(root)
            (root / "workflow").mkdir()
            workflow = WorkflowFixture(root / "workflow")
            local = LocalProviderFixture(root / "provider")
            outputs = workflow.outputs()
            outputs["card_synthesizer"]["card_body_markdown"] = VALID_BODY
            local.outputs = [outputs[r] for r in REQUIRED_CARD_WORKFLOW_ROLES]
            adapter = MultiAgentCardGeneratorAdapter(local.adapter, replace(workflow.config, protocol_version=LOCAL_PATH_PROTOCOL_VERSION))
            protected = [card.pdf, card.package / "card.md", card.package / "manifest.json", card.task_path]
            before = [p.read_bytes() for p in protected]
            result = card.trial(adapter)
            self.assertTrue(result["ok"], result)
            self.assertEqual(len(local.calls), 6)
            self.assertEqual(before, [p.read_bytes() for p in protected])
            audit = json.loads((Path(result["trial_path"]) / "quality-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(set(audit["roles"]), set(REQUIRED_CARD_WORKFLOW_ROLES))
            self.assertEqual(audit["source_pdf_sha256"], digest)

    def test_trial_saves_new_card_without_changing_production(self):
        with tempfile.TemporaryDirectory() as directory:
            f = GenerationFixture(Path(directory))
            f.generate(FakeAdapter())
            before = [p.read_bytes() for p in (f.package / "card.md", f.package / "manifest.json", f.task_path)]
            result = f.trial(DirectGenerationAdapter())
            self.assertEqual(result["action"], "VALIDATED_TRIAL_SAVED")
            self.assertEqual(before, [p.read_bytes() for p in (f.package / "card.md", f.package / "manifest.json", f.task_path)])
            self.assertTrue((Path(result["trial_path"]) / "quality-audit.json").exists())

    def test_formal_manifest_is_truthful_and_readable_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            f = GenerationFixture(Path(directory))
            adapter = DirectGenerationAdapter()
            self.assertTrue(f.generate(adapter)["ok"])
            manifest_path = f.package / "manifest.json"
            manifest = load_evidence_manifest(manifest_path)
            self.assertFalse(manifest["generation"]["source_access_verified"])
            self.assertIsNone(manifest["generation"]["source_pages_served"])
            self.assertEqual(f.generate(adapter)["action"], "SKIPPED_EXISTING_CARD")
            self.assertEqual(len(adapter.calls), 1)
            for delta in ({"source_access_verified": True}, {"source_access_server": "fake-mcp"}, {"source_pages_served": 12}):
                wrong = deepcopy(manifest)
                wrong["generation"].update(delta)
                manifest_path.write_text(json.dumps(wrong), encoding="utf-8")
                with self.assertRaises(EvidencePackageError):
                    load_evidence_manifest(manifest_path)

    def test_claims_cannot_impersonate_independent_verification(self):
        good = local_access("a" * 64)
        for delta in ({"verified": True}, {"full_read_verified": True}, {"visual_understanding_verified": True},
                      {"source_identity_verified": False}, {"sandbox_preflight_passed": False},
                      {"command_event_count": 0}, {"page_count": True}, {"pages_served": 12}):
            self.assertFalse(source_access_acceptable({**good, **delta}))


if __name__ == "__main__":
    unittest.main()
