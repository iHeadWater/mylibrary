"""Auto-refresh of the generated reading layer after a successful write.

``cards index`` stays the manual rebuild command; the same generator also runs
at the end of ``cards run finalize`` and a completed ``themes-run`` so the vault
does not silently go stale. These tests use the real converter and the real CLI
(no model, no network) and assert three things a reader depends on:

* a successful write leaves ``reading_layer`` in the JSON result and files on
  disk;
* ``--no-index`` (and an unfinished theme session) writes nothing;
* a failing refresh is reported, never raised into a completed command.
"""

from __future__ import annotations

import io
import json
import shutil
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hydrolitagent.cards import cli
from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.application import reading_layer
from hydrolitagent.cards.cli import main

from test_config import write_config
from test_markdown_workflow import _record, _write_pdf, grounded_output
from test_theme_session import ThemeSession, session  # noqa: F401 - pytest fixture

PARENT_KEY = "PARENT01"


def _cli(argv) -> tuple[int, dict]:
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = main(argv)
    return code, json.loads(stream.getvalue())


def _config(tmp_path: Path) -> Path:
    """A throwaway workspace whose card assets are copied inside its root."""

    (tmp_path / "templates").mkdir(parents=True, exist_ok=True)
    (tmp_path / "templates" / "evidence-cards").mkdir(exist_ok=True)
    for source in (ASSETS_DIR / "templates" / "evidence-cards").iterdir():
        target = tmp_path / "templates" / "evidence-cards" / source.name
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.write_bytes(source.read_bytes())
    (tmp_path / "automation" / "prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "automation" / "prompts" / "evidence-card-generation-v4.md").write_bytes(
        (ASSETS_DIR / "prompts" / "evidence-card-generation-v8.md").read_bytes()
    )
    # ``write_config`` puts the file in ``<root>/config`` and resolves
    # ``project_root: ".."`` to ``<root>``; the assets must live there too.
    return write_config(tmp_path)


def _prepare(config_path: Path, input_path: Path, run_dir: Path, output_root: Path) -> dict:
    code, result = _cli([
        "run", "prepare",
        "--config", str(config_path),
        "--paper-input", str(input_path),
        "--run-dir", str(run_dir),
        "--output-root", str(output_root),
        "--json",
    ])
    assert code == 0, result
    request = SimpleNamespace(
        workspace=run_dir,
        paper=SimpleNamespace(page_count=result["page_count"]),
    )
    (run_dir / "response.json").write_text(
        json.dumps(grounded_output(request), ensure_ascii=False), encoding="utf-8"
    )
    return result


def _finalize(config_path: Path, input_path: Path, run_dir: Path,
              output_root: Path, *extra: str) -> tuple[int, dict]:
    return _cli([
        "run", "finalize",
        "--config", str(config_path),
        "--paper-input", str(input_path),
        "--run-dir", str(run_dir),
        "--output-root", str(output_root),
        *extra,
        "--json",
    ])


def _single_paper_workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    config_path = _config(tmp_path)
    pdf = _write_pdf(tmp_path / "paper.pdf")
    input_path = tmp_path / "paper-input.json"
    input_path.write_text(json.dumps(_record(pdf), ensure_ascii=False), encoding="utf-8")
    return config_path, input_path, tmp_path / "literature"


def test_single_paper_finalize_refreshes_and_no_index_opts_out(tmp_path: Path) -> None:
    config_path, input_path, output_root = _single_paper_workspace(tmp_path)

    # 1. ``--no-index``: the draft is written, the reading layer is not.
    quiet_run = tmp_path / "run-quiet"
    _prepare(config_path, input_path, quiet_run, output_root)
    code, quiet = _finalize(config_path, input_path, quiet_run, output_root, "--no-index")
    assert code == 0, quiet
    assert quiet["ok"] is True
    assert "reading_layer" not in quiet
    assert not (output_root / "HOME.md").exists()

    # 2. default: the same successful write also refreshes the reader pages.
    run_dir = tmp_path / "run"
    _prepare(config_path, input_path, run_dir, output_root)
    code, result = _finalize(config_path, input_path, run_dir, output_root)
    assert code == 0, result
    assert result["ok"] is True
    layer = result["reading_layer"]
    assert layer["ok"] is True, layer
    assert layer["written"] > 0
    assert layer["unchanged"] == 0
    assert layer["broken_links"] == []
    assert layer["links_checked"] > 0
    assert (output_root / "HOME.md").is_file()
    assert (output_root / "cards" / "INDEX.md").is_file()
    assert (output_root / "cards" / PARENT_KEY / "card.md").is_file()

    # 3. a refresh that blows up is reported, not raised into the command.
    failing_run = tmp_path / "run-failing"
    _prepare(config_path, input_path, failing_run, output_root)

    def boom(root, *, runtime_dir=None):
        raise PermissionError("denied")

    with patch.object(cli, "refresh_reading_layer", boom):
        code, broken = _finalize(config_path, input_path, failing_run, output_root)

    assert code == 0, broken
    assert broken["ok"] is True
    assert broken["reading_layer"]["ok"] is False
    assert broken["reading_layer"]["error"]["code"] == reading_layer.REFRESH_FAILED
    assert "denied" in broken["reading_layer"]["error"]["message"]


def test_refresh_wrapper_never_raises(monkeypatch, tmp_path: Path) -> None:
    def boom(root, *, runtime_dir=None):
        raise OSError("disk full")

    monkeypatch.setattr(reading_layer, "build_reading_layer", boom)

    report = reading_layer.refresh(tmp_path)

    assert report["ok"] is False
    assert report["written"] == 0
    assert report["broken_links"] == []
    assert report["error"]["code"] == reading_layer.REFRESH_FAILED


def test_refresh_counts_written_and_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()

    first = reading_layer.refresh(root, runtime_dir=tmp_path / "runtime")
    second = reading_layer.refresh(root, runtime_dir=tmp_path / "runtime")

    assert first["ok"] is True and second["ok"] is True
    assert first["written"] > 0 and first["unchanged"] == 0
    assert second["written"] == 0 and second["unchanged"] == first["written"]


def test_human_output_names_the_refresh() -> None:
    from hydrolitagent.cards.cli import _render_human

    text = _render_human({
        "operation": "session_finalize",
        "ok": True,
        "card_path": "c",
        "draft_path": "d",
        "literature_root": "out",
        "reading_layer": {
            "ok": True, "written": 2, "unchanged": 1,
            "links_checked": 3, "broken_links": [], "error": None,
        },
    })
    assert "阅读层已刷新：2 个文件（1 未变，3 条链接，0 断链）" in text

    failed = _render_human({
        "operation": "session_finalize",
        "ok": True,
        "card_path": "c",
        "draft_path": "d",
        "literature_root": "out",
        "reading_layer": {
            "ok": False, "written": 0, "unchanged": 0, "links_checked": 0,
            "broken_links": [], "error": {"code": "READING_LAYER_REFRESH_FAILED",
                                          "message": "OSError: disk full"},
        },
    })
    assert "阅读层未刷新 [READING_LAYER_REFRESH_FAILED]" in failed


# --------------------------------------------------------------------------------------
# theme pool
# --------------------------------------------------------------------------------------


def test_theme_finalize_refreshes_only_after_completion(session: ThemeSession) -> None:
    run_dir = session.root / "auto-run"

    with patch("hydrolitagent.cards.theme_session_steps.prepare_pdf_delivery",
               session.delivery):
        code, result = _cli(["run", "prepare", "--theme",
                             "--config", str(session.config_path),
                             "--run-dir", str(run_dir), "--json"])
        assert code == 0, result
        for _ in range(20):
            session.respond(run_dir)
            code, result = _cli(["run", "finalize", "--theme",
                                 "--config", str(session.config_path),
                                 "--run-dir", str(run_dir), "--json"])
            assert code == 0, result
            if result["status"] == "COMPLETED":
                break
            # Intermediate steps keep the pool open: no layer, no files.
            assert "reading_layer" not in result
            assert not (session.root / "HOME.md").exists()
        else:
            raise AssertionError("theme session did not converge within 20 steps")

    assert result["status"] == "COMPLETED"
    layer = result["reading_layer"]
    assert layer["ok"] is True, layer
    assert layer["written"] > 0
    assert (session.root / "HOME.md").is_file()
    assert (session.root / "reading" / "themes").is_dir()


def test_theme_finalize_accepts_no_index(session: ThemeSession) -> None:
    run_dir = session.root / "quiet-run"

    with patch("hydrolitagent.cards.theme_session_steps.prepare_pdf_delivery",
               session.delivery):
        code, result = _cli(["run", "prepare", "--theme",
                             "--config", str(session.config_path),
                             "--run-dir", str(run_dir), "--json"])
        assert code == 0, result
        for _ in range(20):
            session.respond(run_dir)
            code, result = _cli(["run", "finalize", "--theme",
                                 "--config", str(session.config_path),
                                 "--run-dir", str(run_dir), "--no-index", "--json"])
            assert code == 0, result
            if result["status"] == "COMPLETED":
                break
        else:
            raise AssertionError("theme session did not converge within 20 steps")

    assert result["status"] == "COMPLETED"
    assert "reading_layer" not in result
    assert not (session.root / "HOME.md").exists()


def test_themes_run_dry_run_does_not_refresh(session: ThemeSession) -> None:
    code, result = _cli(["themes-run", "--config", str(session.config_path),
                         "--dry-run", "--json"])

    assert code == 0, result
    assert result["status"] == "LOCAL_PREVIEW"
    assert "reading_layer" not in result
    assert not (session.root / "HOME.md").exists()
