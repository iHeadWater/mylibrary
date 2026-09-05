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
            "evidence_packs_dir": "evidence-packs",
            "templates_dir": "templates",
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


if __name__ == "__main__":
    unittest.main()
