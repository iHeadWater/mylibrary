from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from hydrolitagent.cards.config import ConfigError, load_config

def write_config(root: Path, overrides: dict[str, object] | None = None) -> Path:
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    data: dict[str, object] = {
        "schema_version": 1,
        "paths": {
            "project_root": "..",
            "artifact_root": "../",
            "artifact_root_external": True,
            "evidence_cards_dir": "证据卡",
            "themes_vault_dir": "主题",
            "run_records_dir": "运行记录",
            "literature_index_dir": "文献链接",
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
            "workflow_mode": "single_agent",
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

    def test_artifact_root_defaults_to_workspace_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(root)

            config = load_config(config_path)

            workspace = root.parent
            self.assertEqual(config.paths.artifact_root, workspace)
            self.assertTrue(config.paths.artifact_root_external)
            self.assertEqual(config.paths.evidence_cards_dir, workspace / "证据卡")
            self.assertEqual(config.paths.themes_vault_dir, workspace / "主题")
            self.assertEqual(config.paths.run_records_dir, workspace / "运行记录")
            self.assertEqual(config.paths.literature_index_dir, workspace / "文献链接")

    def test_artifact_root_accepts_external_path_with_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            shared = (root.parent / "shared-artifacts").resolve()
            config_path = write_config(
                root,
                {
                    "paths": {
                        "artifact_root": str(shared),
                        "artifact_root_external": True,
                    }
                },
            )

            config = load_config(config_path)

            self.assertEqual(config.paths.artifact_root, shared)
            self.assertTrue(config.paths.artifact_root_external)
            self.assertEqual(config.paths.evidence_cards_dir, shared / "证据卡")
            self.assertEqual(config.paths.themes_vault_dir, shared / "主题")

    def test_rejects_external_artifact_root_without_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root,
                {
                    "paths": {
                        "artifact_root": "../shared-artifacts",
                        "artifact_root_external": False,
                    }
                },
            )

            with self.assertRaisesRegex(ConfigError, "artifact_root_external"):
                load_config(config_path)

    def test_rejects_non_boolean_artifact_root_external(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root, {"paths": {"artifact_root_external": "yes"}}
            )

            with self.assertRaisesRegex(ConfigError, "artifact_root_external"):
                load_config(config_path)

    def test_rejects_artifact_subdir_outside_artifact_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root, {"paths": {"evidence_cards_dir": "../../outside-cards"}}
            )

            with self.assertRaisesRegex(ConfigError, "evidence_cards_dir"):
                load_config(config_path)

    def test_rejects_missing_artifact_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(root)
            data = json.loads(config_path.read_text(encoding="utf-8"))
            del data["paths"]["run_records_dir"]
            config_path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "run_records_dir"):
                load_config(config_path)

    def test_rejects_theme_assets_dir_outside_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = write_config(
                root, {"theme_pipeline": {"assets_dir": "../outside-assets"}}
            )

            with self.assertRaisesRegex(ConfigError, "theme_pipeline.assets_dir"):
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
