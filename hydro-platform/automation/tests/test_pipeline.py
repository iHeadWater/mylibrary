from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.card_generation import generate_evidence_card
from hydro_platform.cli import main
from hydro_platform.config import ConfigError, PipelineConfig, load_config
from hydro_platform.evidence_packages import find_evidence_package, load_evidence_manifest
from hydro_platform.pipeline import run_once
from hydro_platform.publication import publication_path, validate_saved_package
from hydro_platform.tasks import PipelineRunLock, _pid_running, build_task_id, load_task_registry, reconcile_tasks, save_task_registry, sync_tasks
from test_card_generation import GenerationFixture, FakeAdapter, FailingAdapter, NOW, PARENT_KEY, PDF_HASH
from test_config import write_config


class ReadyAdapter(FakeAdapter):
    def preflight(self):
        return {"ok": True}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.f = GenerationFixture(root)
        self.config_path = write_config(root)
        config = load_config(self.config_path)
        self.config = replace(config,
            card_generator=replace(config.card_generator, workflow_mode="single_agent", multi_agent_workflow=None),
            paths=replace(config.paths, evidence_card_generation_prompt_file=self.f.prompt))
        self.adapter = ReadyAdapter()
        self.generated = []
        self.factory_configs = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.zotero_check = self.stack.enter_context(patch("hydro_platform.pipeline.preflight", return_value={"ok": True}))
        self.sync = self.stack.enter_context(patch("hydro_platform.pipeline.sync_tasks", side_effect=self.local_sync))
        self.stack.enter_context(patch("hydro_platform.pipeline.build_card_generator_adapter", side_effect=self.factory))
        self.stack.enter_context(patch("hydro_platform.pipeline.generate_evidence_card", side_effect=self.generate))

    def registry(self):
        return load_task_registry(self.f.task_path, self.f.zotero.group_id)

    def local_sync(self, *args, **kwargs):
        return {"tasks": list(self.registry()["tasks"].values())}

    def factory(self, config, **kwargs):
        self.factory_configs.append(config)
        return self.adapter

    def generate(self, *args, **kwargs):
        self.generated.append(args[10])
        def delivery(*delivery_args, **delivery_kwargs):
            key = delivery_args[-1]
            task = self.registry()["tasks"][key]
            package = find_evidence_package(self.f.evidence_root, key)
            return replace(self.f.delivery(), parent_key=key, task_id=task["task_id"],
                           pdf_sha256=task["input"]["pdf_sha256"],
                           evidence_package_path=package, manifest_path=package / "manifest.json")
        return generate_evidence_card(*args, **kwargs, delivery_preparer=delivery)

    def set_tasks(self, mutate):
        registry = self.registry()
        mutate(registry["tasks"])
        save_task_registry(self.f.task_path, registry)

    def add_task(self, key="ITEM0002", state="READY_FOR_EXTRACTION"):
        def mutate(tasks):
            task = deepcopy(tasks[PARENT_KEY])
            task.update(parent_key=key, record_id=f"{self.f.zotero.group_id}:{key}", state=state,
                        task_id=build_task_id(self.f.zotero.group_id, key, task["input"]["attachment_key"], PDF_HASH))
            tasks[key] = task
        self.set_tasks(mutate)

    def run_pipeline(self, **kwargs):
        return run_once(self.config, now=NOW + timedelta(hours=3), **kwargs)

    def test_one_command_generates_and_second_run_skips_without_model(self):
        first = self.run_pipeline()
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["counts"]["completed"], 1)
        self.assertEqual(len(self.adapter.calls), 1)
        protected = [self.f.package / "card.md", self.f.package / "manifest.json", self.f.package / "quality-audit.json"]
        before = [p.read_bytes() for p in protected]
        self.generated.clear()
        second = self.run_pipeline()
        self.assertEqual(second["counts"]["skipped"], 1)
        self.assertEqual(second["generation_attempt_count"], 0)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(self.generated, [])
        self.assertEqual(before, [p.read_bytes() for p in protected])
        self.assertEqual(json.loads(Path(second["report_path"]).read_text(encoding="utf-8")), second)

    def test_batch_cap_does_not_create_packages_for_deferred_items(self):
        self.config = replace(self.config, pipeline=replace(self.config.pipeline, max_items_per_run=1))
        self.add_task()
        result = self.run_pipeline()
        self.assertEqual(result["generation_attempt_count"], 1)
        self.assertEqual(result["counts"]["deferred"], 1)
        self.assertIsNone(find_evidence_package(self.f.evidence_root, "ITEM0002"))
        again = self.run_pipeline()
        self.assertEqual(again["counts"]["completed"], 1)
        self.assertEqual(self.generated, [PARENT_KEY, "ITEM0002"])

    def test_activity_and_daily_reporting_are_integrated_without_more_models(self):
        from hydro_platform.activity import load_ledger
        self.config = replace(self.config, activity_reporting=replace(self.config.activity_reporting, enabled=True))
        def monitored_sync(*args, **kwargs):
            kwargs["snapshot_consumer"]({"group_id": self.config.zotero.group_id,
                "parents": {PARENT_KEY: {"title": "Test paper"}}, "pdf_attachments": {}})
            return self.local_sync()
        self.sync.side_effect = monitored_sync
        first = self.run_pipeline()
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["activity_reporting"]["after_generation"]["added_event_count"], 1)
        self.assertTrue(Path(first["activity_reporting"]["daily_report"]["report_path"]).exists())
        self.assertEqual(len(self.adapter.calls), 1)
        second = self.run_pipeline()
        self.assertTrue(second["ok"], second)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(len(load_ledger(self.config)[1]["events"]), 1)

    def test_reporting_failure_does_not_roll_back_or_regenerate_cards(self):
        self.config = replace(self.config, activity_reporting=replace(self.config.activity_reporting, enabled=True))
        with patch("hydro_platform.pipeline.daily_report", side_effect=OSError("fixture")):
            first = self.run_pipeline()
            second = self.run_pipeline()
        self.assertFalse(first["ok"])
        self.assertFalse(second["ok"])
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertIsNotNone(validate_saved_package(self.f.package))
        self.assertEqual(second["activity_reporting"]["errors"][0]["code"], "DAILY_REPORT_FAILED")

    def test_enabled_themes_run_after_cards_in_same_command(self):
        self.config = replace(self.config, theme_pipeline=replace(self.config.theme_pipeline, enabled=True))
        with patch("hydro_platform.pipeline.run_themes", return_value={"ok": True, "status": "CANDIDATES_REFINED"}) as themes:
            result = self.run_pipeline()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["counts"]["completed"], 1)
        themes.assert_called_once()
        self.assertEqual(result["theme_pipeline"]["status"], "CANDIDATES_REFINED")

    def test_themes_failure_is_reported_without_undoing_saved_cards(self):
        self.config = replace(self.config, theme_pipeline=replace(self.config.theme_pipeline, enabled=True))
        with patch("hydro_platform.pipeline.run_themes", return_value={"ok": False, "status": "BLOCKED"}):
            result = self.run_pipeline()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "COMPLETED_WITH_BLOCKERS")
        self.assertIsNotNone(validate_saved_package(self.f.package))

    def test_deferred_cards_do_not_make_transient_theme_batches(self):
        self.config = replace(self.config, theme_pipeline=replace(self.config.theme_pipeline, enabled=True),
            pipeline=replace(self.config.pipeline, max_items_per_run=1))
        self.add_task()
        with patch("hydro_platform.pipeline.run_themes") as themes:
            result = self.run_pipeline()
        themes.assert_not_called()
        self.assertEqual(result["theme_pipeline"]["status"], "DEFERRED")

    def test_missing_pdf_is_waited_then_later_pdf_is_processed(self):
        original = deepcopy(self.registry()["tasks"][PARENT_KEY])
        self.set_tasks(lambda tasks: tasks[PARENT_KEY].update(state="WAITING_FOR_PDF", reason_code="PDF_MISSING",
                                                             task_id=None, input={"attachment_key": None, "pdf_sha256": None}))
        waiting = self.run_pipeline()
        self.assertTrue(waiting["ok"])
        self.assertEqual(waiting["counts"]["waiting"], 1)
        self.assertEqual(waiting["status"], "COMPLETED_WITH_PENDING")
        self.assertFalse(self.adapter.calls)
        def sync_after_pdf(*args, **kwargs):
            registry = self.registry()
            reconcile_tasks(registry, {"group_id": self.f.zotero.group_id, "parents": {
                PARENT_KEY: {"title": "Test paper"}}}, {PARENT_KEY: {
                "gate_status": "READY", "reason_code": "PDF_READY", "message": "ready", "pdf": {
                    "attachment_key": original["input"]["attachment_key"], "sha256": PDF_HASH}}}, self.f.tasks, now=NOW)
            save_task_registry(self.f.task_path, registry)
            return self.local_sync()
        self.sync.side_effect = sync_after_pdf
        result = self.run_pipeline()
        self.assertEqual(result["new_discovered_count"], 0)
        self.assertEqual(result["counts"]["completed"], 1)

    def test_file_sync_and_index_wait_defer_themes_without_model_retry(self):
        self.config = replace(self.config, theme_pipeline=replace(self.config.theme_pipeline, enabled=True))
        for reason in ("PDF_FILE_NOT_SYNCED", "FULLTEXT_NOT_INDEXED"):
            with self.subTest(reason=reason):
                self.set_tasks(lambda tasks: tasks[PARENT_KEY].update(state="WAITING_FOR_FILE_SYNC", reason_code=reason))
                with patch("hydro_platform.pipeline.run_themes") as themes:
                    result = self.run_pipeline()
                themes.assert_not_called()
                self.assertEqual(result["status"], "COMPLETED_WITH_PENDING")
                self.assertEqual(result["theme_pipeline"]["status"], "DEFERRED")
                self.assertFalse(self.adapter.calls)

    def test_no_pdf_does_not_permanently_starve_themes_for_existing_cards(self):
        self.config = replace(self.config, theme_pipeline=replace(self.config.theme_pipeline, enabled=True))
        self.add_task(state="WAITING_FOR_PDF")
        self.set_tasks(lambda tasks: tasks["ITEM0002"].update(reason_code="PDF_MISSING"))
        with patch("hydro_platform.pipeline.run_themes", return_value={"ok": True, "status": "CANDIDATES_REFINED"}) as themes:
            result = self.run_pipeline()
        themes.assert_called_once()
        self.assertEqual(result["counts"]["completed"], 1)
        self.assertEqual(result["status"], "COMPLETED_WITH_PENDING")

    def test_startup_timeout_keeps_task_and_model_untouched(self):
        self.config = replace(self.config, zotero=replace(self.config.zotero,
            startup=replace(self.config.zotero.startup, enabled=True)))
        before = self.f.task_path.read_bytes()
        with patch("hydro_platform.pipeline.ensure_zotero_ready", return_value={"ok": False,
            "error": {"code": "ZOTERO_READY_TIMEOUT", "message": "timeout"}}):
            result = self.run_pipeline()
        self.assertEqual(result["error"]["code"], "ZOTERO_READY_TIMEOUT")
        self.sync.assert_not_called()
        self.assertFalse(self.factory_configs)
        self.assertEqual(self.f.task_path.read_bytes(), before)

    def test_scheduler_revisits_pending_pipeline_without_regenerating_completed_card(self):
        from hydro_platform.scheduled import scheduled_tick
        self.config = replace(self.config, scheduler=replace(self.config.scheduler, enabled=True))
        self.add_task(state="WAITING_FOR_FILE_SYNC")
        self.set_tasks(lambda tasks: tasks["ITEM0002"].update(reason_code="PDF_FILE_NOT_SYNCED"))
        first = scheduled_tick(self.config, now=NOW, pipeline=lambda cfg: run_once(cfg, now=NOW))
        self.assertEqual(first["status"], "PENDING")
        card = (self.f.package / "card.md").read_bytes()
        self.assertEqual(self.generated, [PARENT_KEY])
        self.set_tasks(lambda tasks: tasks["ITEM0002"].update(state="READY_FOR_EXTRACTION", reason_code="PDF_READY"))
        later = NOW + timedelta(hours=1)
        second = scheduled_tick(self.config, now=later, pipeline=lambda cfg: run_once(cfg, now=later))
        self.assertEqual(second["status"], "COMPLETED")
        self.assertEqual(self.generated, [PARENT_KEY, "ITEM0002"])
        self.assertEqual((self.f.package / "card.md").read_bytes(), card)
        third = scheduled_tick(self.config, now=later + timedelta(hours=1),
                               pipeline=lambda cfg: self.fail("completed slot must not rerun"))
        self.assertEqual(third["status"], "ALREADY_COMPLETED")

    def test_quality_failure_and_exhausted_retries_are_not_rerun(self):
        for values in ({"state": "QUALITY_FAILED"}, {"state": "RETRY_PENDING", "attempt_count": 3}):
            with self.subTest(values=values):
                self.set_tasks(lambda tasks: tasks[PARENT_KEY].update(values))
                result = self.run_pipeline()
                self.assertFalse(result["ok"])
                self.assertEqual(result["counts"]["blocked"], 1)
                self.assertFalse(self.adapter.calls)

    def test_retry_cooldown_then_single_retry(self):
        self.set_tasks(lambda tasks: tasks[PARENT_KEY].update(state="RETRY_PENDING", attempt_count=1,
            reason_code="CODEX_SERVICE_UNAVAILABLE",
            updated_at=(NOW + timedelta(hours=3)).isoformat()))
        result = self.run_pipeline()
        self.assertEqual(result["counts"]["deferred"], 1)
        self.assertFalse(self.adapter.calls)
        later = run_once(self.config, now=NOW + timedelta(hours=5))
        self.assertEqual(later["counts"]["completed"], 1)
        self.assertEqual(self.registry()["tasks"][PARENT_KEY]["attempt_count"], 2)

    def test_service_failure_stops_other_model_calls_and_retains_summary(self):
        self.add_task()
        self.config = replace(self.config, pipeline=replace(self.config.pipeline, max_items_per_run=3))
        class FailingReady(FailingAdapter):
            def preflight(self):
                return {"ok": True}
        self.adapter = FailingReady()
        result = self.run_pipeline()
        self.assertFalse(result["ok"])
        self.assertEqual(result["counts"]["failed"], 1)
        self.assertEqual(result["counts"]["deferred"], 1)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(self.registry()["tasks"][PARENT_KEY]["state"], "RETRY_PENDING")
        self.assertTrue(Path(result["report_path"]).is_file())

    def test_preflight_failure_does_not_scan_or_call_model(self):
        self.zotero_check.return_value = {"ok": False, "error": {"code": "ZOTERO_NOT_RUNNING", "message": "closed"}}
        before = self.f.task_path.read_bytes()
        result = self.run_pipeline()
        self.assertFalse(result["ok"])
        self.sync.assert_not_called()
        self.assertFalse(self.factory_configs)
        self.assertEqual(self.f.task_path.read_bytes(), before)

    def test_generator_preflight_failure_leaves_task_unclaimed(self):
        self.adapter.preflight = lambda: {"ok": False, "error": {"code": "AUTH_FAILED", "message": "login required"}}
        result = self.run_pipeline()
        self.assertFalse(result["ok"])
        self.assertEqual(self.registry()["tasks"][PARENT_KEY]["attempt_count"], 0)
        self.assertFalse(self.adapter.calls)

    def test_live_run_lock_prevents_a_second_scan(self):
        lock_path = self.config.paths.lock_file.with_name(self.config.paths.lock_file.name + ".pipeline")
        with PipelineRunLock(lock_path):
            result = self.run_pipeline()
        self.assertEqual(result["status"], "ALREADY_RUNNING")
        self.zotero_check.assert_not_called()
        self.sync.assert_not_called()
        self.assertFalse(self.adapter.calls)

    def test_time_limit_does_not_start_a_model(self):
        self.config = replace(self.config, pipeline=replace(self.config.pipeline, max_run_seconds=1))
        times = iter([0, 2, 2])
        result = self.run_pipeline(clock=lambda: next(times))
        self.assertEqual(result["counts"]["deferred"], 1)
        self.assertEqual(result["items"][0]["reason_code"], "RUN_TIME_LIMIT")
        self.assertFalse(self.adapter.calls)

    def test_model_timeout_is_bounded_by_remaining_run_time(self):
        self.config = replace(self.config, pipeline=replace(self.config.pipeline, max_run_seconds=20))
        result = self.run_pipeline(clock=lambda: 0)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.factory_configs[-1].generation_timeout_seconds, 20)

    def test_existing_user_edits_or_changed_input_are_not_overwritten(self):
        self.f.generate(FakeAdapter())
        for mutation in ("card", "input"):
            with self.subTest(mutation=mutation):
                if mutation == "card":
                    (self.f.package / "card.md").write_text("user edited", encoding="utf-8")
                else:
                    self.set_tasks(lambda tasks: tasks[PARENT_KEY].update(state="READY_FOR_EXTRACTION",
                        input={"attachment_key": "WXYZ5678", "pdf_sha256": "d" * 64},
                        task_id=build_task_id(self.f.zotero.group_id, PARENT_KEY, "WXYZ5678", "d" * 64)))
                before = (self.f.package / "card.md").read_bytes()
                result = self.run_pipeline()
                self.assertEqual(result["counts"]["blocked"], 1)
                self.assertEqual((self.f.package / "card.md").read_bytes(), before)
                self.assertFalse(self.adapter.calls)

    def test_active_task_lease_is_not_interrupted(self):
        self.set_tasks(lambda tasks: tasks[PARENT_KEY].update(state="PROCESSING", lease={
            "token": "private", "expires_at": (NOW + timedelta(hours=4)).isoformat()}))
        result = self.run_pipeline()
        self.assertEqual(result["items"][0]["reason_code"], "ACTIVE_LEASE")
        self.assertNotIn("private", json.dumps(result))
        self.assertFalse(self.adapter.calls)

    def test_dry_run_is_offline_and_read_only_including_cli(self):
        before = {p: p.read_bytes() for p in self.f.root.rglob("*") if p.is_file()}
        stdout = io.StringIO()
        with patch("hydro_platform.cli.load_config", return_value=self.config), redirect_stdout(stdout):
            code = main(["run-once", "--dry-run", "--json"])
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "LOCAL_PREVIEW")
        self.assertFalse(result["model_invoked"])
        self.assertFalse(self.factory_configs)
        self.zotero_check.assert_not_called()
        self.assertEqual({p: p.read_bytes() for p in self.f.root.rglob("*") if p.is_file()}, before)

    def test_newly_discovered_item_count_comes_from_task_inventory(self):
        original = self.registry()
        save_task_registry(self.f.task_path, {**original, "tasks": {}})
        def sync_new(*args, **kwargs):
            save_task_registry(self.f.task_path, original)
            return self.local_sync()
        self.sync.side_effect = sync_new
        result = self.run_pipeline()
        self.assertEqual(result["new_discovered_count"], 1)
        self.assertEqual(result["counts"]["completed"], 1)

    def test_config_default_limits_and_strict_integer_validation(self):
        self.assertEqual(load_config(self.config_path).pipeline, PipelineConfig())
        self.assertIsNone(self.config.pipeline.max_items_per_run)
        self.assertIsNone(self.config.pipeline.max_run_seconds)
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        for values in ({"unknown": 1}, {"max_items_per_run": True}, {"max_items_per_run": 0},
                       {"max_run_seconds": 1.5}, {"max_attempts_per_item": -1}, {"retry_cooldown_seconds": "soon"},
                       {"max_attempts_per_item": None}, {"retry_cooldown_seconds": None}):
            with self.subTest(values=values):
                self.config_path.write_text(json.dumps({**data, "pipeline": values}), encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_config(self.config_path)

    def test_default_drains_initial_queue_in_one_command_and_prints_formal_paths(self):
        self.add_task()
        self.add_task("ITEM0003")
        events = []
        result = self.run_pipeline(progress=events.append)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["generation_attempt_count"], 3)
        self.assertEqual(result["counts"]["completed"], 3)
        self.assertEqual(result["counts"]["deferred"], 0)
        self.assertEqual(self.sync.call_count, 1)
        for item in result["items"]:
            self.assertIn("card_state:", Path(item["card_path"]).read_text(encoding="utf-8"))
        self.assertTrue(any("3/3" in e.get("message", "") for e in events))
        self.assertTrue(any("正式卡片：" in e.get("message", "") for e in events))
        again = self.run_pipeline()
        self.assertEqual(again["counts"]["skipped"], 3)
        self.assertEqual(len(self.adapter.calls), 3)

    def test_no_overall_timeout_by_default_and_individual_timeout_retained(self):
        self.add_task()
        moment = [0]
        def clock():
            moment[0] += 1900
            return moment[0]
        result = self.run_pipeline(clock=clock)
        self.assertEqual(result["counts"]["completed"], 2)
        self.assertEqual(self.factory_configs[-1].generation_timeout_seconds,
                         self.config.card_generator.generation_timeout_seconds)

    def test_one_local_failure_does_not_stop_other_papers_or_repeat_failed_paper(self):
        from hydro_platform.card_generation import CardGenerationError
        self.add_task()
        self.add_task("ITEM0003")
        original_generate = self.generate
        def fail_first(*args, **kwargs):
            if args[10] == PARENT_KEY:
                raise CardGenerationError("SINGLE_CARD_CONTRACT_FAILED", "bad body",
                                          diagnostic={"draft_path": "saved.json"})
            return original_generate(*args, **kwargs)
        with patch("hydro_platform.pipeline.generate_evidence_card", side_effect=fail_first):
            result = self.run_pipeline()
        self.assertEqual(result["counts"]["failed"], 1)
        self.assertEqual(result["counts"]["completed"], 2)
        self.assertEqual(result["generation_attempt_count"], 3)
        self.assertEqual(result["items"][0]["error"]["draft_path"], "saved.json")

    def test_interruption_during_each_package_write_recovers_without_model(self):
        for name in ("quality-audit.json", "card.md", "manifest.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                f = GenerationFixture(Path(directory))
                original = load_evidence_manifest(f.package / "manifest.json")
                real_replace = os.replace
                def crash(source, destination):
                    if Path(destination) == f.package / name:
                        raise KeyboardInterrupt("simulated interruption")
                    return real_replace(source, destination)
                with patch("hydro_platform.card_generation.os.replace", side_effect=crash):
                    with self.assertRaises(KeyboardInterrupt):
                        f.generate(FakeAdapter())
                self.assertTrue(publication_path(f.lock_path, original).exists())
                previous_f, previous_config = self.f, self.config
                self.f = f
                self.config = replace(self.config, paths=replace(self.config.paths,
                    lock_file=f.lock_path, tasks_file=f.task_path, logs_dir=f.runtime / "logs",
                    evidence_packs_dir=f.evidence_root))
                result = self.run_pipeline()
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["counts"]["recovered"], 1)
                self.assertIsNotNone(validate_saved_package(f.package))
                self.assertFalse(publication_path(f.lock_path, original).exists())
                self.assertEqual(self.registry()["tasks"][PARENT_KEY]["state"], "COMPLETED")
                self.assertFalse(self.adapter.calls)
                self.f, self.config = previous_f, previous_config

    def test_crash_after_files_committed_recovers_task_completion_only(self):
        with patch("hydro_platform.card_generation.finish_task", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.f.generate(FakeAdapter())
        card = (self.f.package / "card.md").read_bytes()
        result = self.run_pipeline()
        self.assertEqual(result["counts"]["recovered"], 1)
        self.assertEqual((self.f.package / "card.md").read_bytes(), card)
        self.assertFalse(self.adapter.calls)

    def test_pending_record_does_not_overwrite_user_changes(self):
        real_replace = os.replace
        def crash(source, destination):
            if Path(destination) == self.f.package / "card.md":
                raise KeyboardInterrupt
            real_replace(source, destination)
        with patch("hydro_platform.card_generation.os.replace", side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                self.f.generate(FakeAdapter())
        (self.f.package / "card.md").write_text("user edit after crash", encoding="utf-8")
        result = self.run_pipeline()
        self.assertEqual(result["counts"]["blocked"], 1)
        self.assertEqual((self.f.package / "card.md").read_text(encoding="utf-8"), "user edit after crash")
        self.assertTrue(list((self.f.lock_path.parent / "pending-publications").glob("*.json")))
        self.assertFalse(self.adapter.calls)

    def test_local_task_state_loss_rebuilds_completion_without_regeneration(self):
        self.f.generate(FakeAdapter())
        original = self.registry()
        self.f.task_path.unlink()  # test fixture only, simulates loss of the disposable registry
        original["tasks"][PARENT_KEY].update(state="READY_FOR_EXTRACTION", attempt_count=0)
        def sync_restored(*args, **kwargs):
            save_task_registry(self.f.task_path, original)
            return self.local_sync()
        self.sync.side_effect = sync_restored
        result = self.run_pipeline()
        self.assertEqual(result["counts"]["recovered"], 1)
        self.assertFalse(self.adapter.calls)

    def test_liveness_probe_does_not_terminate_a_live_process(self):
        child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertTrue(_pid_running(child.pid))
            self.assertIsNone(child.poll())
        finally:
            child.communicate(timeout=5)
        self.assertFalse(_pid_running(child.pid))

    def test_real_task_sync_and_package_generation_with_fixture_zotero_client(self):
        from test_tasks import SyncClient
        self.f.pdf.write_bytes(b"%PDF-1.7\nfixture contents\n%%EOF\n")
        self.config = replace(self.config, pdf_gate=self.f.pdf_gate)
        self.sync.side_effect = lambda *args, **kwargs: sync_tasks(*args, **kwargs, client=SyncClient(self.f.pdf))
        first = self.run_pipeline()
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["new_discovered_count"], 1)
        self.assertEqual(self.generated, ["PARENT01"])
        self.assertEqual(self.registry()["tasks"]["PARENT01"]["state"], "COMPLETED")
        second = self.run_pipeline()
        self.assertEqual(second["generation_attempt_count"], 0)
        self.assertEqual(len(self.adapter.calls), 1)

    def test_nontransient_failure_does_not_regenerate_an_existing_draft(self):
        self.set_tasks(lambda tasks: tasks[PARENT_KEY].update(state="RETRY_PENDING", attempt_count=1,
            reason_code="CARD_GENERATION_STRUCTURE_INVALID", updated_at=NOW.isoformat()))
        result = self.run_pipeline()
        self.assertEqual(result["items"][0]["reason_code"], "NON_RETRYABLE_FAILURE")
        self.assertFalse(self.adapter.calls)

    def test_cancelled_generation_keeps_run_summary(self):
        self.adapter.generate = lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt())
        result = self.run_pipeline()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual(result["error"]["code"], "CANCELLED")
        self.assertEqual(result["items"][0]["parent_key"], PARENT_KEY)
        self.assertEqual(result["counts"]["failed"], 1)
        self.assertTrue(Path(result["report_path"]).exists())
        with PipelineRunLock(self.config.paths.lock_file.with_name(self.config.paths.lock_file.name + ".pipeline")):
            pass

    def test_publication_record_mismatch_is_retained_and_not_applied(self):
        real_replace = os.replace
        def crash(source, destination):
            if Path(destination) == self.f.package / "card.md":
                raise KeyboardInterrupt
            real_replace(source, destination)
        with patch("hydro_platform.card_generation.os.replace", side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                self.f.generate(FakeAdapter())
        journal = publication_path(self.f.lock_path, load_evidence_manifest(self.f.package / "manifest.json"))
        record = json.loads(journal.read_text(encoding="utf-8"))
        record["manifest"]["parent_key"] = "OTHER001"
        journal.write_text(json.dumps(record), encoding="utf-8")
        before = (self.f.package / "card.md").read_bytes()
        result = self.run_pipeline()
        self.assertEqual(result["counts"]["blocked"], 1)
        self.assertEqual(before, (self.f.package / "card.md").read_bytes())
        self.assertTrue(journal.exists())
        self.assertFalse(self.adapter.calls)

    def test_run_lock_is_released_after_holder_process_exits(self):
        lock_path = self.config.paths.lock_file.with_name(self.config.paths.lock_file.name + ".pipeline")
        source = str(Path(__file__).resolve().parents[1] / "src")
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from hydro_platform.tasks import PipelineRunLock; "
                "lock=PipelineRunLock(sys.argv[2]); lock.__enter__(); print('locked', flush=True); sys.stdin.read()")
        child = subprocess.Popen([sys.executable, "-c", code, source, str(lock_path)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(child.stdout.readline().strip(), b"locked")
            result = self.run_pipeline()
            self.assertEqual(result["status"], "ALREADY_RUNNING")
        finally:
            child.communicate(timeout=5)  # process exits without calling the lock's __exit__
        with PipelineRunLock(lock_path):
            pass


if __name__ == "__main__":
    unittest.main()
