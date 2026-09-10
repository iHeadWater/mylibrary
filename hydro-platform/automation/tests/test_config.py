from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from hydro_platform.config import ConfigError, load_config


def write_config(root: Path, overrides: dict[str, object] | None = None) -> Path:
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    data: dict[str, object] = {
        "schema_version": 1,
        "paths": {
            "project_root": "..",
            "runtime_dir": ".runtime",
            "snapshot_file": ".runtime/zotero-snapshot.json",
            "tasks_file": ".runtime/tasks.json",
            "lock_file": ".runtime/worker.lock",
            "logs_dir": ".runtime/logs",
            "card_trials_dir": ".runtime/card-trials",
            "evidence_packs_dir": "evidence-packs",
            "templates_dir": "templates",
            "evidence_card_templates_dir": "templates/evidence-cards",
            "evidence_card_template_catalog_file": "templates/evidence-cards/_catalog.json",
            "evidence_card_generation_prompt_file": "automation/prompts/evidence-card-generation-v4.md",
            "card_generation_output_schema_file": "automation/schemas/card-generation-output.schema.json",
            "themes_dir": "themes",
            "members_dir": "members",
            "activity_dir": "activity",
            "reports_dir": "reports",
            "prompts_dir": "automation/prompts",
            "schemas_dir": "automation/schemas",
        },
        "zotero": {
            "base_url": "http://127.0.0.1:23119",
            "group_id": 42,
            "timeout_seconds": 5,
            "process_timeout_seconds": 5,
        },
        "scan": {"page_size": 100},
        "pdf_gate": {
            "min_file_size_bytes": 1024,
            "min_text_characters": 1000,
            "hash_chunk_size_bytes": 1048576,
        },
        "tasks": {
            "lease_seconds": 1800,
            "lock_stale_seconds": 300,
            "max_history_entries": 100,
        },
        "card_generator": {
            "adapter": "codex_cli",
            "executable": "codex",
            "auth_mode": "chatgpt_account",
            "preflight_timeout_seconds": 10,
            "model": None,
            "reasoning_effort": None,
            "smoke_test_timeout_seconds": 120,
            "generation_timeout_seconds": 900,
            "pdf_reader": {
                "adapter": "project_mcp",
                "server_name": "hydro_pdf_reader",
                "python_executable": None,
                "server_file": "automation/src/hydro_platform/pdf_reader_mcp.py",
                "pdfinfo_executable": "pdfinfo",
                "pdftotext_executable": "pdftotext",
                "pdftoppm_executable": "pdftoppm",
                "render_dpi": 120,
                "max_pages_per_call": 4,
                "output_token_limit": 60000,
                "startup_timeout_seconds": 15,
                "tool_timeout_seconds": 120,
            },
            "multi_agent_workflow": {
                "protocol_version": "rough-card-multi-agent-v1",
                "prompts": {
                    "fact_extraction": "automation/prompts/fact-extraction-v1.md",
                    "fact_adjudication": "automation/prompts/fact-adjudication-v1.md",
                    "critical_analysis": "automation/prompts/critical-analysis-v1.md",
                    "adversarial_review": "automation/prompts/adversarial-review-v1.md",
                },
                "schemas": {
                    "fact_extraction": "automation/schemas/fact-extraction-output.schema.json",
                    "fact_adjudication": "automation/schemas/fact-adjudication-output.schema.json",
                    "critical_analysis": "automation/schemas/critical-analysis-output.schema.json",
                    "adversarial_review": "automation/schemas/adversarial-review-output.schema.json",
                },
                "quality_gate": {
                    "minimum_verified_facts": 8,
                    "minimum_critical_analyses": 5,
                    "minimum_adversarial_challenges": 5,
                    "maximum_unresolved_high_severity": 0,
                },
                "roles": {
                    name: {
                        "model": None,
                        "reasoning_effort": "high",
                        "timeout_seconds": 1200,
                    }
                    for name in (
                        "fact_extractor_a",
                        "fact_extractor_b",
                        "fact_adjudicator",
                        "critical_analyst",
                        "card_synthesizer",
                        "adversarial_reviewer",
                    )
                },
            },
        },
    }
    if overrides:
        for section, value in overrides.items():
            if isinstance(value, dict) and isinstance(data.get(section), dict):
                data[section] = {**data[section], **value}  # type: ignore[arg-type]
            else:
                data[section] = value
    path = config_dir / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class ConfigTests(unittest.TestCase):
    def test_relative_paths_resolve_from_configured_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(root)
            previous_cwd = Path.cwd()
            unrelated = root / "unrelated"
            unrelated.mkdir()
            try:
                os.chdir(unrelated)
                config = load_config(config_path, require_group=True)
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(config.paths.project_root, root)
            self.assertEqual(config.paths.snapshot_file, root / ".runtime" / "zotero-snapshot.json")
            self.assertEqual(config.paths.evidence_packs_dir, root / "evidence-packs")
            self.assertEqual(
                config.paths.evidence_card_templates_dir,
                root / "templates" / "evidence-cards",
            )
            self.assertEqual(
                config.paths.evidence_card_template_catalog_file,
                root / "templates" / "evidence-cards" / "_catalog.json",
            )
            self.assertEqual(
                config.paths.evidence_card_generation_prompt_file,
                root / "automation" / "prompts" / "evidence-card-generation-v4.md",
            )
            self.assertEqual(
                config.paths.card_generation_output_schema_file,
                root / "automation" / "schemas" / "card-generation-output.schema.json",
            )

    def test_rejects_path_outside_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"paths": {"project_root": "..", "evidence_packs_dir": "../outside"}},
            )

            with self.assertRaisesRegex(ConfigError, "evidence_packs_dir"):
                load_config(config_path)

    def test_rejects_snapshot_outside_runtime_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"paths": {"project_root": "..", "snapshot_file": "state/snapshot.json"}},
            )

            with self.assertRaisesRegex(ConfigError, "runtime_dir"):
                load_config(config_path)

    def test_rejects_evidence_template_directory_outside_templates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"paths": {"evidence_card_templates_dir": "evidence-card-templates"}},
            )

            with self.assertRaisesRegex(ConfigError, "templates_dir"):
                load_config(config_path)

    def test_rejects_template_catalog_outside_evidence_template_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {
                    "paths": {
                        "evidence_card_template_catalog_file": "templates/_catalog.json"
                    }
                },
            )

            with self.assertRaisesRegex(ConfigError, "evidence_card_templates_dir"):
                load_config(config_path)

    def test_rejects_generation_prompt_outside_prompt_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {
                    "paths": {
                        "evidence_card_generation_prompt_file": "templates/prompt.md"
                    }
                },
            )

            with self.assertRaisesRegex(ConfigError, "prompts_dir"):
                load_config(config_path)

    def test_rejects_generation_schema_outside_schema_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {
                    "paths": {
                        "card_generation_output_schema_file": "automation/output.json"
                    }
                },
            )

            with self.assertRaisesRegex(ConfigError, "schemas_dir"):
                load_config(config_path)

    def test_allows_custom_loopback_port(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"zotero": {"base_url": "http://localhost:32199"}},
            )

            config = load_config(config_path)

            self.assertEqual(config.zotero.base_url, "http://localhost:32199")

    def test_rejects_missing_required_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(root)
            data = json.loads(config_path.read_text(encoding="utf-8"))
            del data["paths"]["reports_dir"]
            config_path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "reports_dir"):
                load_config(config_path)

    def test_loads_card_generator_preflight_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {
                    "card_generator": {
                        "executable": "C:/Tools/codex.exe",
                        "preflight_timeout_seconds": 12.5,
                    }
                },
            )

            config = load_config(config_path)

            self.assertEqual(config.card_generator.adapter, "codex_cli")
            self.assertEqual(config.card_generator.executable, "C:/Tools/codex.exe")
            self.assertEqual(config.card_generator.auth_mode, "chatgpt_account")
            self.assertEqual(config.card_generator.preflight_timeout_seconds, 12.5)
            self.assertIsNone(config.card_generator.model)
            self.assertIsNone(config.card_generator.reasoning_effort)
            self.assertEqual(config.card_generator.smoke_test_timeout_seconds, 120)
            self.assertEqual(config.card_generator.generation_timeout_seconds, 900)
            self.assertEqual(config.card_generator.pdf_reader.server_name, "hydro_pdf_reader")
            self.assertEqual(config.card_generator.pdf_reader.render_dpi, 120)
            self.assertEqual(
                config.card_generator.pdf_reader.server_file,
                root / "automation" / "src" / "hydro_platform" / "pdf_reader_mcp.py",
            )
            workflow = config.card_generator.multi_agent_workflow
            self.assertIsNotNone(workflow)
            assert workflow is not None
            self.assertEqual(workflow.protocol_version, "rough-card-multi-agent-v1")
            self.assertEqual(len(workflow.roles), 6)
            self.assertEqual(workflow.roles["critical_analyst"].reasoning_effort, "high")

    def test_rejects_missing_required_multi_agent_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(root)
            data = json.loads(config_path.read_text(encoding="utf-8"))
            del data["card_generator"]["multi_agent_workflow"]["roles"][
                "adversarial_reviewer"
            ]
            config_path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "roles 必须且只能包含"):
                load_config(config_path)

    def test_rejects_multi_agent_prompt_outside_prompt_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(root)
            data = json.loads(config_path.read_text(encoding="utf-8"))
            data["card_generator"]["multi_agent_workflow"]["prompts"][
                "fact_extraction"
            ] = "outside.md"
            config_path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "prompts.fact_extraction"):
                load_config(config_path)

    def test_rejects_unknown_multi_agent_protocol_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(root)
            data = json.loads(config_path.read_text(encoding="utf-8"))
            data["card_generator"]["multi_agent_workflow"][
                "protocol_version"
            ] = "skip-review-v1"
            config_path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "protocol_version"):
                load_config(config_path)

    def test_loads_explicit_smoke_test_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"card_generator": {"model": "gpt-test-model"}},
            )

            config = load_config(config_path)

            self.assertEqual(config.card_generator.model, "gpt-test-model")

    def test_loads_explicit_reasoning_effort(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"card_generator": {"reasoning_effort": "HIGH"}},
            )

            config = load_config(config_path)

            self.assertEqual(config.card_generator.reasoning_effort, "high")

    def test_rejects_unknown_card_generator_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"card_generator": {"adapter": "imaginary_api"}},
            )

            with self.assertRaisesRegex(ConfigError, "card_generator.adapter"):
                load_config(config_path)

    def test_rejects_non_chatgpt_auth_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"card_generator": {"auth_mode": "api_key"}},
            )

            with self.assertRaisesRegex(ConfigError, "card_generator.auth_mode"):
                load_config(config_path)

    def test_rejects_empty_card_generator_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"card_generator": {"executable": "  "}},
            )

            with self.assertRaisesRegex(ConfigError, "card_generator.executable"):
                load_config(config_path)

    def test_rejects_nonpositive_generator_preflight_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"card_generator": {"preflight_timeout_seconds": 0}},
            )

            with self.assertRaisesRegex(
                ConfigError,
                "card_generator.preflight_timeout_seconds",
            ):
                load_config(config_path)

    def test_rejects_empty_generator_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"card_generator": {"model": "  "}},
            )

            with self.assertRaisesRegex(ConfigError, "card_generator.model"):
                load_config(config_path)

    def test_rejects_unknown_reasoning_effort(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"card_generator": {"reasoning_effort": "extreme"}},
            )

            with self.assertRaisesRegex(ConfigError, "reasoning_effort"):
                load_config(config_path)

    def test_rejects_nonpositive_smoke_test_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"card_generator": {"smoke_test_timeout_seconds": 0}},
            )

            with self.assertRaisesRegex(
                ConfigError,
                "card_generator.smoke_test_timeout_seconds",
            ):
                load_config(config_path)

    def test_rejects_nonpositive_generation_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {"card_generator": {"generation_timeout_seconds": 0}},
            )

            with self.assertRaisesRegex(
                ConfigError,
                "card_generator.generation_timeout_seconds",
            ):
                load_config(config_path)


if __name__ == "__main__":
    unittest.main()
