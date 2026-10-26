"""Configuration contract for the stage-2 converter.

Stage 2 must not change behaviour: the shipped config has no active converter
(``converter_id="none"``), the pipeline selector defaults to ``legacy`` and the
new ``converter`` section is validated rather than silently accepted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydrolitagent.cards.config import (
    ConfigError,
    ConverterConfig,
    load_config,
    resolve_pipeline_mode,
)

ASSETS_CONFIG = (
    Path(__file__).resolve().parent.parent / "hydrolitagent" / "cards" / "assets" / "config"
)


def _config_with(tmp_path: Path, **converter: object) -> Path:
    data = json.loads((ASSETS_CONFIG / "config.example.json").read_text(encoding="utf-8"))
    # The example carries a placeholder group id; unrelated to this contract.
    data["zotero"]["group_id"] = 42
    data["converter"] = {
        **data.get("converter", {}),
        **converter,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_shipped_config_keeps_the_legacy_pipeline() -> None:
    for name in ("config.json", "config.example.json"):
        # The example carries a placeholder group id; that value is unrelated
        # to this test, so supply the real one explicitly.
        config = load_config(ASSETS_CONFIG / name, group_id=42)
        assert isinstance(config.converter, ConverterConfig)
        assert config.converter.converter_id == "none"
        assert config.converter.mode == "layout"
        assert config.converter.table_mode == "markdown"
        assert config.converter.min_text_coverage == 0.6
        assert config.converter.cache_dir == config.paths.runtime_dir


def test_pipeline_mode_defaults_to_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARD_PIPELINE", raising=False)
    assert resolve_pipeline_mode() == "legacy"
    assert resolve_pipeline_mode({"CARD_PIPELINE": "markdown"}) == "markdown"
    assert resolve_pipeline_mode({"CARD_PIPELINE": " LEGACY "}) == "legacy"


def test_unknown_pipeline_mode_is_rejected() -> None:
    with pytest.raises(ConfigError, match="CARD_PIPELINE"):
        resolve_pipeline_mode({"CARD_PIPELINE": "pdf"})


def test_converter_section_accepts_explicit_values(tmp_path: Path) -> None:
    config = load_config(
        _config_with(
            tmp_path,
            converter_id="pymupdf",
            mode="text",
            table_mode="text",
            extract_figures=False,
            ocr=True,
            min_text_coverage=0.9,
        )
    )
    converter = config.converter
    assert converter.converter_id == "pymupdf"
    assert converter.mode == "text"
    assert converter.table_mode == "text"
    assert converter.extract_figures is False
    assert converter.ocr is True
    assert converter.min_text_coverage == 0.9


def test_unknown_converter_field_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="converter"):
        load_config(_config_with(tmp_path, unknown_field=True))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("converter_id", ""),
        ("mode", "columns"),
        ("table_mode", "html"),
        ("extract_figures", "yes"),
        ("ocr", 1),
        ("min_text_coverage", 1.5),
        ("min_text_coverage", -0.1),
        ("cache_dir", 42),
    ],
)
def test_invalid_converter_values_are_rejected(
    tmp_path: Path, field: str, value: object
) -> None:
    with pytest.raises(ConfigError, match="converter"):
        load_config(_config_with(tmp_path, **{field: value}))


def test_cache_dir_cannot_escape_project_root(tmp_path: Path) -> None:
    outside = Path(tmp_path.anchor) / "outside-cards-cache"
    with pytest.raises(ConfigError, match="converter.cache_dir"):
        load_config(_config_with(tmp_path, cache_dir=str(outside)))
