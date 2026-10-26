"""Behaviour of ``cards doctor`` and its capability checks.

A doctor is only useful if it (a) works on a machine without Poppler, (b) never
invokes a model or reads a user's paper, and (c) turns a missing dependency into
an actionable ``fix`` instead of a traceback. These tests exercise the probes
directly and the assembled report; the only network path is opt-in and is
monkeypatched, so no test touches Zotero.
"""

from __future__ import annotations

import json
import sys

import pytest

from hydrolitagent.cards import cli
from hydrolitagent.cards.adapters.pdf.doctor import probe_pymupdf
from hydrolitagent.cards.application.doctor import (
    build_report,
    converter_checks,
    runner_checks,
)
from hydrolitagent.cards.composition import build_doctor_report
from hydrolitagent.cards.config import load_config
from hydrolitagent.cards.ports.runner import RunnerDoctor

from test_config import write_config


def _config(tmp_path, *, group_id: int | None = None):
    path = write_config(tmp_path / "app", {"zotero": {"group_id": group_id}})
    return load_config(path, require_group=False)


# --------------------------------------------------------------------------------------
# whole report
# --------------------------------------------------------------------------------------


def test_doctor_is_ok_without_poppler_and_never_invokes_a_model(tmp_path):
    config = _config(tmp_path, group_id=None)

    report = build_doctor_report(config, output_root=tmp_path / "artifacts")

    assert report["ok"] is True, report
    assert report["model_invoked"] is False
    assert report["operation"] == "doctor"
    text = json.dumps(report, ensure_ascii=False).lower()
    assert "pdfinfo" not in text and "pdftoppm" not in text

    checks = {check["name"]: check for check in report["checks"]}
    assert checks["converter.pymupdf"]["status"] == "pass"
    assert checks["runner.in_session"]["status"] == "pass"
    assert checks["storage.output_root"]["status"] == "pass"
    assert checks["storage.runtime_lock"]["status"] == "pass"
    assert "in_session" in report["capabilities"]["runners"]


def test_doctor_without_network_does_not_touch_zotero(tmp_path, monkeypatch):
    config = _config(tmp_path, group_id=42)

    def explode(*args, **kwargs):  # pragma: no cover - calling it is the failure
        raise AssertionError("network=False 时不允许访问 Zotero")

    monkeypatch.setattr("hydrolitagent.cards.zotero.preflight", explode)

    report = build_doctor_report(config, output_root=tmp_path / "artifacts", network=False)

    assert report["ok"] is True, report
    assert not any(check["capability"] == "zotero.read" for check in report["checks"])


def test_doctor_with_network_reports_zotero_checks(tmp_path, monkeypatch):
    config = _config(tmp_path, group_id=42)
    monkeypatch.setattr(
        "hydrolitagent.cards.zotero.preflight",
        lambda cfg: {
            "ok": True,
            "checks": [
                {"name": "local_api", "status": "pass", "detail": "本地 API 可访问"}
            ],
        },
    )

    report = build_doctor_report(config, output_root=tmp_path / "artifacts", network=True)

    names = {check["name"] for check in report["checks"]}
    assert "zotero.local_api" in names
    assert report["capabilities"]["network_checked"] is True


# --------------------------------------------------------------------------------------
# converter
# --------------------------------------------------------------------------------------


def test_missing_pymupdf_is_a_failing_check_with_an_actionable_fix(monkeypatch):
    # ``None`` in sys.modules makes the next ``import pymupdf`` raise ImportError,
    # which is exactly what a machine without the dependency does.
    monkeypatch.setitem(sys.modules, "pymupdf", None)

    doctor = probe_pymupdf()
    assert doctor.available is False
    assert doctor.fix and "pymupdf" in doctor.fix.lower()

    checks = converter_checks(doctor)
    assert checks[0].status == "fail"
    assert checks[0].fix == doctor.fix
    report = build_report(checks)
    assert report["ok"] is False
    assert report["model_invoked"] is False


# --------------------------------------------------------------------------------------
# runners
# --------------------------------------------------------------------------------------


def test_one_missing_runner_warns_when_another_is_available():
    checks = runner_checks(
        [
            RunnerDoctor("needs_setup", False, "缺少可执行文件", "安装该命令行"),
            RunnerDoctor("in_session", True, "文件式协议"),
        ]
    )

    missing = next(check for check in checks if check.name == "runner.needs_setup")
    assert missing.status == "warn"
    assert missing.fix == "安装该命令行"
    assert build_report(checks)["ok"] is True


def test_no_available_runner_fails_the_report():
    checks = runner_checks(
        [RunnerDoctor("a", False, "不可用", "修好它"), RunnerDoctor("b", False, "不可用", "修好它")]
    )

    assert all(check.status == "fail" for check in checks)
    assert build_report(checks)["ok"] is False


# --------------------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------------------


def test_cli_doctor_outputs_json_and_exits_zero(tmp_path, capsys):
    config_path = write_config(tmp_path / "app", {"zotero": {"group_id": None}})

    code = cli.main(
        [
            "doctor",
            "--config",
            str(config_path),
            "--output-root",
            str(tmp_path / "artifacts"),
            "--json",
        ]
    )

    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert code == 0
    assert payload["operation"] == "doctor"
    assert payload["model_invoked"] is False
    assert payload["checks"]


if __name__ == "__main__":  # pragma: no cover - manual invocation convenience
    raise SystemExit(pytest.main([__file__]))
