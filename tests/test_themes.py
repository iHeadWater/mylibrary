from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from hydrolitagent.cards import theme_pool as pool
from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.adapters.pdf.pymupdf_converter import PymupdfConverter
from hydrolitagent.cards.adapters.runners.scripted import ScriptedRunner
from hydrolitagent.cards.adapters.storage.paper_store import PaperStore
from hydrolitagent.cards.application.prepare_paper import prepare_paper
from hydrolitagent.cards.card_validation import fingerprint
from hydrolitagent.cards.cli import main
from hydrolitagent.cards.composition import MarkdownPipeline
from hydrolitagent.cards.config import ConfigError, load_config
from hydrolitagent.cards.domain.grounding import expected_canaries
from hydrolitagent.cards.domain.source_access import MARKDOWN_PREPARED
from hydrolitagent.cards.pdf_delivery import PdfDeliveryError
from hydrolitagent.cards.ports.paper import ConversionOptions
from hydrolitagent.cards.ports.runner import CardRunError, RunnerDoctor
from hydrolitagent.cards.tasks import PipelineRunLock
from hydrolitagent.cards.themes import ThemeError, _publish, _safe_path, run_themes
from test_card_generation import ATTACHMENT_KEY, GenerationFixture, FakeAdapter, PARENT_KEY
from test_config import write_config
from test_markdown_workflow import first_prose_quote, _write_pdf

ROOT = ASSETS_DIR
EID = "EV-" + PARENT_KEY


class ThemeRunner(ScriptedRunner):
    """Scripted runner whose answer is the theme-flow fixture for this test.

    The owner decides the answer per ``role``: discovery, focused reading or
    refinement. A reading answer is built from the paper the runner actually
    received, so a passing test means the grounding gate accepted real quotes.
    """

    runner_id = "scripted"

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def doctor(self) -> RunnerDoctor:
        return RunnerDoctor(runner_id=self.runner_id, available=True, detail="测试替身")

    def run(self, request):
        answer, failure = self.owner.answer(request)
        self.output, self.ok, self.error = answer, failure is None, failure
        return super().run(request)


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = GenerationFixture(self.root)
        self.path = write_config(self.root)
        config = load_config(self.path)
        self.config = replace(config, theme_pipeline=replace(config.theme_pipeline, enabled=True,
            assets_dir=ROOT / "templates/themes"))
        # Build a real, validated legacy rough pack without a live provider.
        self.f.generate(FakeAdapter())
        # A real PDF: the live pipeline converts it with PyMuPDF and caches the
        # Markdown, exactly as production does.
        self.pdf = _write_pdf(self.root / "source.pdf")
        digest = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        self.manifest = json.loads((self.f.package / "manifest.json").read_text(encoding="utf-8"))
        self.manifest["pdf_sha256"] = digest
        (self.f.package / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        self.delivery = Mock(return_value=replace(self.f.delivery(), pdf_path=self.pdf, pdf_sha256=digest))
        self.discovered = {"problem_clusters_markdown": "问题簇：测试材料。", "themes": [{"title": "主题一",
            "candidate_markdown": "自由格式初版。没有固定标题，也没有固定标签。", "paper_tasks": [
                {"evidence_id": EID, "focus": "尺度差异能否解释结论差别？"}]}]}
        self.discovery_actions = None      # None -> CREATE one theme per self.discovered item
        self.revised_markdown = "精读后建议收窄主题，仍是候选。"
        self.reading_markdown = "精读发现：原主题需要收窄。没有固定章节。"
        self.failures = {}                 # role -> remaining failures
        self.fail_hooks = []               # callables(request) -> True to fail this call
        self.answer_hooks = []             # callables(request, output) run after answering
        self.workspace_views = []          # (role, staged file names) per runner call
        self.reader = ThemeRunner(self)
        self.pipeline = MarkdownPipeline(
            converter=PymupdfConverter(),
            store=PaperStore(self.root / "paper-cache"),
            runner=self.reader,
            options=ConversionOptions(),
        )

    # -- scripted answers ---------------------------------------------------------

    def discovery_output(self):
        if self.discovery_actions is not None:
            return {"problem_clusters_markdown": "关联判断与变更理由",
                    "actions": deepcopy(self.discovery_actions)}
        return {"problem_clusters_markdown": self.discovered["problem_clusters_markdown"], "actions": [
            {"kind": "CREATE", "theme_ids": [], "reason": "测试新主题", "themes": [deepcopy(t)]}
            for t in self.discovered["themes"]]}

    def reading_output(self, request):
        prepared = request.paper
        markdown = prepared.markdown_path.read_text(encoding="utf-8")
        return {
            "source_read_status": "FULL_MARKDOWN_REVIEWED",
            "source_page_count": prepared.page_count,
            "visual_content_status": "NOT_PRESENT",
            "source_read_evidence": "fixture read every page of paper.md",
            "reading_markdown": self.reading_markdown,
            "reading_receipt": {
                "markdown_sha256": prepared.markdown_sha256,
                "read_mode": "file",
                "model_claimed_status": "FULL_MARKDOWN_REVIEWED",
                "model_claimed_pages": list(range(1, prepared.page_count + 1)),
                "canaries_seen": list(expected_canaries(markdown)),
            },
            "source_locations": [{
                "anchor": "P2",
                "quote": first_prose_quote(markdown, 2),
                "pdf_page": 2,
                "section": None, "figure": None, "table": None,
            }],
        }

    def answer(self, request):
        """Return ``(output, failure)`` for one runner request."""

        # The staged directory is deleted after a successful stage, so the view
        # the runner had is recorded while it is still on disk.
        self.workspace_views.append(
            (request.role, sorted(path.name for path in Path(request.workspace).iterdir()))
        )
        if self.failures.get(request.role):
            self.failures[request.role] -= 1
            return None, CardRunError("CODEX_SERVICE_UNAVAILABLE", "断线")
        if any(hook(request) for hook in self.fail_hooks):
            return None, CardRunError("CODEX_SERVICE_UNAVAILABLE", "断线")
        if request.role == "focused_reading":
            output = self.reading_output(request)
        elif request.role == "theme_discovery":
            output = self.discovery_output()
        else:
            output = {"revised_markdown": self.revised_markdown}
        for hook in self.answer_hooks:
            changed = hook(request, output)
            if changed is not None:
                output = changed
        return output, None

    def calls(self, role):
        return [request for request in self.reader.requests if request.role == role]

    def changed_goal(self, goal="changed-goal"):
        self.config = replace(self.config, theme_pipeline=replace(self.config.theme_pipeline, research_goal=goal))

    def run_theme(self, **kwargs):
        # An empty literature root isolates the test from drafts on this machine.
        kwargs.setdefault("literature_root", self.root / "literature")
        return run_themes(self.config, pipeline=self.pipeline, delivery_preparer=self.delivery, **kwargs)

    # -- validated single-paper drafts as sources ---------------------------------

    draft_card = "# 已验证主体卡草稿\n\n本卡由单篇流程生成，等待主题聚合。\n"

    def use_validated_drafts_only(self):
        """Point the run at one validated personal-library draft and no packs.

        Returns the prepared paper that backs the draft, so a test can check the
        reading reuses that exact Markdown.
        """

        empty = self.root / "empty-packs"
        empty.mkdir(exist_ok=True)
        self.config = replace(self.config, paths=replace(self.config.paths, evidence_packs_dir=empty))
        prepare_paper(self.pdf, converter=PymupdfConverter(), store=self.pipeline.store,
                      options=ConversionOptions(), group_id=None, parent_key=PARENT_KEY,
                      attachment_key=ATTACHMENT_KEY)
        digest = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        directory = (self.root / "literature" / "zotero" / f"user-0-{PARENT_KEY}" / "drafts" / ("d" * 16))
        directory.mkdir(parents=True)
        draft = {
            "schema_version": 2, "draft_id": "d" * 16, "status": "DRAFT_PENDING_VALIDATION",
            "created_at": "2026-10-27T00:00:00Z", "pipeline": "markdown",
            "source": {"library": {"type": "user", "id": 0}, "parent_key": PARENT_KEY,
                       "requested_item_key": PARENT_KEY, "attachment_key": ATTACHMENT_KEY,
                       "pdf_sha256": digest, "pdf_size_bytes": self.pdf.stat().st_size,
                       "pdf_page_count": 3, "item": {"title": "Draft source paper"}},
            "card_body_markdown": self.draft_card,
            "provenance": {"converter_id": "pymupdf",
                           "converter_version": PymupdfConverter().converter_version},
        }
        (directory / "draft.json").write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        (directory / "card.md").write_text(self.draft_card, encoding="utf-8")
        validation = directory / "validations" / ("v" * 32)
        validation.mkdir(parents=True)
        (validation / "validation.json").write_text(json.dumps({
            "schema_version": 1, "validation_id": "v" * 32,
            "validated_at": "2026-10-27T00:00:01Z", "status": "PASS", "ok": True,
            "reading_verified": True, "eligible_for_theme_generation": True,
            "draft_id": draft["draft_id"], "draft_sha256": fingerprint(draft),
        }), encoding="utf-8")
        return directory

    def test_draft_source_runs_the_whole_theme_chain(self):
        directory = self.use_validated_drafts_only()
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "CANDIDATES_REFINED")
        self.assertEqual(result["source_count"], 1)
        self.assertEqual(result["sources_by_kind"], {"evidence_pack": 0, "draft": 1})
        self.assertEqual(result["source_ids"], [EID])
        self.assertEqual(result["duplicate_sources"], [])
        # No evidence pack exists, so no PDF was delivered: the reading reused
        # the conversion cache the draft was built from.
        self.assertEqual(self.delivery.call_count, 0)
        reading = self.calls("focused_reading")[0]
        self.assertIn("本卡由单篇流程生成", self.calls("theme_discovery")[0].prompt)
        self.assertEqual(reading.paper.source.pdf_sha256,
                         hashlib.sha256(self.pdf.read_bytes()).hexdigest())
        theme = result["themes"][0]
        self.assertTrue(Path(theme["revised_path"]).is_file())
        self.assertIn("card.md", Path(theme["revised_path"]).read_text(encoding="utf-8"))
        self.assertIn("drafts", Path(theme["revised_path"]).read_text(encoding="utf-8"))
        self.assertTrue(Path(theme["readings"][0]["path"]).is_relative_to(
            self.config.paths.evidence_packs_dir))
        state = pool.load(self.config)
        self.assertEqual(len(state["themes"]), 1)
        pool.check_index(self.config, state)
        # A rerun is unchanged: same source identity, no model call.
        again = self.run_theme()
        self.assertTrue(again["ok"], again)
        self.assertEqual(again["model_call_count"], 0)
        self.assertTrue(directory.is_dir())

    def test_draft_dry_run_reports_sources_without_writing(self):
        self.use_validated_drafts_only()
        before = sorted(str(path) for path in self.root.rglob("*"))
        result = self.run_theme(dry_run=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["sources_by_kind"], {"evidence_pack": 0, "draft": 1})
        self.assertEqual(result["source_ids"], [EID])
        self.assertEqual(sum(result["rejected_drafts"].values()), 0)
        self.assertEqual(self.reader.requests, [])
        self.assertEqual(before, sorted(str(path) for path in self.root.rglob("*")))

    def test_unvalidated_draft_is_not_a_source(self):
        directory = self.use_validated_drafts_only()
        shutil.rmtree(directory / "validations")
        result = self.run_theme(dry_run=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "NO_ROUGH_CARDS")
        self.assertEqual(result["sources_by_kind"], {"evidence_pack": 0, "draft": 0})
        self.assertEqual(result["rejected_drafts"]["unvalidated"], 1)
        self.assertEqual(self.reader.requests, [])

    def test_draft_without_cached_markdown_blocks_before_the_reader(self):
        self.use_validated_drafts_only()
        shutil.rmtree(self.pipeline.store.cache_dir)
        result = self.run_theme()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "THEME_DRAFT_MARKDOWN_MISSING")
        self.assertEqual(self.calls("focused_reading"), [])
        self.assertEqual(self.delivery.call_count, 0)

    def test_draft_edit_during_run_is_blocked(self):
        self.use_validated_drafts_only()

        def edit(request, output):
            if request.role == "theme_discovery":
                path = next((self.root / "literature").rglob("card.md"))
                path.write_text(self.draft_card + "手工改动。", encoding="utf-8")
            return None

        self.answer_hooks.append(edit)
        result = self.run_theme()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "THEME_INPUT_CHANGED")
        self.assertEqual(self.calls("focused_reading"), [])

    # -- behaviour ---------------------------------------------------------------

    def test_end_to_end_and_rerun_skip_preserve_main_files(self):
        protected = {p: p.read_bytes() for p in self.f.package.iterdir() if p.is_file()}
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "CANDIDATES_REFINED")
        self.assertEqual(result["model_call_count"], 3)
        reading = self.calls("focused_reading")[0]
        # The runner receives a prepared paper, never a PDF path.
        self.assertIsNotNone(reading.paper)
        self.assertFalse(hasattr(reading.paper, "pdf_path"))
        self.assertNotIn(".pdf", reading.prompt.lower())
        views = dict(self.workspace_views)
        self.assertIn("paper.md", views["focused_reading"])
        self.assertIn("output.schema.json", views["focused_reading"])
        self.assertFalse(any(name.lower().endswith(".pdf") for name in views["focused_reading"]))
        # A synthesis call is text-only: no paper.md is staged or implied.
        self.assertNotIn("paper.md", views["theme_discovery"])
        self.assertIn("output.schema.json", views["theme_discovery"])
        item = result["themes"][0]
        self.assertIn("原主题需要收窄", self.calls("theme_synthesis")[0].prompt)
        self.assertTrue(Path(item["revised_path"]).exists())
        self.assertTrue(Path(item["initial_path"]).exists())
        self.assertTrue(Path(item["readings"][0]["path"]).is_relative_to(self.f.package))
        self.assertEqual(protected, {p: p.read_bytes() for p in protected})
        self.assertFalse((self.config.paths.themes_dir / "confirmed").exists())
        again = self.run_theme()
        self.assertTrue(again["ok"], again)
        self.assertEqual(again["model_call_count"], 0)
        self.assertEqual(again["reused_step_count"], 3)
        self.assertEqual(self.delivery.call_count, 1)

    def test_focused_reading_is_recorded_as_markdown_prepared(self):
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        path = Path(result["themes"][0]["readings"][0]["path"])
        record = json.loads((path.parent / "result.json").read_text(encoding="utf-8"))["record"]
        access = record["execution"]["source_access"]
        self.assertEqual(access["method"], MARKDOWN_PREPARED)
        self.assertEqual(access["source_pdf_sha256"], self.manifest["pdf_sha256"])
        self.assertEqual(access["parent_key"], PARENT_KEY)
        self.assertEqual(access["converter_id"], "pymupdf")
        self.assertTrue(access["reading"]["verified"])
        self.assertTrue(access["reading"]["canaries_ok"])
        self.assertFalse(access["reading"]["scientific_correctness_verified"])
        self.assertEqual(record["execution"]["runner_id"], "scripted")

    def test_failed_pdf_resumes_no_repeat_discovery(self):
        self.failures["focused_reading"] = 1
        first = self.run_theme()
        self.assertFalse(first["ok"])
        self.assertTrue(Path(first["themes"][0]["initial_path"]).exists())
        self.assertFalse((Path(first["themes"][0]["initial_path"]).parent / "revised.md").exists())
        second = self.run_theme()
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["model_call_count"], 2)

    def test_failed_refinement_resumes_without_pdf(self):
        self.failures["theme_synthesis"] = 1
        first = self.run_theme()
        self.assertFalse(first["ok"])
        second = self.run_theme()
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["model_call_count"], 1)
        self.assertEqual(len(self.calls("focused_reading")), 1)

    def test_duplicate_paper_tasks_merge_focus_once(self):
        self.discovered["themes"][0]["paper_tasks"].append({"evidence_id": EID, "focus": "再看图表"})
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        readings = self.calls("focused_reading")
        self.assertEqual(len(readings), 1)
        self.assertIn("再看图表", readings[0].prompt)

    def test_unknown_source_or_path_injection_rejected(self):
        self.discovered["themes"][0]["paper_tasks"][0]["evidence_id"] = "../../outside"
        result = self.run_theme()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "THEME_UNKNOWN_SOURCE")
        self.assertEqual(self.calls("focused_reading"), [])
        again = self.run_theme()
        self.assertEqual(again["model_call_count"], 0)  # preserve invalid raw result, no token loop

    def test_no_candidates_allowed(self):
        self.discovered["themes"] = []
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "NO_CANDIDATES")
        self.assertEqual(self.calls("focused_reading"), [])

    def test_no_cards_skips_all_models(self):
        self.config = replace(self.config, paths=replace(self.config.paths, evidence_packs_dir=self.root / "empty"))
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "NO_ROUGH_CARDS")
        self.assertEqual(self.calls("theme_discovery"), [])

    def test_same_paper_gets_separate_readings_for_two_themes(self):
        second = deepcopy(self.discovered["themes"][0])
        second["title"] = "主题二"
        second["paper_tasks"][0]["focus"] = "验证方式的边界是什么？"
        self.discovered["themes"].append(second)
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["refined_count"], 2)
        self.assertEqual(len(self.calls("focused_reading")), 2)
        self.assertNotEqual(result["themes"][0]["readings"][0]["path"], result["themes"][1]["readings"][0]["path"])
        again = self.run_theme()
        self.assertEqual(again["model_call_count"], 0)

    def test_multi_paper_revision_waits_for_each_source(self):
        other_key = "ITEM0002"
        other_pack = self.f.package.parent / ("EV-" + other_key + "-test")
        shutil.copytree(self.f.package, other_pack)
        path = other_pack / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest.update(parent_key=other_key, evidence_id="EV-" + other_key)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.discovered["themes"][0]["paper_tasks"].append({"evidence_id": "EV-" + other_key, "focus": "关联研究进展"})
        base_delivery = self.delivery.return_value
        def deliver(*args, **kwargs):
            key = args[-1]
            pack = self.f.package if key == PARENT_KEY else other_pack
            return replace(base_delivery, parent_key=key, evidence_package_path=pack, manifest_path=pack / "manifest.json")
        self.delivery.side_effect = deliver
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(self.calls("focused_reading")), 2)
        self.assertEqual(len(result["themes"][0]["readings"]), 2)
        final_prompt = self.calls("theme_synthesis")[0].prompt
        self.assertIn(PARENT_KEY, final_prompt)
        self.assertIn(other_key, final_prompt)

    def test_source_edit_during_model_call_stops_publication(self):
        def edit(request, output):
            if request.role == "theme_discovery":
                with (self.f.package / "card.md").open("a", encoding="utf-8") as stream:
                    stream.write("manual edit")
            return None
        self.answer_hooks.append(edit)
        result = self.run_theme()
        self.assertFalse(result["ok"])
        self.assertEqual(self.calls("focused_reading"), [])
        self.assertEqual(result["error"]["code"], "EVIDENCE_CARD_CHANGED")

    def test_missing_pdf_no_fake_reading_or_refinement(self):
        self.delivery.side_effect = PdfDeliveryError("PDF_MISSING", "未取得 PDF")
        result = self.run_theme()
        self.assertFalse(result["ok"])
        self.assertEqual(self.calls("focused_reading"), [])
        self.assertEqual(len(self.calls("theme_discovery")), 1)

    def test_wrong_pdf_rejected_before_model(self):
        self.pdf.write_bytes(b"changed PDF")
        result = self.run_theme()
        self.assertEqual(result["themes"][0]["error"]["code"], "THEME_PDF_MISMATCH")
        self.assertEqual(self.calls("focused_reading"), [])

    def test_unreadable_pdf_blocks_one_theme_without_a_model_call(self):
        scanned = _write_pdf(self.root / "scanned.pdf", text=False)
        digest = hashlib.sha256(scanned.read_bytes()).hexdigest()
        self.manifest["pdf_sha256"] = digest
        (self.f.package / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        self.delivery.return_value = replace(self.f.delivery(), pdf_path=scanned, pdf_sha256=digest)
        result = self.run_theme()
        self.assertFalse(result["ok"])
        self.assertEqual(result["themes"][0]["error"]["code"], "CONVERTER_LOW_TEXT")
        self.assertEqual(self.calls("focused_reading"), [])

    def test_empty_reading_blocked_but_no_format_gates(self):
        self.reading_markdown = " "
        result = self.run_theme()
        self.assertEqual(result["themes"][0]["error"]["code"], "THEME_OUTPUT_EMPTY")
        self.assertEqual(len(self.calls("theme_discovery")), 1)

    def test_missing_reading_receipt_cannot_pass(self):
        def drop_receipt(request, output):
            if request.role != "focused_reading":
                return None
            return {key: value for key, value in output.items() if key != "reading_receipt"}
        self.answer_hooks.append(drop_receipt)
        result = self.run_theme()
        self.assertEqual(result["themes"][0]["error"]["code"], "INCOMPLETE_MARKDOWN_READ")

    def test_wrong_markdown_digest_cannot_pass(self):
        self.answer_hooks.append(
            lambda request, output: {
                **output,
                "reading_receipt": {**output["reading_receipt"], "markdown_sha256": "0" * 64},
            } if request.role == "focused_reading" else None
        )
        result = self.run_theme()
        self.assertEqual(result["themes"][0]["error"]["code"], "MARKDOWN_SHA_MISMATCH")

    def test_fabricated_quote_is_rejected(self):
        def fabricate(request, output):
            if request.role != "focused_reading":
                return None
            return {**output, "source_locations": [{
                "anchor": "P2",
                "quote": "Peak error fell by 92 percent under every tested scenario.",
                "pdf_page": 2, "section": None, "figure": None, "table": None}]}
        self.answer_hooks.append(fabricate)
        result = self.run_theme()
        self.assertEqual(result["themes"][0]["error"]["code"], "QUOTE_NOT_FOUND")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "BLOCKED")

    def test_manual_changes_never_overwritten_or_regenerated(self):
        first = self.run_theme()
        path = Path(first["themes"][0]["revised_path"])
        path.write_text("我的修改", encoding="utf-8")
        second = self.run_theme()
        self.assertFalse(second["ok"])
        self.assertEqual(second["model_call_count"], 0)
        self.assertEqual(path.read_text(encoding="utf-8"), "我的修改")

    def test_partial_publication_resumes_from_saved_model_result(self):
        original = _publish
        def fail(path, content):
            if path.name == "reading.md":
                raise OSError("disk temporarily unavailable")
            original(path, content)
        with patch("hydrolitagent.cards.themes._publish", side_effect=fail):
            first = self.run_theme()
        self.assertFalse(first["ok"])
        second = self.run_theme()
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["model_call_count"], 1)
        self.assertEqual(len(self.calls("focused_reading")), 1)

    def test_checkpoints_survive_local_runtime_loss(self):
        self.assertTrue(self.run_theme()["ok"])
        # Simulates a fresh runtime by pointing only the local state to a new directory.
        self.config = replace(self.config, paths=replace(self.config.paths,
            runtime_dir=self.root / "new-runtime", lock_file=self.root / "new-runtime/worker.lock",
            logs_dir=self.root / "new-runtime/logs"))
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["model_call_count"], 0)

    def test_windows_git_newlines_do_not_trigger_regeneration(self):
        first = self.run_theme()
        for root in (Path(first["pool_path"]), self.f.package / "readings"):
            for path in root.rglob("*"):
                if path.is_file():
                    path.write_bytes(path.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["model_call_count"], 0)

    def test_goal_change_versions_instead_of_overwrite(self):
        first = self.run_theme()
        original = Path(first["themes"][0]["revised_path"]).read_bytes()
        self.config = replace(self.config, theme_pipeline=replace(self.config.theme_pipeline, research_goal="灾害链"))
        second = self.run_theme()
        self.assertTrue(second["ok"], second)
        self.assertNotEqual(first["change_id"], second["change_id"])
        self.assertEqual(Path(first["themes"][0]["revised_path"]).read_bytes(), original)

    def test_hash_chain_links_each_version_to_the_previous_one(self):
        """The same chain rules as before: immutable commit, one new generation."""

        from hydrolitagent.cards import themes as core

        first = self.run_theme()
        self.assertTrue(first["ok"], first)
        registry = json.loads((self.config.paths.themes_dir / "_registry.json").read_text(encoding="utf-8"))
        previous = registry["record"]
        self.changed_goal("另一研究目标")
        second = self.run_theme()
        self.assertTrue(second["ok"], second)
        registry = json.loads((self.config.paths.themes_dir / "_registry.json").read_text(encoding="utf-8"))
        current = registry["record"]
        self.assertEqual(registry["sha256"], core._digest(current))
        self.assertEqual(current["generation"], previous["generation"] + 1)
        self.assertEqual(current["previous_registry_sha256"], core._digest(previous))
        self.assertEqual(current["previous_index_sha256"], previous["index_sha256"])

    def test_dry_run_no_writes_or_models(self):
        before = sorted(str(p) for p in self.root.rglob("*"))
        result = self.run_theme(dry_run=True)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["model_invoked"])
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob("*")))
        self.assertEqual(self.reader.requests, [])

    def test_concurrent_run_blocked(self):
        lock = self.config.paths.lock_file.with_name(self.config.paths.lock_file.name + ".themes")
        with PipelineRunLock(lock):
            result = self.run_theme()
        self.assertEqual(result["error"]["code"], "TASK_STORE_BUSY")
        self.assertEqual(self.reader.requests, [])

    def test_deadline_no_model(self):
        result = self.run_theme(remaining_seconds=lambda: 0)
        self.assertEqual(result["error"]["code"], "RUN_TIME_LIMIT")
        self.assertEqual(self.reader.requests, [])

    def test_path_containment_and_no_clobber(self):
        with self.assertRaises(ThemeError):
            _safe_path(self.root, "..", "outside")
        path = self.root / "immutable.md"
        _publish(path, "one")
        _publish(path, "one")
        with self.assertRaises(ThemeError):
            _publish(path, "two")


class ThemeConfigTests(unittest.TestCase):
    def test_config_inheritance_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_config(root)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(load_config(path).theme_pipeline.enabled)
            data["theme_pipeline"] = {"enabled": True, "research_goal": "灾害链", "assets_dir": "custom-themes"}
            path.write_text(json.dumps(data), encoding="utf-8")
            config = load_config(path)
            self.assertEqual(config.theme_pipeline.assets_dir, root / "custom-themes")
            self.assertIsNone(config.theme_pipeline.model)
            for value in ({"enabled": "yes"}, {"unknown": 1}, {"timeout_seconds": 0}, {"timeout_seconds": float("inf")}, {"reasoning_effort": "bad"}):
                data["theme_pipeline"] = value
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_config(path)

    def test_cli_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp))
            output = {"ok": True, "operation": "themes_run", "status": "LOCAL_PREVIEW"}
            with patch("hydrolitagent.cards.cli.run_themes", return_value=output) as operation, redirect_stdout(io.StringIO()) as stream:
                code = main(["themes-run", "--config", str(path), "--json", "--dry-run"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stream.getvalue()), output)
            self.assertTrue(operation.call_args.kwargs["dry_run"])


if __name__ == "__main__":
    unittest.main()
