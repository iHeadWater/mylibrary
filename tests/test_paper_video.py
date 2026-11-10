import hashlib
import subprocess

import pytest

from scripts import paper_video


def test_failed_update_keeps_active_installation(monkeypatch, tmp_path):
    monkeypatch.setattr(paper_video, "CACHE", tmp_path)
    active = tmp_path / "active.json"
    previous = {"directory": "previous", "commit": "old"}
    paper_video.write_json(active, previous)

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "git clone")

    monkeypatch.setattr(paper_video, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        paper_video.setup()
    assert paper_video.read_json(active) == previous


def test_prepare_records_local_and_zotero_inputs(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    output = tmp_path / "outputs"
    monkeypatch.setattr(paper_video, "CACHE", cache)
    monkeypatch.setattr(paper_video, "OUTPUT", output)
    workshop = cache / "installed/workshop"
    workshop.mkdir(parents=True)
    (workshop / "scenes.example.json").write_text("{}", encoding="utf-8")
    (cache / "installed/upstream/skills/paper2video").mkdir(parents=True)
    paper_video.write_json(cache / "active.json", {"directory": "installed", "commit": "abc"})
    pdf = tmp_path / "论文.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
    record = tmp_path / "input.json"
    zotero = {
        "status": "READY", "item": {"item_key": "ABCD1234"},
        "pdf": {"local_path": str(pdf), "sha256": sha256},
    }
    paper_video.write_json(record, zotero)

    paper_video.prepare(pdf, None)
    paper_video.prepare(None, record)

    runs = sorted((output / sha256[:16]).iterdir())
    assert len(runs) == 2
    assert all((run / "input/paper.pdf").read_bytes() == pdf.read_bytes() for run in runs)
    sources = [paper_video.read_json(run / "run.json") for run in runs]
    assert all(source["upstream_commit"] == "abc" for source in sources)
    assert {state["source"].get("status") for state in sources} == {None, "READY"}

    paper_video.write_json(record, {"status": "BLOCKED", "message": "附件不可读"})
    with pytest.raises(ValueError, match="附件不可读"):
        paper_video.prepare(None, record)


def test_finish_reuses_run_after_voice_failure(monkeypatch, tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes/claims.md").touch()
    launcher = paper_video.remotion_launcher(tmp_path)
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    paper_video.write_json(tmp_path / "run.json", {"stage": "prepared"})
    commands = []

    def voice_then_stop(directory, *command, **kwargs):
        commands.append(command)
        if len(commands) == 1 or "scripts/zh_breaks.py" in command:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(paper_video, "run", voice_then_stop)
    monkeypatch.setattr(paper_video, "check_voice", lambda directory: None)
    with pytest.raises(subprocess.CalledProcessError):
        paper_video.finish(tmp_path)
    assert paper_video.read_json(tmp_path / "run.json")["stage"] == "prepared"
    with pytest.raises(subprocess.CalledProcessError):
        paper_video.finish(tmp_path)
    assert paper_video.read_json(tmp_path / "run.json")["stage"] == "voiced"
    assert commands[0] == commands[1]
