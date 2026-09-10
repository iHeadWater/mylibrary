from __future__ import annotations

import json
import shutil
import sys
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform import themes, theme_pool as pool
from hydro_platform.publication import atomic_text, text_hash
import test_themes as fixtures


class ThemePoolTests(unittest.TestCase):
    setUp = fixtures.ThemeTests.setUp
    text_result = fixtures.ThemeTests.text_result
    run_theme = fixtures.ThemeTests.run_theme

    def entries(self):
        return pool.load(self.config)["themes"]

    def actions(self, actions):
        def provider(prompt, **kwargs):
            if kwargs["output_schema_path"].name == "pool-discovery.schema.json":
                output = {"problem_clusters_markdown": "关联判断与变更理由", "actions": deepcopy(actions)}
                return {"ok": True, "ephemeral": True, "output": output}
            return self.text_result(prompt, **kwargs)
        self.text.generate.side_effect = provider

    def child(self, title="更新的主题", focus=None, reuse=None):
        child = deepcopy(self.discovered["themes"][0])
        child["title"] = title
        if focus:
            child["paper_tasks"][0]["focus"] = focus
        child["paper_tasks"][0].update(reuse_reading_id=reuse, reuse_reason="原精读已回答本次问题" if reuse else None)
        return child

    def reading_id(self, entry):
        return entry["current"]["readings"][0]["reading_id"]

    def changed_goal(self, goal="changed-goal"):
        self.config = replace(self.config, theme_pipeline=replace(self.config.theme_pipeline, research_goal=goal))

    def add_paper(self, key="ITEM0002"):
        other = self.f.package.parent / ("EV-" + key + "-test")
        shutil.copytree(self.f.package, other, ignore=shutil.ignore_patterns("readings"))
        path = other / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest.update(parent_key=key, evidence_id="EV-" + key)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        base = self.delivery.return_value
        self.delivery.side_effect = lambda *args, **kw: replace(base, parent_key=args[-1])
        result = deepcopy(self.pdf_adapter.generate.return_value)
        def read(prompt, **kw):
            value = deepcopy(result)
            value["source_access"]["parent_key"] = kw["zotero_parent_key"]
            return value
        self.pdf_adapter.generate.side_effect = read
        return "EV-" + key

    def two_themes(self):
        self.discovered["themes"].append(self.child("第二个问题", "不同的科学问题"))
        first = self.run_theme()
        self.assertTrue(first["ok"], first)
        return list(self.entries())

    def test_new_paper_updates_existing_identity_and_reuses_old_reading(self):
        self.assertTrue(self.run_theme()["ok"])
        tid, old = next(iter(self.entries().items()))
        before = deepcopy(old)
        new_eid = self.add_paper()
        child = self.child(reuse=self.reading_id(old))
        child["paper_tasks"].append({"evidence_id": new_eid, "focus": "补充新证据",
                                    "reuse_reading_id": None, "reuse_reason": None})
        self.actions([{"kind": "UPDATE", "theme_ids": [tid], "reason": "新旧文章共同回答同一问题", "themes": [child]}])
        self.text.generate.reset_mock()
        self.pdf_adapter.generate.reset_mock()
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(list(self.entries()), [tid])
        updated = self.entries()[tid]
        self.assertEqual(len(updated["history"]), 2)
        self.assertEqual(updated["history"][0], before["current"])
        self.assertEqual(self.pdf_adapter.generate.call_count, 1)  # only the newly added paper
        self.assertEqual(result["reused_reading_count"], 1)
        discovery_prompt = self.text.generate.call_args_list[0].args[0]
        self.assertIn(tid, discovery_prompt)
        self.assertIn(fixtures.EID, discovery_prompt)
        self.assertIn(new_eid, discovery_prompt)
        self.assertIn("精读后建议收窄", discovery_prompt)  # includes previous refined content, not just titles
        self.assertEqual(self.run_theme()["model_call_count"], 0)

    def test_merge_creates_new_identity_preserves_both_parents_and_readings(self):
        parents = self.two_themes()
        before = deepcopy(self.entries())
        self.changed_goal()
        child = self.child("合并后科学问题", reuse=self.reading_id(before[parents[0]]))
        self.actions([{"kind": "MERGE", "theme_ids": parents, "reason": "机制与证据关系一致", "themes": [child]}])
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        entries = self.entries()
        new = next(t for t in entries if t not in parents)
        self.assertEqual(entries[new]["predecessors"], parents)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["model_call_count"], 2)  # planner and refinement, not PDF
        for tid in parents:
            self.assertEqual(entries[tid]["status"], pool.RETIRED)
            self.assertEqual(entries[tid]["successors"], [new])
            self.assertEqual(entries[tid]["current"], before[tid]["current"])
        self.assertEqual(self.run_theme()["model_call_count"], 0)

    def test_split_keeps_parent_and_creates_two_children(self):
        self.run_theme()
        tid, before = next(iter(self.entries().items()))
        reuse = self.reading_id(before)
        self.changed_goal()
        self.actions([{"kind": "SPLIT", "theme_ids": [tid], "reason": "需区分两个机制",
            "themes": [self.child("子问题甲", reuse=reuse), self.child("子问题乙", reuse=reuse)]}])
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        entries = self.entries()
        self.assertEqual(entries[tid]["status"], pool.RETIRED)
        self.assertEqual(len(entries[tid]["successors"]), 2)
        self.assertEqual(result["reused_reading_count"], 2)
        for child in entries[tid]["successors"]:
            self.assertEqual(entries[child]["predecessors"], [tid])
        self.assertEqual(entries[tid]["current"], before["current"])

    def test_failed_split_is_not_visible_until_all_children_are_refined(self):
        self.run_theme()
        base = pool.load(self.config)
        tid, entry = next(iter(base["themes"].items()))
        self.changed_goal()
        self.actions([{"kind": "SPLIT", "theme_ids": [tid], "reason": "拆分",
            "themes": [self.child("甲", reuse=self.reading_id(entry)), self.child("乙", reuse=self.reading_id(entry))]}])
        provider = self.text.generate.side_effect
        count = 0
        def fail_second(prompt, **kwargs):
            nonlocal count
            if "refinement" in kwargs["output_schema_path"].name:
                count += 1
                if count == 2:
                    return {"ok": False, "error": {"code": "CODEX_SERVICE_UNAVAILABLE", "message": "test"}}
            return provider(prompt, **kwargs)
        self.text.generate.side_effect = fail_second
        failed = self.run_theme()
        self.assertFalse(failed["ok"])
        self.assertEqual(pool.load(self.config), base)
        self.text.generate.side_effect = provider
        recovered = self.run_theme()
        self.assertTrue(recovered["ok"], recovered)
        self.assertEqual(recovered["model_call_count"], 1)
        self.assertEqual(self.entries()[tid]["status"], pool.RETIRED)

    def test_changed_focus_can_request_new_original_pdf_reading(self):
        self.run_theme()
        tid = next(iter(self.entries()))
        self.changed_goal()
        self.actions([{"kind": "UPDATE", "theme_ids": [tid], "reason": "原精读未回答新重点",
                       "themes": [self.child(focus="现在考察另一个机制", reuse=None)]}])
        self.pdf_adapter.generate.reset_mock()
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.pdf_adapter.generate.call_count, 1)
        self.assertIn("现在考察另一个机制", self.pdf_adapter.generate.call_args.args[0])

    def test_unchanged_input_does_not_invoke_planner(self):
        first = self.run_theme()
        self.text.generate.reset_mock()
        self.pdf_adapter.generate.reset_mock()
        again = self.run_theme()
        self.assertTrue(again["ok"], again)
        self.text.generate.assert_not_called()
        self.pdf_adapter.generate.assert_not_called()
        self.assertEqual(first["themes"], again["themes"])

    def test_no_action_keeps_old_topics_and_records_inputs_as_processed(self):
        self.run_theme()
        before = deepcopy(self.entries())
        self.add_paper()
        self.actions([])
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["model_call_count"], 1)
        self.assertEqual(before, self.entries())
        self.assertEqual(self.run_theme()["model_call_count"], 0)

    def test_formal_and_retired_parents_cannot_be_mutated(self):
        self.run_theme()
        state = pool.load(self.config)
        tid = next(iter(state["themes"]))
        sources = themes._sources(self.config)
        catalog = pool.reading_catalog(self.config, state)
        action = {"problem_clusters_markdown": "reason", "actions": [
            {"kind": "UPDATE", "theme_ids": [tid], "reason": "change", "themes": [self.child()]}]}
        for status in ("FORMAL", pool.RETIRED):
            modified = deepcopy(state)
            modified["themes"][tid]["status"] = status
            with self.assertRaises(themes.ThemeError) as error:
                pool.plan_actions(action, modified, sources, "CHANGE-test", catalog)
            self.assertEqual(error.exception.code, "THEME_PARENT_PROTECTED")

    def test_invalid_reuse_is_rejected_without_pdf_calls(self):
        self.run_theme()
        tid = next(iter(self.entries()))
        self.changed_goal()
        self.actions([{"kind": "UPDATE", "theme_ids": [tid], "reason": "change",
                       "themes": [self.child(reuse="RD-invented")]}])
        self.pdf_adapter.generate.reset_mock()
        result = self.run_theme()
        self.assertEqual(result["error"]["code"], "THEME_REUSE_INVALID")
        self.pdf_adapter.generate.assert_not_called()
        self.assertEqual(self.run_theme()["model_call_count"], 0)  # invalid output is retained, not regenerated

    def test_registry_publish_failure_recovers_initial_commit_without_model(self):
        def fail(path, text):
            if path.name == "_registry.json":
                raise OSError("disk full")
            atomic_text(path, text)
        with patch("hydro_platform.theme_pool.atomic_text", side_effect=fail):
            first = self.run_theme()
        self.assertFalse(first["ok"])
        recovered = self.run_theme()
        self.assertTrue(recovered["ok"], recovered)
        self.assertEqual(recovered["model_call_count"], 0)

    def test_index_publish_failure_repairs_from_registry_without_model(self):
        def fail(path, text):
            if path.name == "index.md":
                raise OSError("test")
            atomic_text(path, text)
        with patch("hydro_platform.theme_pool.atomic_text", side_effect=fail):
            first = self.run_theme()
        self.assertFalse(first["ok"])
        again = self.run_theme()
        self.assertTrue(again["ok"], again)
        self.assertEqual(again["model_call_count"], 0)
        self.assertTrue(Path(again["index_path"]).exists())

    def test_unknown_index_is_preserved_before_model(self):
        self.config.paths.themes_dir.mkdir()
        path = self.config.paths.themes_dir / "index.md"
        path.write_text("我的入口", encoding="utf-8")
        result = self.run_theme()
        self.assertFalse(result["ok"])
        self.assertEqual(result["model_call_count"], 0)
        self.assertEqual(path.read_text(encoding="utf-8"), "我的入口")

    def test_legacy_migration_preserves_bytes_and_skips_regeneration(self):
        with patch("hydro_platform.themes._run", themes._run_legacy):
            legacy = self.run_theme()
        self.assertTrue(legacy["ok"], legacy)
        protected = {p: p.read_bytes() for root in (Path(legacy["batch_path"]), self.f.package)
                     for p in root.rglob("*") if p.is_file()}
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["imported_theme_count"], 1)
        self.assertEqual(result["model_call_count"], 0)
        self.assertEqual(result["themes"][0]["theme_id"], legacy["themes"][0]["theme_id"])
        self.assertTrue(all(p.read_bytes() == data for p, data in protected.items()))

    def test_multiple_legacy_batches_enter_one_planner_not_isolated_pools(self):
        with patch("hydro_platform.themes._run", themes._run_legacy):
            first = self.run_theme()
            self.changed_goal("legacy-second")
            second = self.run_theme()
        self.actions([])
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["imported_theme_count"], 2)
        self.assertEqual(result["model_call_count"], 1)
        prompt = self.text.generate.call_args.args[0]
        for old in (first, second):
            self.assertIn(old["themes"][0]["theme_id"], prompt)
        self.assertEqual(len(self.entries()), 2)

    def test_migration_only_never_invokes_model_even_if_input_changed(self):
        with patch("hydro_platform.themes._run", themes._run_legacy):
            self.run_theme()
        self.add_paper()
        self.text.generate.reset_mock()
        result = self.run_theme(migration_only=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["model_call_count"], 0)
        self.text.generate.assert_not_called()

    def test_legacy_migration_dry_run_creates_nothing(self):
        with patch("hydro_platform.themes._run", themes._run_legacy):
            self.run_theme()
        before = {str(p): p.read_bytes() for p in self.config.paths.themes_dir.rglob("*") if p.is_file()}
        result = self.run_theme(dry_run=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.config.paths.themes_dir.rglob("*") if p.is_file()})

    def test_current_state_conflict_during_model_keeps_original_topics(self):
        self.run_theme()
        self.changed_goal()
        original = self.text_result
        def edit(prompt, **kwargs):
            state = pool.load(self.config)
            path = pool.root_path(self.config, next(iter(state["themes"].values()))["current"]["directory"]) / "revised.md"
            path.write_text("保留我的修改", encoding="utf-8")
            return original(prompt, **kwargs)
        self.text.generate.side_effect = edit
        result = self.run_theme()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "THEME_FILE_CONFLICT")


if __name__ == "__main__":
    unittest.main()
