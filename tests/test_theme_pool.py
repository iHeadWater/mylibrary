from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from hydrolitagent.cards import themes, theme_pool as pool
from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.config import load_config
from hydrolitagent.cards.domain.source_access import LOCAL_PDF_PATH, MARKDOWN_PREPARED
from hydrolitagent.cards.publication import atomic_text
from hydrolitagent.cards.themes import run_themes
import test_themes as fixtures
from test_config import write_config

class ThemePoolTests(unittest.TestCase):
    setUp = fixtures.ThemeTests.setUp
    discovery_output = fixtures.ThemeTests.discovery_output
    reading_output = fixtures.ThemeTests.reading_output
    answer = fixtures.ThemeTests.answer
    run_theme = fixtures.ThemeTests.run_theme
    calls = fixtures.ThemeTests.calls
    changed_goal = fixtures.ThemeTests.changed_goal

    def entries(self):
        return pool.load(self.config)["themes"]

    def actions(self, actions):
        self.discovery_actions = deepcopy(actions)

    def child(self, title="更新的主题", focus=None, reuse=None):
        child = deepcopy(self.discovered["themes"][0])
        child["title"] = title
        if focus:
            child["paper_tasks"][0]["focus"] = focus
        child["paper_tasks"][0].update(reuse_reading_id=reuse, reuse_reason="原精读已回答本次问题" if reuse else None)
        return child

    def reading_id(self, entry):
        return entry["current"]["readings"][0]["reading_id"]

    def add_paper(self, key="ITEM0002"):
        other = self.f.package.parent / ("EV-" + key + "-test")
        shutil.copytree(self.f.package, other, ignore=shutil.ignore_patterns("readings"))
        path = other / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest.update(parent_key=key, evidence_id="EV-" + key)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        base = self.delivery.return_value
        self.delivery.side_effect = lambda *args, **kw: replace(base, parent_key=args[-1])
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
        self.reader.requests.clear()
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        self.assertEqual(list(self.entries()), [tid])
        updated = self.entries()[tid]
        self.assertEqual(len(updated["history"]), 2)
        self.assertEqual(updated["history"][0], before["current"])
        self.assertEqual(len(self.calls("focused_reading")), 1)  # only the newly added paper
        self.assertEqual(result["reused_reading_count"], 1)
        discovery_prompt = self.calls("theme_discovery")[0].prompt
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
        self.assertEqual(result["model_call_count"], 2)  # planner and refinement, no reading
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
        seen = {"count": 0}
        def fail_second(request):
            if request.role != "theme_synthesis":
                return False
            seen["count"] += 1
            return seen["count"] == 2
        self.fail_hooks.append(fail_second)
        failed = self.run_theme()
        self.assertFalse(failed["ok"])
        self.assertEqual(pool.load(self.config), base)
        self.fail_hooks.clear()
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
        self.reader.requests.clear()
        result = self.run_theme()
        self.assertTrue(result["ok"], result)
        readings = self.calls("focused_reading")
        self.assertEqual(len(readings), 1)
        self.assertIn("现在考察另一个机制", readings[0].prompt)

    def test_unchanged_input_does_not_invoke_planner(self):
        first = self.run_theme()
        self.reader.requests.clear()
        again = self.run_theme()
        self.assertTrue(again["ok"], again)
        self.assertEqual(self.reader.requests, [])
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
        sources = themes._sources(self.config, literature_root=self.root / "literature")
        catalog = pool.reading_catalog(self.config, state)
        action = {"problem_clusters_markdown": "reason", "actions": [
            {"kind": "UPDATE", "theme_ids": [tid], "reason": "change", "themes": [self.child()]}]}
        for status in ("FORMAL", pool.RETIRED):
            modified = deepcopy(state)
            modified["themes"][tid]["status"] = status
            with self.assertRaises(themes.ThemeError) as error:
                pool.plan_actions(action, modified, sources, "CHANGE-test", catalog)
            self.assertEqual(error.exception.code, "THEME_PARENT_PROTECTED")

    def test_invalid_reuse_is_rejected_without_reading(self):
        self.run_theme()
        tid = next(iter(self.entries()))
        self.changed_goal()
        self.actions([{"kind": "UPDATE", "theme_ids": [tid], "reason": "change",
                       "themes": [self.child(reuse="RD-invented")]}])
        self.reader.requests.clear()
        result = self.run_theme()
        self.assertEqual(result["error"]["code"], "THEME_REUSE_INVALID")
        self.assertEqual(self.calls("focused_reading"), [])
        self.assertEqual(self.run_theme()["model_call_count"], 0)  # invalid output is retained, not regenerated

    def test_registry_publish_failure_recovers_initial_commit_without_model(self):
        def fail(path, text):
            if path.name == "_registry.json":
                raise OSError("disk full")
            atomic_text(path, text)
        with patch("hydrolitagent.cards.theme_pool.atomic_text", side_effect=fail):
            first = self.run_theme()
        self.assertFalse(first["ok"])
        self.reader.requests.clear()
        recovered = self.run_theme()
        self.assertTrue(recovered["ok"], recovered)
        self.assertEqual(recovered["model_call_count"], 0)

    def test_index_publish_failure_repairs_from_registry_without_model(self):
        def fail(path, text):
            if path.name == "index.md":
                raise OSError("test")
            atomic_text(path, text)
        with patch("hydrolitagent.cards.theme_pool.atomic_text", side_effect=fail):
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

    def test_current_state_conflict_during_model_keeps_original_topics(self):
        self.run_theme()
        self.changed_goal()
        def edit(request, output):
            state = pool.load(self.config)
            path = pool.root_path(self.config, next(iter(state["themes"].values()))["current"]["directory"]) / "revised.md"
            path.write_text("保留我的修改", encoding="utf-8")
            return None
        self.answer_hooks.append(edit)
        result = self.run_theme()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "THEME_FILE_CONFLICT")

class LegacyPoolFixtureTests(unittest.TestCase):
    """Historical artifacts are read from static files; nothing regenerates them."""

    FIXTURES = Path(__file__).parent / "fixtures" / "legacy_themes"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(self.FIXTURES / "themes", self.root / "themes")
        shutil.copytree(self.FIXTURES / "evidence-packs", self.root / "evidence-packs")
        config = load_config(write_config(self.root))
        self.config = replace(config, theme_pipeline=replace(
            config.theme_pipeline, enabled=True, assets_dir=ASSETS_DIR / "templates/themes"))

    def snapshot(self):
        roots = (self.config.paths.themes_dir, self.config.paths.evidence_packs_dir)
        return {path: path.read_bytes() for root in roots for path in root.rglob("*") if path.is_file()}

    def test_static_pool_loads_and_historical_reading_stays_readable(self):
        state = pool.load(self.config)
        self.assertEqual(len(state["themes"]), 1)
        entry = next(iter(state["themes"].values()))
        ref = entry["current"]["readings"][0]
        record = pool._unwrap(pool.reading_path(self.config, ref) / "result.json")
        self.assertEqual(record["execution"]["source_access"]["method"], LOCAL_PDF_PATH)
        self.assertEqual(pool.check_reading(self.config, ref), record["output"]["reading_markdown"])
        self.assertNotIn(MARKDOWN_PREPARED, {
            r["execution"]["source_access"]["method"] for r in [record]})

    def test_migration_only_never_invokes_a_model_or_rewrites_bytes(self):
        before = self.snapshot()
        result = run_themes(self.config, pipeline=None, migration_only=True,
                            literature_root=self.root / "literature")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["model_call_count"], 0)
        self.assertEqual(result["action"], "UNCHANGED")
        self.assertEqual(before, self.snapshot())

    def test_dry_run_creates_nothing(self):
        before = self.snapshot()
        result = run_themes(self.config, pipeline=None, dry_run=True,
                            literature_root=self.root / "literature")
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["model_invoked"])
        self.assertEqual(before, self.snapshot())

    def test_static_legacy_batch_imports_without_rewriting_its_files(self):
        # A pool that has never been migrated only has the batch tree; the
        # registry, index and import commit are what migration adds.
        (self.config.paths.themes_dir / "_registry.json").unlink()
        (self.config.paths.themes_dir / "index.md").unlink()
        shutil.rmtree(self.config.paths.themes_dir / "changes")
        protected = {
            path: path.read_bytes()
            for root in (self.config.paths.themes_dir / "candidates",
                         self.config.paths.evidence_packs_dir)
            for path in root.rglob("*") if path.is_file()
        }
        result = run_themes(self.config, pipeline=None, migration_only=True,
                            literature_root=self.root / "literature")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["action"], "MIGRATED")
        self.assertEqual(result["imported_theme_count"], 1)
        self.assertEqual(result["model_call_count"], 0)
        self.assertEqual(protected, {path: path.read_bytes() for path in protected})
        ref = next(iter(pool.load(self.config)["themes"].values()))["current"]["readings"][0]
        self.assertEqual(pool.validate_reading(
            pool._unwrap(pool.reading_path(self.config, ref) / "result.json"), ref["source"]),
            "精读发现：原主题需要收窄。没有固定章节。")


if __name__ == "__main__":
    unittest.main()
