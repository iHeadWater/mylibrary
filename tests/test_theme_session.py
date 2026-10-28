"""Behaviour of the step-by-step, file-based theme session protocol.

``themes-run`` asks a runner for every answer at once; ``in_session`` cannot be
called, so the same three kinds of step (discovery, one reading per paper, one
refinement per candidate) are written to a directory and answered by an agent.
These tests drive that protocol with real sources and the real converter: the
reading answers are built from the ``paper.md`` the platform staged, so a green
result means the grounding gate accepted genuine quotes.

Nothing here invokes a model; every report must say ``model_invoked`` is false.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from hydrolitagent.cards import theme_pool as pool
from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.adapters.pdf.pymupdf_converter import PymupdfConverter
from hydrolitagent.cards.adapters.runners.in_session import InSessionRunner
from hydrolitagent.cards.adapters.storage.paper_store import PaperStore
from hydrolitagent.cards.cli import main
from hydrolitagent.cards.composition import MarkdownPipeline
from hydrolitagent.cards.config import load_config
from hydrolitagent.cards.domain.source_access import MARKDOWN_PREPARED
from hydrolitagent.cards.ports.paper import ConversionOptions
from hydrolitagent.cards.theme_session import (
    finalize_theme_session,
    prepare_theme_session,
)

from card_fixtures import ATTACHMENT_KEY, GenerationFixture, PARENT_KEY
from test_config import write_config
from test_markdown_workflow import _write_pdf, first_prose_quote

EID = "EV-" + PARENT_KEY


class ThemeSession:
    """One configured workspace: a rough pack, a real PDF and a run directory."""

    revised_markdown = "精读后建议收窄主题，仍是候选。"
    reading_markdown = "精读发现：原主题需要收窄。没有固定章节。"

    def __init__(self, root: Path):
        self.root = root
        self.f = GenerationFixture(root)
        # The theme assets must live under the configured project root; the real
        # ones are copied so both the library and the CLI resolve the same files.
        shutil.copytree(ASSETS_DIR / "templates/themes", root / "templates/themes")
        self.config_path = write_config(root, {"theme_pipeline": {
            "enabled": True, "assets_dir": "templates/themes"}})
        self.config = load_config(self.config_path)
        self.f.complete()
        self.pdf = _write_pdf(root / "source.pdf")
        digest = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        manifest = json.loads((self.f.package / "manifest.json").read_text(encoding="utf-8"))
        manifest["pdf_sha256"] = digest
        (self.f.package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.delivery = Mock(return_value=replace(
            self.f.delivery(), pdf_path=self.pdf, pdf_sha256=digest))
        self.pipeline = MarkdownPipeline(
            converter=PymupdfConverter(),
            store=PaperStore(root / "paper-cache"),
            runner=InSessionRunner(),
            options=ConversionOptions(),
        )
        self.run_dir = root / "run"
        self.literature_root = root / "literature"

    # -- answers ---------------------------------------------------------------

    def discovery_output(self, evidence_ids=None):
        ids = evidence_ids or [EID]
        return {
            "problem_clusters_markdown": "问题簇：测试材料。",
            "actions": [{
                "kind": "CREATE", "theme_ids": [], "reason": "测试新主题",
                "themes": [{
                    "title": "主题一",
                    "candidate_markdown": "自由格式初版。没有固定标题，也没有固定标签。",
                    "paper_tasks": [
                        {"evidence_id": evidence_id, "focus": f"问题 {evidence_id}",
                         "reuse_reading_id": None, "reuse_reason": None}
                        for evidence_id in ids
                    ],
                }],
            }],
        }

    def answer(self, request, run_dir: Path):
        if request["step_kind"] == "theme_discovery":
            return self.discovery_output()
        if request["step_kind"] == "focused_reading":
            markdown = (Path(run_dir) / "paper.md").read_text(encoding="utf-8")
            return {
                "source_read_status": "FULL_MARKDOWN_REVIEWED",
                "source_page_count": request["page_count"],
                "visual_content_status": "NOT_PRESENT",
                "source_read_evidence": "fixture read every page of paper.md",
                "reading_markdown": self.reading_markdown,
                "reading_receipt": {
                    "markdown_sha256": request["markdown_sha256"],
                    "read_mode": "file",
                    "model_claimed_status": "FULL_MARKDOWN_REVIEWED",
                    "model_claimed_pages": list(range(1, request["page_count"] + 1)),
                    "canaries_seen": request["reading_canaries"],
                },
                "source_locations": [{
                    "anchor": "P2", "quote": first_prose_quote(markdown, 2),
                    "pdf_page": 2, "section": None, "figure": None, "table": None,
                }],
            }
        return {"revised_markdown": self.revised_markdown}

    def respond(self, run_dir=None, response=None):
        run_dir = Path(run_dir or self.run_dir)
        request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
        payload = response if response is not None else self.answer(request, run_dir)
        (run_dir / "response.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return request

    # -- phases ------------------------------------------------------------------

    def prepare(self, **kwargs):
        kwargs.setdefault("literature_root", self.literature_root)
        kwargs.setdefault("delivery_preparer", self.delivery)
        kwargs.setdefault("pipeline", self.pipeline)
        return prepare_theme_session(self.config, run_dir=self.run_dir, **kwargs)

    def finalize(self, **kwargs):
        kwargs.setdefault("literature_root", self.literature_root)
        kwargs.setdefault("delivery_preparer", self.delivery)
        kwargs.setdefault("pipeline", self.pipeline)
        return finalize_theme_session(self.config, run_dir=self.run_dir, **kwargs)

    def run_steps(self):
        result = self.prepare()
        assert result["ok"], result
        seen = []
        for _ in range(20):
            request = self.respond()
            seen.append((request["step_kind"], request["step"]))
            result = self.finalize()
            if result["status"] != "NEXT_STEP_READY":
                break
        else:
            raise AssertionError("theme session did not converge within 20 steps")
        return result, seen

    def state(self, run_dir=None):
        path = Path(run_dir or self.run_dir) / "state.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def add_paper(self, key="ITEM0002"):
        other_pack = self.f.package.parent / ("EV-" + key + "-test")
        shutil.copytree(self.f.package, other_pack)
        path = other_pack / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest.update(parent_key=key, evidence_id="EV-" + key)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        base = self.delivery.return_value
        self.delivery.side_effect = lambda *args, **kwargs: replace(
            base,
            parent_key=args[-1],
            evidence_package_path=self.f.package if args[-1] == PARENT_KEY else other_pack,
            manifest_path=(self.f.package if args[-1] == PARENT_KEY
                           else other_pack) / "manifest.json",
        )
        return "EV-" + key


@pytest.fixture
def session(tmp_path):
    return ThemeSession(tmp_path)


def _write_response(run_dir: Path, payload) -> None:
    (Path(run_dir) / "response.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------
# happy path
# --------------------------------------------------------------------------------------


def test_prepare_stages_one_discovery_step_without_a_model(session):
    result = session.prepare()

    assert result["ok"], result
    assert result["status"] == "AWAITING_SESSION_OUTPUT"
    assert result["step_kind"] == "theme_discovery"
    assert result["step"] == "discovery"
    assert result["step_index"] == 0
    assert result["remaining_steps"] == []
    assert result["steps_known"] is False
    assert result["model_invoked"] is False
    assert result["model_call_count"] == 0
    for name in ("state.json", "request.json", "output.schema.json", "README.md"):
        assert (session.run_dir / name).is_file(), name
    assert not (session.run_dir / "response.json").exists()
    # A synthesis step stages no paper at all.
    assert not (session.run_dir / "paper.md").exists()

    state = session.state()
    assert state["step"] == "discovery" and state["step_index"] == 0
    assert state["response_file"] == "response.json"
    assert state["completed"] == []
    assert state["steps_known"] is False
    assert state["plan"] is None
    request = json.loads((session.run_dir / "request.json").read_text(encoding="utf-8"))
    assert request["step"] == "discovery"
    assert request["output_schema_file"] == "output.schema.json"
    assert request["prompt"] and request["input"]["cards"]


def test_single_source_completes_all_three_step_kinds(session):
    result, seen = session.run_steps()

    assert result["ok"], result
    assert result["status"] == "COMPLETED"
    assert [kind for kind, _ in seen] == [
        "theme_discovery", "focused_reading", "theme_refinement"]
    assert result["model_invoked"] is False
    assert result["model_call_count"] == 0
    assert result["candidate_count"] == 1
    assert result["action"] == "EVOLVED"
    assert session.state()["status"] == "COMPLETED"

    state = pool.load(session.config)
    assert len(state["themes"]) == 1
    pool.check_index(session.config, state)
    assert (session.config.paths.themes_dir / "index.md").is_file()
    assert (session.config.paths.themes_dir / "_registry.json").is_file()

    theme = result["themes"][0]
    assert session.revised_markdown in Path(theme["revised_path"]).read_text(encoding="utf-8")
    reading_path = Path(theme["readings"][0]["path"])
    assert reading_path.is_file()
    record = json.loads(
        (reading_path.parent / "result.json").read_text(encoding="utf-8"))["record"]
    access = record["execution"]["source_access"]
    assert access["method"] == MARKDOWN_PREPARED
    assert access["parent_key"] == PARENT_KEY
    assert access["converter_id"] == "pymupdf"
    assert access["reading"]["verified"] is True
    assert access["reading"]["canaries_ok"] is True
    assert access["reading"]["scientific_correctness_verified"] is False
    assert record["execution"]["runner_id"] == "in_session"
    assert record["execution"]["model_invoked"] is False

    # The reading never saw a PDF: only Markdown and JSON are staged.
    assert not any(path.suffix.lower() == ".pdf"
                   for path in session.run_dir.rglob("*"))


def test_two_sources_produce_two_reading_steps(session):
    other = session.add_paper()
    session.discovery_output = lambda: ThemeSession.discovery_output(session, [EID, other])

    result, seen = session.run_steps()

    assert result["ok"], result
    kinds = [kind for kind, _ in seen]
    assert kinds == ["theme_discovery", "focused_reading", "focused_reading",
                     "theme_refinement"]
    assert len(result["themes"][0]["readings"]) == 2
    assert session.delivery.call_count == 2


def test_discovery_without_actions_commits_an_empty_change(session):
    assert session.prepare()["ok"]
    session.respond(response={"problem_clusters_markdown": "本批没有可聚的主题。",
                              "actions": []})

    result = session.finalize()

    assert result["ok"], result
    assert result["status"] == "COMPLETED"
    assert result["candidate_count"] == 0
    assert result["action"] == "NO_CHANGE_NEEDED"
    state = pool.load(session.config)
    assert state is not None and state["themes"] == {}
    pool.check_index(session.config, state)


def test_second_run_is_unchanged_and_calls_no_step(session):
    assert session.run_steps()[0]["ok"]
    again = session.prepare()

    assert again["ok"], again
    assert again["status"] == "UNCHANGED"
    assert again["model_call_count"] == 0
    assert again["next_action"] is None


# --------------------------------------------------------------------------------------
# failures do not advance
# --------------------------------------------------------------------------------------


def test_missing_response_is_a_structured_failure(session):
    assert session.prepare()["ok"]

    result = session.finalize()

    assert result["ok"] is False
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "IN_SESSION_RESPONSE_MISSING"
    state = session.state()
    assert state["step"] == "discovery" and state["completed"] == []


def test_invalid_json_does_not_advance(session):
    assert session.prepare()["ok"]
    (session.run_dir / "response.json").write_text("{not json", encoding="utf-8")

    result = session.finalize()

    assert result["ok"] is False
    assert result["error"]["code"] == "IN_SESSION_RESPONSE_INVALID"
    assert session.state()["step"] == "discovery"
    assert (session.run_dir / "response.json").is_file()


def test_unroutable_discovery_output_does_not_advance(session):
    assert session.prepare()["ok"]
    session.respond(response={"problem_clusters_markdown": "只有说明", "actions": [
        {"kind": "CREATE", "theme_ids": [], "reason": "x", "themes": [
            {"title": "t", "candidate_markdown": "m", "paper_tasks": [
                {"evidence_id": "../../outside", "focus": "f"}]}]}]})

    result = session.finalize()

    assert result["ok"] is False
    assert result["error"]["code"] == "THEME_UNKNOWN_SOURCE"
    assert session.state()["step"] == "discovery"
    assert not (session.config.paths.themes_dir / "_registry.json").exists()


def test_fabricated_quote_fails_the_reading_and_keeps_the_step_open(session):
    assert session.prepare()["ok"]
    session.respond()
    assert session.finalize()["status"] == "NEXT_STEP_READY"
    request = session.respond()
    assert request["step_kind"] == "focused_reading"

    bad = session.answer(request, session.run_dir)
    bad["source_locations"][0]["quote"] = (
        "Peak error fell by 92 percent under every tested scenario.")
    session.respond(response=bad)

    result = session.finalize()

    assert result["ok"] is False
    assert result["error"]["code"] == "QUOTE_NOT_FOUND"
    state = session.state()
    assert state["step"] == request["step"]
    assert request["step"] not in state["completed"]
    assert not (session.config.paths.themes_dir / "_registry.json").exists()


def test_wrong_markdown_digest_fails_the_reading(session):
    assert session.prepare()["ok"]
    session.respond()
    assert session.finalize()["status"] == "NEXT_STEP_READY"
    request = session.respond()
    response = session.answer(request, session.run_dir)
    response["reading_receipt"]["markdown_sha256"] = "0" * 64
    session.respond(response=response)

    result = session.finalize()

    assert result["ok"] is False
    assert result["error"]["code"] == "MARKDOWN_SHA_MISMATCH"


def test_edited_paper_md_is_rejected(session):
    assert session.prepare()["ok"]
    session.respond()
    assert session.finalize()["status"] == "NEXT_STEP_READY"
    request = session.respond()
    markdown = (session.run_dir / "paper.md").read_text(encoding="utf-8")
    (session.run_dir / "paper.md").write_text(markdown + "\n手工追加。", encoding="utf-8")

    result = session.finalize()

    assert result["ok"] is False
    assert result["error"]["code"] == "MARKDOWN_CHANGED"
    assert session.state()["step"] == request["step"]


# --------------------------------------------------------------------------------------
# restart and replay
# --------------------------------------------------------------------------------------


def test_reprepare_returns_the_unfinished_step_with_its_material(session):
    assert session.prepare()["ok"]
    session.respond()
    assert session.finalize()["status"] == "NEXT_STEP_READY"

    again = session.prepare()

    assert again["ok"], again
    assert again["resumed"] is True
    assert again["status"] == "AWAITING_SESSION_OUTPUT"
    assert again["step_kind"] == "focused_reading"
    assert len(again["remaining_steps"]) == 1
    assert (session.run_dir / "paper.md").is_file()
    request = json.loads((session.run_dir / "request.json").read_text(encoding="utf-8"))
    assert request["step"] == again["step"]
    # The staged Markdown is the one the reading will be checked against.
    assert request["markdown_sha256"]
    assert request["page_anchors"]
    assert request["reading_canaries"]


def test_replayed_finalize_is_idempotent(session):
    assert session.prepare()["ok"]
    session.respond()
    first = session.finalize()
    assert first["status"] == "NEXT_STEP_READY"
    before = session.state()

    second = session.finalize()

    assert second.get("replayed") is True
    assert second["status"] == first["status"]
    assert second["next_step"] == first["next_step"]
    after = session.state()
    assert after["step"] == before["step"]
    assert after["completed"] == before["completed"]
    assert not (session.config.paths.themes_dir / "_registry.json").exists()


def test_finalize_after_completion_re_reports_the_same_outcome(session):
    completed, _seen = session.run_steps()
    assert completed["status"] == "COMPLETED"
    state_before = session.state()

    again = session.finalize()

    assert again.get("replayed") is True
    assert again["status"] == "COMPLETED"
    assert again["candidate_count"] == completed["candidate_count"]
    assert session.state()["completed"] == state_before["completed"]


def test_finalize_without_state_is_a_structured_failure(session):
    result = session.finalize()

    assert result["ok"] is False
    assert result["error"]["code"] == "THEME_SESSION_STATE_MISSING"


def test_archived_answer_replays_after_a_lost_state_write(session):
    """A crash between staging the next request and writing state is recoverable.

    The answer is archived under the step id before the state advances, so a
    finalize that finds the old state, a new request and no ``response.json``
    can rebuild the request and replay the archived answer instead of asking the
    agent to read the paper again.
    """

    assert session.prepare()["ok"]
    before = session.state()
    request = session.respond()
    assert session.finalize()["status"] == "NEXT_STEP_READY"
    assert not (session.run_dir / "response.json").exists()
    # Simulate the interrupted write: the state still points at the answered step.
    (session.run_dir / "state.json").write_text(
        json.dumps(before, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = session.finalize()

    assert result["ok"], result
    assert result["status"] == "NEXT_STEP_READY"
    assert result["step"] == request["step"]
    assert result.get("replayed") is not True
    assert session.state()["step"] == result["next_step"]


def test_no_sources_stages_nothing(session):
    session.config = replace(session.config, paths=replace(
        session.config.paths, evidence_packs_dir=session.root / "empty-packs"))

    result = session.prepare()

    assert result["ok"], result
    assert result["status"] == "NO_ROUGH_CARDS"
    assert result["model_invoked"] is False
    assert not (session.run_dir / "state.json").exists()


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _cli(argv) -> tuple[int, dict]:
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = main(argv)
    return code, json.loads(stream.getvalue())


def test_cli_theme_session_walks_to_completed(session):
    run_dir = session.root / "cli-run"
    with patch("hydrolitagent.cards.theme_session_steps.prepare_pdf_delivery",
               session.delivery):
        code, result = _cli(["run", "prepare", "--theme",
                             "--config", str(session.config_path),
                             "--run-dir", str(run_dir), "--json"])
        assert code == 0, result
        assert result["status"] == "AWAITING_SESSION_OUTPUT"
        assert result["step_kind"] == "theme_discovery"
        for _ in range(20):
            request = session.respond(run_dir)
            assert request["step"]
            code, result = _cli(["run", "finalize", "--theme",
                                 "--config", str(session.config_path),
                                 "--run-dir", str(run_dir), "--json"])
            assert code == 0, result
            if result["status"] != "NEXT_STEP_READY":
                break
        else:
            raise AssertionError("theme session did not converge within 20 steps")

    assert result["status"] == "COMPLETED"
    assert result["model_invoked"] is False
    assert result["candidate_count"] == 1
    assert pool.load(session.config)["themes"]


def test_cli_rejects_theme_with_paper_input(session):
    code, result = _cli(["run", "prepare", "--theme",
                         "--config", str(session.config_path),
                         "--paper-input", "-", "--run-dir", str(session.root / "r"),
                         "--json"])

    assert code == 3
    assert result["ok"] is False
    assert result["error"]["code"] == "CARD_DRAFT_CONFIG_OR_INPUT_INVALID"


def test_cli_themes_run_with_in_session_awaits_session_output(session):
    run_dir = session.root / "themes-run"

    code, result = _cli(["themes-run", "--config", str(session.config_path),
                         "--ai-provider", "in_session", "--run-dir", str(run_dir),
                         "--json"])

    assert code == 0, result
    assert result["operation"] == "themes_run"
    assert result["status"] == "AWAITING_SESSION_OUTPUT"
    assert result["model_invoked"] is False
    assert result["model_call_count"] == 0
    assert result["step_kind"] == "theme_discovery"
    assert result["next_action"]
    assert (run_dir / "state.json").is_file()
    assert (run_dir / "request.json").is_file()

    # Rerunning resumes the same step instead of starting a second session.
    again_code, again = _cli(["themes-run", "--config", str(session.config_path),
                              "--ai-provider", "in_session", "--run-dir", str(run_dir),
                              "--json"])
    assert again_code == 0
    assert again["step"] == result["step"]
    assert again.get("resumed") is True


if __name__ == "__main__":  # pragma: no cover - manual invocation convenience
    raise SystemExit(pytest.main([__file__]))
