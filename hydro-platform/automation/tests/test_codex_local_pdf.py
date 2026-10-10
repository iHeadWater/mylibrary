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
from hydrolitagent.cards.card_generators import build_card_generator_adapter
from hydrolitagent.cards.card_generators.codex_local_pdf import CodexLocalPdfAdapter
from hydrolitagent.cards.card_generation import CardGenerationError, _validate_workflow_result
from hydrolitagent.cards.config import ConfigError, LOCAL_PATH_PROTOCOL_VERSION, REQUIRED_CARD_WORKFLOW_ROLES, load_config
from hydrolitagent.cards.evidence_packages import EvidencePackageError, load_evidence_manifest
from hydrolitagent.cards.source_access import source_access_acceptable
from test_card_generator import command_result, smoke_jsonl
from test_config import write_config
from card_generator_fixtures import common
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

if __name__ == "__main__":
    unittest.main()
