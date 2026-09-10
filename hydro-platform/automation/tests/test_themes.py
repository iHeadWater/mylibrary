from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.cli import main
from hydro_platform.config import ConfigError, load_config
from hydro_platform.pdf_delivery import PdfDeliveryError
from hydro_platform.publication import text_hash
from hydro_platform.tasks import PipelineRunLock
from hydro_platform.themes import ThemeError, _publish, _safe_path, run_themes
from test_card_generation import GenerationFixture, FakeAdapter, PARENT_KEY
from test_config import write_config

ROOT = Path(__file__).resolve().parents[2]
EID = "EV-" + PARENT_KEY


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = GenerationFixture(self.root)
        self.path = write_config(self.root)
        config = load_config(self.path)
        self.config = replace(config, theme_pipeline=replace(config.theme_pipeline, enabled=True,
            assets_dir=ROOT / "templates/themes"), card_generator=replace(config.card_generator,
            pdf_reader=replace(config.card_generator.pdf_reader, adapter="local_path"),
            pdf_direct_trial=replace(config.card_generator.pdf_direct_trial,
                reading_prompt_file=ROOT / "automation/prompts/pdf-local-reading-v1.md")))
        # Build a real, validated legacy rough pack without a live provider.
        self.f.generate(FakeAdapter())
        self.pdf = self.root / "source.pdf"
        self.pdf.write_bytes(b"%PDF-theme-test-source")
        digest = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        manifest = json.loads((self.f.package / "manifest.json").read_text(encoding="utf-8"))
        manifest["pdf_sha256"] = digest
        (self.f.package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.delivery = Mock(return_value=replace(self.f.delivery(), pdf_path=self.pdf, pdf_sha256=digest))
        self.discovered = {"problem_clusters_markdown": "问题簇：测试材料。", "themes": [{"title": "主题一",
            "candidate_markdown": "自由格式初版。没有固定标题，也没有固定标签。", "paper_tasks": [
                {"evidence_id": EID, "focus": "尺度差异能否解释结论差别？"}]}]}
        self.text = Mock()
        self.text.generate.side_effect = self.text_result
        self.pdf_adapter = Mock()
        self.pdf_adapter.generate.return_value = {"ok": True, "ephemeral": True,
            "configured_model": "test-model", "configured_reasoning_effort": "high",
            "source_access": {"source_sha256": digest, "source_identity_verified": True,
                "parent_key": PARENT_KEY, "method": "local_pdf_path",
                "source_unchanged": True, "model_reading_report_accepted": True},
            "output": {"reading_markdown": "精读发现：原主题需要收窄。没有固定章节。"}}

    def text_result(self, prompt, **kwargs):
        self.assertIn("输入材料", prompt)
        if kwargs["output_schema_path"].name == "pool-discovery.schema.json":
            output = {"problem_clusters_markdown": self.discovered["problem_clusters_markdown"], "actions": [
                {"kind": "CREATE", "theme_ids": [], "reason": "测试新主题", "themes": [t]}
                for t in self.discovered["themes"]]}
        else:
            output = self.discovered if "discovery" in kwargs["output_schema_path"].name else {"revised_markdown": "精读后建议收窄主题，仍是候选。"}
        return {"ok": True, "output": deepcopy(output), "ephemeral": True, "model": "test-model"}

    def run_theme(self, **kwargs):
        return run_themes(self.config, text_adapter=self.text, pdf_adapter=self.pdf_adapter,
            delivery_preparer=self.delivery, **kwargs)

    def test_end_to_end_and_rerun_skip_preserve_main_files(self):
        protected = {p: p.read_bytes() for p in self.f.package.iterdir() if p.is_file()}
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "CANDIDATES_REFINED")
        self.assertEqual(result["model_call_count"], 3)
        pdf_call = self.pdf_adapter.generate.call_args.kwargs
        self.assertEqual(pdf_call["working_directory"], pdf_call["source_pdf_path"].parent)
        item = result["themes"][0]
        self.assertIn("原主题需要收窄", self.text.generate.call_args[0][0])
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

    def test_failed_pdf_resumes_no_repeat_discovery(self):
        success = self.pdf_adapter.generate.return_value
        self.pdf_adapter.generate.return_value = {"ok": False, "error": {"code": "CODEX_SERVICE_UNAVAILABLE", "message": "断线"}}
        first = self.run_theme()
        self.assertFalse(first["ok"])
        self.assertTrue(Path(first["themes"][0]["initial_path"]).exists())
        self.assertFalse((Path(first["themes"][0]["initial_path"]).parent / "revised.md").exists())
        self.pdf_adapter.generate.return_value = success
        second = self.run_theme()
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["model_call_count"], 2)

    def test_failed_refinement_resumes_without_pdf(self):
        def result(prompt, **kwargs):
            if "refinement" in kwargs["output_schema_path"].name:
                return {"ok": False, "error": {"code": "CODEX_SERVICE_UNAVAILABLE", "message": "断线"}}
            return self.text_result(prompt, **kwargs)
        self.text.generate.side_effect = result
        first = self.run_theme()
        self.assertFalse(first["ok"])
        self.text.generate.side_effect = self.text_result
        second = self.run_theme()
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["model_call_count"], 1)
        self.assertEqual(self.pdf_adapter.generate.call_count, 1)

    def test_duplicate_paper_tasks_merge_focus_once(self):
        self.discovered["themes"][0]["paper_tasks"].append({"evidence_id": EID, "focus": "再看图表"})
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.pdf_adapter.generate.call_count, 1)
        self.assertIn("再看图表", self.pdf_adapter.generate.call_args[0][0])

    def test_unknown_source_or_path_injection_rejected(self):
        self.discovered["themes"][0]["paper_tasks"][0]["evidence_id"] = "../../outside"
        result = self.run_theme()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "THEME_UNKNOWN_SOURCE")
        self.pdf_adapter.generate.assert_not_called()
        again = self.run_theme()
        self.assertEqual(again["model_call_count"], 0)  # preserve invalid raw result, no token loop

    def test_no_candidates_allowed(self):
        self.discovered["themes"] = []
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "NO_CANDIDATES")
        self.pdf_adapter.generate.assert_not_called()

    def test_no_cards_skips_all_models(self):
        self.config = replace(self.config, paths=replace(self.config.paths, evidence_packs_dir=self.root / "empty"))
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "NO_ROUGH_CARDS")
        self.text.generate.assert_not_called()

    def test_same_paper_gets_separate_readings_for_two_themes(self):
        second = deepcopy(self.discovered["themes"][0])
        second["title"] = "主题二"
        second["paper_tasks"][0]["focus"] = "验证方式的边界是什么？"
        self.discovered["themes"].append(second)
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["refined_count"], 2)
        self.assertEqual(self.pdf_adapter.generate.call_count, 2)
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
        base_result = deepcopy(self.pdf_adapter.generate.return_value)
        def read(prompt, **kwargs):
            result = deepcopy(base_result)
            result["source_access"]["parent_key"] = kwargs["zotero_parent_key"]
            result["output"]["reading_markdown"] += kwargs["zotero_parent_key"]
            return result
        self.pdf_adapter.generate.side_effect = read
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.pdf_adapter.generate.call_count, 2)
        self.assertEqual(len(result["themes"][0]["readings"]), 2)
        final_prompt = self.text.generate.call_args[0][0]
        self.assertIn(PARENT_KEY, final_prompt)
        self.assertIn(other_key, final_prompt)

    def test_source_edit_during_model_call_stops_publication(self):
        original = self.text_result
        def edit(prompt, **kwargs):
            result = original(prompt, **kwargs)
            with (self.f.package / "card.md").open("a", encoding="utf-8") as stream:
                stream.write("manual edit")
            return result
        self.text.generate.side_effect = edit
        result = self.run_theme()
        self.assertFalse(result["ok"])
        self.pdf_adapter.generate.assert_not_called()
        self.assertEqual(result["error"]["code"], "EVIDENCE_CARD_CHANGED")

    def test_missing_pdf_no_fake_reading_or_refinement(self):
        self.delivery.side_effect = PdfDeliveryError("PDF_MISSING", "未取得 PDF")
        result = self.run_theme()
        self.assertFalse(result["ok"])
        self.pdf_adapter.generate.assert_not_called()
        self.assertEqual(self.text.generate.call_count, 1)

    def test_wrong_pdf_rejected_before_model(self):
        self.pdf.write_bytes(b"changed PDF")
        result = self.run_theme()
        self.assertEqual(result["themes"][0]["error"]["code"], "THEME_PDF_MISMATCH")
        self.pdf_adapter.generate.assert_not_called()

    def test_empty_reading_blocked_but_no_format_gates(self):
        self.pdf_adapter.generate.return_value["output"]["reading_markdown"] = " "
        result = self.run_theme()
        self.assertEqual(result["themes"][0]["error"]["code"], "THEME_OUTPUT_EMPTY")
        self.assertEqual(self.text.generate.call_count, 1)

    def test_missing_pdf_process_record_cannot_pass(self):
        self.pdf_adapter.generate.return_value["source_access"] = {}
        result = self.run_theme()
        self.assertEqual(result["themes"][0]["error"]["code"], "THEME_READING_PROCESS_INVALID")

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
        with patch("hydro_platform.themes._publish", side_effect=fail):
            first = self.run_theme()
        self.assertFalse(first["ok"])
        second = self.run_theme()
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["model_call_count"], 1)
        self.assertEqual(self.pdf_adapter.generate.call_count, 1)

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

    def test_dry_run_no_writes_or_models(self):
        before = sorted(str(p) for p in self.root.rglob("*"))
        result = self.run_theme(dry_run=True)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["model_invoked"])
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob("*")))
        self.text.generate.assert_not_called()

    def test_concurrent_run_blocked(self):
        lock = self.config.paths.lock_file.with_name(self.config.paths.lock_file.name + ".themes")
        with PipelineRunLock(lock):
            result = self.run_theme()
        self.assertEqual(result["error"]["code"], "TASK_STORE_BUSY")
        self.text.generate.assert_not_called()

    def test_deadline_no_model(self):
        result = self.run_theme(remaining_seconds=lambda: 0)
        self.assertEqual(result["error"]["code"], "RUN_TIME_LIMIT")
        self.text.generate.assert_not_called()

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
            with patch("hydro_platform.cli.run_themes", return_value=output) as operation, redirect_stdout(io.StringIO()) as stream:
                code = main(["themes-run", "--config", str(path), "--json", "--dry-run"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stream.getvalue()), output)
            self.assertTrue(operation.call_args.kwargs["dry_run"])


if __name__ == "__main__":
    unittest.main()
