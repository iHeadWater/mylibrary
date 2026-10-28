"""The product root has exactly one definition: ``configs/paths.toml``.

Every cards output directory is a subdirectory name inside that root. These
tests pin the derivation so a future change cannot reintroduce a second,
project-root-relative definition of ``themes/`` or ``evidence-packs/``.
"""

from __future__ import annotations

import json
from pathlib import Path

from hydrolitagent.cards.config import load_config


def _write_project(root: Path, *, literature_root: str | None = None,
                   env_root: str | None = None) -> Path:
    (root / "configs").mkdir(parents=True)
    # TOML basic strings treat backslashes as escapes; write POSIX form.
    # The temp project lives outside the installed package root, so an
    # absolute root must declare external = true (same rule as a real repo).
    root_value = (literature_root or "products").replace("\\", "/")
    (root / "configs" / "paths.toml").write_text(
        f'[literature]\nroot = "{root_value}"\nexternal = true\n', encoding="utf-8"
    )
    config_dir = root / "config"
    config_dir.mkdir()
    paths = {
        "project_root": "..",
        "runtime_dir": ".runtime",
        "snapshot_file": ".runtime/zotero-snapshot.json",
        "tasks_file": ".runtime/tasks.json",
        "lock_file": ".runtime/worker.lock",
        "logs_dir": ".runtime/logs",
        "evidence_packs_dir": "evidence-packs",
        "templates_dir": "templates",
        "evidence_card_templates_dir": "templates/evidence-cards",
        "evidence_card_template_catalog_file": "templates/evidence-cards/_catalog.json",
        "evidence_card_generation_prompt_file": "prompts/card.md",
        "themes_dir": "themes",
    }
    if env_root is not None:
        paths["literature_root"] = env_root
    data = {
        "schema_version": 1,
        "paths": paths,
        "zotero": {"base_url": "http://127.0.0.1:23119", "group_id": 42,
                   "timeout_seconds": 5, "process_timeout_seconds": 5},
        "scan": {"page_size": 100},
        "pdf_gate": {"min_file_size_bytes": 1024, "min_text_characters": 1000,
                     "hash_chunk_size_bytes": 1048576},
        "tasks": {"lease_seconds": 1800, "lock_stale_seconds": 300, "max_history_entries": 100},
        "card_generator": {"runner": "in_session", "model": None,
                           "reasoning_effort": None, "generation_timeout_seconds": 900},
    }
    path = config_dir / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_output_dirs_derive_from_the_project_literature_root(tmp_path, monkeypatch):
    monkeypatch.delenv("HYDROLITAGENT_LITERATURE_ROOT", raising=False)
    # A relative root in configs/paths.toml anchors to the installed package
    # root, so an isolated temp project needs the absolute spelling.
    config = load_config(_write_project(tmp_path, literature_root=str(tmp_path / "products")))

    assert config.paths.literature_root == tmp_path / "products"
    assert config.paths.themes_dir == tmp_path / "products" / "themes"
    assert config.paths.evidence_packs_dir == tmp_path / "products" / "evidence-packs"


def test_environment_override_changes_the_derived_root(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDROLITAGENT_LITERATURE_ROOT", str(tmp_path / "elsewhere"))
    config = load_config(_write_project(tmp_path))

    assert config.paths.literature_root == tmp_path / "elsewhere"
    assert config.paths.themes_dir == tmp_path / "elsewhere" / "themes"


def test_explicit_literature_root_wins_for_isolated_tests(tmp_path, monkeypatch):
    monkeypatch.delenv("HYDROLITAGENT_LITERATURE_ROOT", raising=False)
    config = load_config(_write_project(tmp_path, env_root="local-products"))

    assert config.paths.literature_root == tmp_path / "local-products"
    assert config.paths.evidence_packs_dir == tmp_path / "local-products" / "evidence-packs"


def test_output_dirs_cannot_escape_the_literature_root(tmp_path, monkeypatch):
    monkeypatch.delenv("HYDROLITAGENT_LITERATURE_ROOT", raising=False)
    config_path = _write_project(tmp_path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["paths"]["themes_dir"] = "../../outside"
    config_path.write_text(json.dumps(data), encoding="utf-8")

    import pytest
    from hydrolitagent.cards.config import ConfigError

    with pytest.raises(ConfigError, match="literature_root"):
        load_config(config_path)
