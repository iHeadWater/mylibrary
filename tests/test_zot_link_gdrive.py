"""Tests for ``hydrolitagent/zotero/zot_link_gdrive.py`` — linked_file by item key.

Regression focus: this script used to read ONLY ``~/.config/zot/config.toml``
with hard subscripts (``config["zotero"]["library_id"]``), so on a bare host —
where credentials live in the repo ``.env`` — it raised ``FileNotFoundError``,
and a TOML missing a key raised ``KeyError``.  It is also the only tool in the
repo that attaches a PDF to an item that ALREADY exists.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from hydrolitagent.zotero import zot_link_gdrive as zlg

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_credentials(monkeypatch, *, library_id="12345", api_key="test-key"):
    """Set the ZOTERO_* env vars; pass None to delete one (simulating absence)."""
    for name, value in (("ZOTERO_LIBRARY_ID", library_id), ("ZOTERO_API_KEY", api_key)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def _isolate_from_repo_dotenv(monkeypatch):
    """Stop the repo's real .env from leaking into credential assertions."""
    monkeypatch.setattr(zlg, "_load_dotenv_fallback", lambda: None)


def _point_at_missing_config(monkeypatch, tmp_path):
    """Point ZOTERO_CONFIG_PATH at a file that does not exist (the bare-host case)."""
    monkeypatch.setenv("ZOTERO_CONFIG_PATH", str(tmp_path / "no-such-config.toml"))


def _wire_mock_client(monkeypatch, argv, *, children=(), create_result=None):
    """Patch sys.argv + the pyzotero client. Returns the mock client."""
    monkeypatch.setattr(sys, "argv", ["zot-link-gdrive", *argv])

    mock_client = MagicMock()
    mock_client.item_template.side_effect = lambda t, *a: {"itemType": t}
    mock_client.children.return_value = list(children)
    mock_client.create_items.return_value = create_result or {"success": {"0": "NEWATT01"}}

    mock_zt_module = MagicMock()
    mock_zt_module.Zotero.return_value = mock_client
    monkeypatch.setattr(zlg, "zt", mock_zt_module)
    return mock_client


# ---------------------------------------------------------------------------
# _parse_env_text
# ---------------------------------------------------------------------------


def test_parse_env_text_extracts_only_credential_keys():
    """Unrelated .env entries and malformed lines are dropped, not propagated."""
    text = (
        "# a comment\n"
        "\n"
        "ZOTERO_LIBRARY_ID=12345\n"
        "ZOTERO_API_KEY=abc\n"
        "SOME_OTHER_SECRET=should-not-leak\n"
        "MALFORMED_LINE_WITHOUT_EQUALS\n"
    )
    assert zlg._parse_env_text(text) == {
        "ZOTERO_LIBRARY_ID": "12345",
        "ZOTERO_API_KEY": "abc",
    }


def test_parse_env_text_strips_quotes_and_spacing():
    text = 'ZOTERO_API_KEY = "quoted-key" \nZOTERO_LIBRARY_ID=\'99\'\n'
    assert zlg._parse_env_text(text) == {
        "ZOTERO_API_KEY": "quoted-key",
        "ZOTERO_LIBRARY_ID": "99",
    }


def test_parse_env_text_empty_input():
    assert zlg._parse_env_text("") == {}


# ---------------------------------------------------------------------------
# _resolve_credentials
# ---------------------------------------------------------------------------


def test_resolve_credentials_uses_env_without_any_toml(monkeypatch, tmp_path):
    """The bare-host case: no TOML at all used to raise FileNotFoundError."""
    _set_credentials(monkeypatch)
    _isolate_from_repo_dotenv(monkeypatch)
    _point_at_missing_config(monkeypatch, tmp_path)

    assert zlg._resolve_credentials() == ("12345", "test-key")


def test_resolve_credentials_toml_overrides_env(monkeypatch, tmp_path):
    """Container path unchanged: TOML values win when present."""
    _set_credentials(monkeypatch, library_id="env-lib", api_key="env-key")
    _isolate_from_repo_dotenv(monkeypatch)
    cfg = tmp_path / "zot.toml"
    cfg.write_text('[zotero]\nlibrary_id = "toml-lib"\napi_key = "toml-key"\n', encoding="utf-8")
    monkeypatch.setenv("ZOTERO_CONFIG_PATH", str(cfg))

    assert zlg._resolve_credentials() == ("toml-lib", "toml-key")


def test_resolve_credentials_toml_missing_key_falls_back_to_env(monkeypatch, tmp_path):
    """Per-key fallback: a TOML with only library_id used to raise KeyError."""
    _set_credentials(monkeypatch, library_id="env-lib", api_key="env-key")
    _isolate_from_repo_dotenv(monkeypatch)
    cfg = tmp_path / "zot.toml"
    cfg.write_text('[zotero]\nlibrary_id = "toml-lib"\n', encoding="utf-8")
    monkeypatch.setenv("ZOTERO_CONFIG_PATH", str(cfg))

    assert zlg._resolve_credentials() == ("toml-lib", "env-key")


def test_resolve_credentials_unparsable_toml_falls_back_to_env(monkeypatch, tmp_path):
    """A corrupt TOML must not take the whole script down."""
    _set_credentials(monkeypatch)
    _isolate_from_repo_dotenv(monkeypatch)
    cfg = tmp_path / "zot.toml"
    cfg.write_text("this is not valid toml {{{", encoding="utf-8")
    monkeypatch.setenv("ZOTERO_CONFIG_PATH", str(cfg))

    assert zlg._resolve_credentials() == ("12345", "test-key")


def test_resolve_credentials_returns_empty_when_nothing_set(monkeypatch, tmp_path):
    _set_credentials(monkeypatch, library_id=None, api_key=None)
    _isolate_from_repo_dotenv(monkeypatch)
    _point_at_missing_config(monkeypatch, tmp_path)

    assert zlg._resolve_credentials() == ("", "")


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def test_main_links_attachment_with_env_only(monkeypatch, tmp_path):
    """End-to-end bare-host regression: env-only credentials now create the link."""
    _set_credentials(monkeypatch)
    _isolate_from_repo_dotenv(monkeypatch)
    _point_at_missing_config(monkeypatch, tmp_path)
    mock_client = _wire_mock_client(monkeypatch, ["EXIST123", "paper.pdf"])

    zlg.main()

    assert mock_client.create_items.call_count == 1
    created = mock_client.create_items.call_args_list[0][0][0][0]
    assert created["parentItem"] == "EXIST123"
    assert created["path"] == "attachments:paper.pdf"
    assert created["title"] == "paper.pdf"
    assert created["contentType"] == "application/pdf"


def test_main_exits_with_readable_error_when_no_credentials(monkeypatch, tmp_path, capsys):
    """Missing credentials give a clear message, not FileNotFoundError/KeyError."""
    _set_credentials(monkeypatch, library_id=None, api_key=None)
    _isolate_from_repo_dotenv(monkeypatch)
    _point_at_missing_config(monkeypatch, tmp_path)
    _wire_mock_client(monkeypatch, ["EXIST123", "paper.pdf"])

    with pytest.raises(SystemExit) as exc:
        zlg.main()

    assert exc.value.code == 3
    err = capsys.readouterr().err
    assert "credentials not found" in err
    assert "ZOTERO_API_KEY" in err


def test_main_skips_when_same_slot_is_already_linked(monkeypatch, tmp_path, capsys):
    """Running it twice must not leave two pointers to the same file."""
    _set_credentials(monkeypatch)
    _isolate_from_repo_dotenv(monkeypatch)
    _point_at_missing_config(monkeypatch, tmp_path)
    mock_client = _wire_mock_client(
        monkeypatch,
        ["EXIST123", "paper.pdf"],
        children=[{
            "key": "OLDATT01",
            "data": {"itemType": "attachment", "path": "attachments:paper.pdf"},
        }],
    )

    with pytest.raises(SystemExit) as exc:
        zlg.main()

    assert exc.value.code == 0
    assert mock_client.create_items.call_count == 0
    assert "Already linked" in capsys.readouterr().out


def test_main_still_links_when_only_a_different_slot_exists(monkeypatch, tmp_path):
    """A different path is a different file — linking is still allowed."""
    _set_credentials(monkeypatch)
    _isolate_from_repo_dotenv(monkeypatch)
    _point_at_missing_config(monkeypatch, tmp_path)
    mock_client = _wire_mock_client(
        monkeypatch,
        ["EXIST123", "paper.pdf"],
        children=[{
            "key": "OTHERATT",
            "data": {"itemType": "attachment", "path": "attachments:other.pdf"},
        }],
    )

    zlg.main()

    assert mock_client.create_items.call_count == 1


def test_main_dry_run_needs_no_credentials(monkeypatch, capsys):
    """--dry-run stays offline: no client, no credential requirement."""
    _set_credentials(monkeypatch, library_id=None, api_key=None)
    monkeypatch.setattr(
        sys, "argv", ["zot-link-gdrive", "--dry-run", "EXIST123", "paper.pdf"]
    )

    with pytest.raises(SystemExit) as exc:
        zlg.main()

    assert exc.value.code == 0
    assert "attachments:paper.pdf" in capsys.readouterr().out


def test_main_usage_exit_code_without_args(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["zot-link-gdrive", "only-one-arg"])

    with pytest.raises(SystemExit) as exc:
        zlg.main()

    assert exc.value.code == 2
    assert "Usage" in capsys.readouterr().err


def test_main_reports_api_failure(monkeypatch, tmp_path, capsys):
    """A rejected create exits 5 with the API's message."""
    _set_credentials(monkeypatch)
    _isolate_from_repo_dotenv(monkeypatch)
    _point_at_missing_config(monkeypatch, tmp_path)
    _wire_mock_client(
        monkeypatch,
        ["EXIST123", "paper.pdf"],
        create_result={"success": {}, "failed": {"0": {"message": "Invalid key"}}},
    )

    with pytest.raises(SystemExit) as exc:
        zlg.main()

    assert exc.value.code == 5
    assert "Invalid key" in capsys.readouterr().err
