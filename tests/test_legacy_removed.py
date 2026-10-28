"""Guards for the removal of the legacy ``--item-key`` evidence-package stack.

The platform now offers exactly two executors -- ``in_session`` (an agent writes
``response.json``) and ``direct`` (one HTTP call) -- and one single-paper entry
point, ``--paper-input``. These tests fail if any of the removed surface comes
back, and they still prove that a historical v1 draft stays readable.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydrolitagent.cards import card_validation as gate
from hydrolitagent.cards import cli
from hydrolitagent.cards.adapters.runners import registry
from hydrolitagent.cards.config import load_config
from hydrolitagent.cards._paths import ASSETS_DIR
from card_fixtures import legacy_draft_case  # noqa: F401 - a pytest fixture

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDS_DIR = REPO_ROOT / "hydrolitagent" / "cards"


def test_evidence_generate_has_no_item_key_and_no_pipeline_flag():
    parser = cli._parser()
    help_text = parser.format_help() + parser._subparsers._group_actions[0].choices[
        "evidence-generate"
    ].format_help()

    assert "--item-key" not in help_text
    assert "--pipeline" not in help_text
    for argv in (
        ["evidence-generate", "--item-key", "ABCD1234"],
        ["evidence-generate", "--paper-input", "input.json", "--pipeline", "legacy"],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)


def test_evidence_generate_requires_a_paper_input_record():
    parser = cli._parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["evidence-generate"])


# Assembled from fragments on purpose: a repository-wide grep for the removed
# stack must not match the guard that forbids it.
@pytest.mark.parametrize("module", [
    "hydrolitagent.cards.card_" + "generation",
    "hydrolitagent.cards.card_" + "draft",
    "hydrolitagent.cards.card_" + "generators",
    "hydrolitagent.cards.infrastructure." + "decoding",
    "hydrolitagent.cards." + "source_access",
    "hydrolitagent.cards.domain." + "roles",
])
def test_removed_modules_are_gone(module):
    with pytest.raises(ImportError):
        __import__(module)


def test_registry_offers_only_the_two_executors():
    assert registry.ids() == ("direct", "in_session")
    assert registry.planned_ids() == ()


# Assembled from fragments on purpose (see above).
REMOVED_NAMES = (
    "card_" + "generators",
    "generate_" + "evidence_card",
    "generate_" + "subject_card_draft",
    "sync_" + "evidence_packages",
    "openai_" + "compatible",
    "Claude" + "MarkdownRunner",
    "Codex" + "MarkdownRunner",
    "CODEX_" + "PDF_",
    "codex_" + "cli",
    "resolve_" + "pipeline_mode",
)


@pytest.mark.parametrize("name", REMOVED_NAMES)
def test_cards_package_does_not_mention_removed_surface(name):
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted(CARDS_DIR.rglob("*.py"))
        if name in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"{name} 仍出现在：{offenders}"


def test_shipped_config_has_no_legacy_generator_keys():
    for name in ("config.json", "config.example.json"):
        data = json.loads(
            (ASSETS_DIR / "config" / name).read_text(encoding="utf-8")
        )
        card_generator = data["card_generator"]
        assert "proxy" not in card_generator
        assert "connection_guard" not in card_generator
        assert "adapter" not in card_generator
        assert "executable" not in card_generator
        assert card_generator["runner"] in registry.ids()


def test_old_v1_draft_is_still_readable_as_legacy_read_only(legacy_draft_case):
    app, draft, record, path, input_path = legacy_draft_case

    report = gate.validate_subject_card(app, draft, record)
    assert report["status"] == "PASS", report
    assert report["report_mode"] == "LEGACY_READ_ONLY"
    assert report["draft_pipeline"] == "legacy"

    saved = gate.validate_subject_card_file(app, path, input_path)
    assert saved["ok"], saved
    assert saved["report_mode"] == "LEGACY_READ_ONLY"


def test_read_prompt_and_template_bundle_live_in_the_application_layer():
    from hydrolitagent.cards.application.prompts import (
        build_template_prompt,
        load_template_bundle,
        read_prompt,
    )

    assets = gate.ValidationAssets.from_root()
    prompt = read_prompt(assets.generation_prompt)
    catalog, templates = load_template_bundle(assets.templates_dir, assets.catalog_file)
    assert prompt["version"]
    assert catalog["catalog_version"]
    assert build_template_prompt(prompt, {"run_id": "x"}, templates).startswith(
        prompt["content"].rstrip()[:20]
    )


def test_shipped_example_still_passes_without_a_model():
    root = ASSETS_DIR / "examples/subject-card-validation"
    report = gate.validate_subject_card(
        None,
        gate._read_json(root / "draft.json"),
        gate._read_json(root / "paper-input.json"),
    )
    assert report["ok"], report


def test_defaults_name_the_in_session_executor():
    config = load_config(ASSETS_DIR / "config/config.example.json", group_id=42)
    assert config.card_generator.runner == "in_session"
