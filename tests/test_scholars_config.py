from __future__ import annotations

from pathlib import Path

import pytest

from hydrolitagent.scholars.config import load_config
from hydrolitagent.scholars.errors import ConfigError


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "scholars.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_default_config_loads_repo_file() -> None:
    config = load_config()
    assert config.identity.institution_id == "I27357992"
    assert config.query.from_date.isoformat() == "2021-01-01"
    assert "article" in config.query.work_types


def test_custom_values(tmp_path) -> None:
    path = write_config(
        tmp_path,
        """
[identity]
institution_id = "I123"
institution_name = "测试大学"
include_past_affiliations = false
max_author_works_count = 100

[query]
from_date = "2022-01-01"
to_date = "2025-12-31"
work_types = ["article", "conference-paper"]
max_works = 200

[openalex]
per_page = 50
max_retries = 1

[output]
root = "outputs/custom"
""",
    )
    config = load_config(path)
    assert config.identity.institution_id == "I123"
    assert config.identity.institution_name == "测试大学"
    assert config.query.from_date.isoformat() == "2022-01-01"
    assert config.query.to_date.isoformat() == "2025-12-31"
    assert config.query.work_types == ("article", "conference-paper")
    assert config.openalex.per_page == 50
    assert config.output.root.name == "custom"


def test_invalid_work_type(tmp_path) -> None:
    path = write_config(tmp_path, '[query]\nwork_types = ["nonsense"]\n')
    with pytest.raises(ConfigError, match="未知作品类型"):
        load_config(path)


def test_api_key_in_toml_rejected(tmp_path) -> None:
    path = write_config(tmp_path, '[openalex]\napi_key = "secret"\n')
    with pytest.raises(ConfigError, match="api_key"):
        load_config(path)


def test_to_date_before_from_date(tmp_path) -> None:
    path = write_config(tmp_path, '[query]\nfrom_date = "2024-01-01"\nto_date = "2023-01-01"\n')
    with pytest.raises(ConfigError, match="to_date"):
        load_config(path)


def test_per_page_upper_bound(tmp_path) -> None:
    path = write_config(tmp_path, "[openalex]\nper_page = 200\n")
    with pytest.raises(ConfigError, match="per_page"):
        load_config(path)


def test_missing_explicit_config(tmp_path) -> None:
    with pytest.raises(ConfigError, match="不存在"):
        load_config(tmp_path / "missing.toml")


def test_api_key_from_environment(tmp_path, monkeypatch) -> None:
    path = write_config(tmp_path, "[openalex]\napi_key_env = \"MY_OPENALEX_KEY\"\n")
    monkeypatch.setenv("MY_OPENALEX_KEY", "abc123")
    config = load_config(path)
    assert config.api_key == "abc123"


def test_overrides(tmp_path) -> None:
    path = write_config(tmp_path, "")
    config = load_config(
        path,
        overrides={
            "institution_id": "I999",
            "from_date": "2020-01-01",
            "work_types": ["review"],
            "output_root": "outputs/override",
        },
    )
    assert config.identity.institution_id == "I999"
    assert config.query.from_date.isoformat() == "2020-01-01"
    assert config.query.work_types == ("review",)
    assert config.output.root.name == "override"
