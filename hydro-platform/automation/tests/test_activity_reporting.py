from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.activity import ActivityError, actor_from, load_ledger, read_record, sync_activity, write_record
from hydro_platform.cli import main
from hydro_platform.config import ActivityReportingConfig, ConfigError, load_config
from hydro_platform.daily_report import daily_report
from hydro_platform.tasks import PipelineRunLock, load_task_registry, save_task_registry
from test_card_generation import GenerationFixture, FakeAdapter, NOW, PARENT_KEY, ATTACHMENT_KEY
from test_config import write_config

TODAY = datetime(2026, 9, 9, 2, 0, tzinfo=timezone.utc)


class ReportingFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = GenerationFixture(self.root)
        self.config_path = write_config(self.root)
        self.config = replace(load_config(self.config_path), activity_reporting=ActivityReportingConfig(enabled=True))
        self.source = {"schema_version": 1, "group_id": self.config.zotero.group_id,
                       "parents": {}, "pdf_attachments": {}}

    def sync(self, now=TODAY):
        return sync_activity(self.config, snapshot=self.source, now=now)

    def ledger(self):
        return load_ledger(self.config)[1]

    def add_paper(self):
        self.source["parents"][PARENT_KEY] = {"title": "Test paper", "date_added": "2026-09-09T01:00:00Z",
            "created_by_user": {"id": 101, "username": "student-a"}, "creators": [{"lastName": "Wrong author"}]}
        self.source["pdf_attachments"][ATTACHMENT_KEY] = {"parent_key": PARENT_KEY,
            "date_added": "2026-09-09T01:01:00Z", "created_by_user": {"id": 102, "username": "student-b"}}


class ActivityTests(ReportingFixture, unittest.TestCase):
    def test_reporting_configuration_is_centralized_and_validated(self):
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        data["activity_reporting"] = {"enabled": True, "utc_offset_minutes": -300, "system_actor_id": "SYS-TEST"}
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        config = load_config(self.config_path)
        self.assertEqual(config.activity_reporting.utc_offset_minutes, -300)
        self.assertEqual(config.activity_reporting.system_actor_id, "SYS-TEST")
        for bad in ({"enabled": "yes"}, {"utc_offset_minutes": True}, {"utc_offset_minutes": 841},
                    {"system_actor_id": ""}, {"unknown": 1}):
            with self.subTest(bad=bad):
                data["activity_reporting"] = bad
                self.config_path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_config(self.config_path)

    def test_first_observation_does_not_make_historical_events(self):
        self.f.generate(FakeAdapter())
        self.add_paper()
        result = self.sync()
        self.assertEqual(result["status"], "BASELINE_CREATED")
        self.assertEqual(result["added_event_count"], 0)
        self.assertEqual(self.ledger()["baseline"]["cards"], [PARENT_KEY])

    def test_paper_pdf_and_system_completion_have_separate_actors(self):
        self.sync()
        self.add_paper()
        self.f.generate(FakeAdapter())
        result = self.sync()
        self.assertEqual(result["added_event_count"], 3)
        events = {e["type"]: e for e in self.ledger()["events"].values()}
        self.assertEqual(events["PAPER_ADDED"]["actor"]["zotero_user_id"], 101)
        self.assertEqual(events["PDF_ADDED"]["actor"]["zotero_user_id"], 102)
        self.assertEqual(events["CARD_COMPLETED"]["actor"], {"kind": "SYSTEM", "member_id": "SYS-CARD-01"})
        self.assertNotIn("Wrong author", json.dumps(events))

    def test_duplicate_run_and_new_runtime_do_not_duplicate_events(self):
        self.sync()
        self.add_paper()
        self.sync()
        before = (self.config.paths.activity_dir / "ledger.json").read_bytes()
        fresh = self.root / "new-runtime"
        self.config = replace(self.config, paths=replace(self.config.paths, runtime_dir=fresh, lock_file=fresh / "lock"))
        result = self.sync(now=TODAY + timedelta(days=1))
        self.assertEqual(result["added_event_count"], 0)
        self.assertEqual(before, (self.config.paths.activity_dir / "ledger.json").read_bytes())

    def test_unknown_identity_never_uses_authors_or_last_modifier(self):
        self.sync()
        self.add_paper()
        self.source["parents"][PARENT_KEY].update(created_by_user=None,
            last_modified_by_user={"id": 199}, creatorSummary="Not contributor")
        self.sync()
        event = next(e for e in self.ledger()["events"].values() if e["type"] == "PAPER_ADDED")
        self.assertEqual(event["actor"]["kind"], "UNKNOWN")

    def test_removed_then_reappearing_key_is_not_double_counted(self):
        self.sync()
        self.add_paper()
        self.sync()
        saved = deepcopy(self.source)
        self.source["parents"].clear()
        self.source["pdf_attachments"].clear()
        self.sync()
        self.source = saved
        self.assertEqual(self.sync()["added_event_count"], 0)

    def test_member_mapping_is_optional_and_matches_only_user_id(self):
        mapping = self.root / "members" / "members.json"
        mapping.parent.mkdir()
        mapping.write_text(json.dumps({"schema_version": 1, "members": [
            {"member_id": "STU-001", "display_name": "同学甲", "zotero_user_id": 101}]}), encoding="utf-8")
        self.sync()
        self.add_paper()
        self.sync()
        events = {e["type"]: e for e in self.ledger()["events"].values()}
        self.assertEqual(events["PAPER_ADDED"]["actor"]["member_id"], "STU-001")
        self.assertNotIn("member_id", events["PDF_ADDED"]["actor"])

    def test_corrupted_ledger_is_preserved(self):
        self.sync()
        path = self.config.paths.activity_dir / "ledger.json"
        path.write_text("edited by user", encoding="utf-8")
        with self.assertRaisesRegex(ActivityError, "保留现场"):
            self.sync()
        self.assertEqual(path.read_text(encoding="utf-8"), "edited by user")

    def test_other_group_ledger_is_rejected(self):
        self.sync()
        path, ledger = load_ledger(self.config)
        ledger["group_id"] = 999
        write_record(path, ledger)
        with self.assertRaises(ActivityError) as context:
            self.sync()
        self.assertEqual(context.exception.code, "ACTIVITY_GROUP_MISMATCH")

    def test_changed_card_is_not_counted_as_completed(self):
        self.sync()
        self.f.generate(FakeAdapter())
        (self.f.package / "card.md").write_text("manual edit", encoding="utf-8")
        result = self.sync()
        self.assertFalse(result["ok"])
        self.assertEqual(result["added_event_count"], 0)
        self.assertEqual(result["issues"][0]["reason_code"], "EVIDENCE_CARD_CHANGED")

    def test_activity_lock_prevents_two_writers(self):
        lock = self.config.paths.lock_file.with_name(self.config.paths.lock_file.name + ".activity")
        with PipelineRunLock(lock):
            with self.assertRaisesRegex(RuntimeError, "已有"):
                self.sync()

    def test_no_local_paths_or_pdf_content_in_events(self):
        self.sync()
        self.add_paper()
        self.source["pdf_attachments"][ATTACHMENT_KEY].update(local_path="secret-local-path", content="pdf-fulltext")
        self.sync()
        content = json.dumps(self.ledger())
        self.assertNotIn("secret-local-path", content)
        self.assertNotIn("pdf-fulltext", content)

    def test_card_completed_after_initial_placeholder_is_recorded(self):
        self.add_paper()
        self.sync()
        self.f.generate(FakeAdapter())
        result = self.sync()
        self.assertEqual(result["added_event_count"], 1)
        self.assertEqual(next(iter(self.ledger()["events"].values()))["type"], "CARD_COMPLETED")

    def test_same_blocking_reason_is_recorded_once_not_every_retry(self):
        self.sync()
        run = {"group_id": self.config.zotero.group_id, "items": [
            {"parent_key": PARENT_KEY, "title": "Paper", "status": "WAITING", "reason_code": "PDF_MISSING"}]}
        first = sync_activity(self.config, snapshot=self.source, run_report=run, now=TODAY)
        again = sync_activity(self.config, snapshot=self.source, run_report=run, now=TODAY + timedelta(days=1))
        self.assertEqual(first["added_event_count"], 1)
        self.assertEqual(again["added_event_count"], 0)
        event = next(iter(self.ledger()["events"].values()))
        self.assertEqual(event["type"], "TASK_BLOCKED")
        self.assertEqual(event["actor"]["kind"], "SYSTEM")


class DailyTests(ReportingFixture, unittest.TestCase):
    def test_completed_task_without_its_card_is_reported_as_blocked(self):
        self.f.generate(FakeAdapter())
        self.config = replace(self.config, paths=replace(self.config.paths, evidence_packs_dir=self.root / "missing-packs"))
        result = daily_report(self.config, now=TODAY)
        report = read_record(Path(result["record_path"]))["report"]
        self.assertEqual(report["valid_card_count"], 0)
        self.assertEqual(report["open_items"][0]["reason_code"], "COMPLETED_CARD_UNAVAILABLE")

    def test_daily_separates_new_events_from_ongoing_blockers(self):
        self.sync()
        self.add_paper()
        self.sync()
        registry = load_task_registry(self.f.task_path, self.config.zotero.group_id)
        registry["tasks"][PARENT_KEY].update(state="WAITING_FOR_PDF", reason_code="PDF_MISSING")
        save_task_registry(self.f.task_path, registry)
        result = daily_report(self.config, now=TODAY + timedelta(days=1))
        record = read_record(Path(result["record_path"]))["report"]
        self.assertEqual(record["today_counts"], {})
        self.assertEqual(len(record["open_items"]), 1)
        self.assertEqual(record["open_items"][0]["reason_code"], "PDF_MISSING")
        self.assertFalse(record["run_observed_today"])

    def test_daily_uses_configured_date_boundary(self):
        self.sync()
        self.add_paper()
        self.sync(now=datetime(2026, 9, 8, 16, 5, tzinfo=timezone.utc))
        result = daily_report(self.config, now=TODAY)
        self.assertEqual(result["date"], "2026-09-09")
        self.assertEqual(result["today_counts"], {"PAPER_ADDED": 1, "PDF_ADDED": 1})

    def test_daily_repeated_run_updates_generated_report_without_duplicate_events(self):
        self.sync()
        self.add_paper()
        self.sync()
        first = daily_report(self.config, now=TODAY)
        again = daily_report(self.config, now=TODAY + timedelta(minutes=1))
        self.assertEqual(first["today_counts"], again["today_counts"])
        self.assertEqual(len(self.ledger()["events"]), 2)

    def test_manually_edited_daily_markdown_is_not_overwritten(self):
        result = daily_report(self.config, now=TODAY)
        path = Path(result["report_path"])
        path.write_text("Human notes", encoding="utf-8")
        record = Path(result["record_path"]).read_bytes()
        with self.assertRaises(ActivityError) as context:
            daily_report(self.config, now=TODAY)
        self.assertEqual(context.exception.code, "DAILY_REPORT_EDITED")
        self.assertEqual(path.read_text(encoding="utf-8"), "Human notes")
        self.assertEqual(Path(result["record_path"]).read_bytes(), record)

    def test_markdown_failure_after_json_save_can_be_repaired(self):
        first = daily_report(self.config, now=TODAY)
        with patch("hydro_platform.daily_report.atomic_text", side_effect=OSError("fixture")):
            with self.assertRaises(OSError):
                daily_report(self.config, now=TODAY + timedelta(minutes=1))
        result = daily_report(self.config, now=TODAY + timedelta(minutes=2))
        record = read_record(Path(result["record_path"]))
        self.assertEqual(Path(result["report_path"]).read_text(encoding="utf-8"), record["markdown"])

    def test_failure_in_latest_run_is_visible_even_when_task_says_completed(self):
        self.f.generate(FakeAdapter())
        run = {"group_id": self.config.zotero.group_id, "status": "COMPLETED_WITH_BLOCKERS", "finished_at": TODAY.isoformat(),
            "items": [{"parent_key": PARENT_KEY, "title": "paper", "status": "BLOCKED", "error": {"code": "EVIDENCE_INPUT_MISMATCH"}}]}
        result = daily_report(self.config, run_report=run, now=TODAY)
        record = read_record(Path(result["record_path"]))["report"]
        self.assertEqual(record["open_items"][0]["reason_code"], "EVIDENCE_INPUT_MISMATCH")
        self.assertTrue(record["run_observed_today"])

    def test_missing_runtime_and_empty_day_do_not_claim_pipeline_health(self):
        self.config = replace(self.config, paths=replace(self.config.paths, tasks_file=self.root / "not-existing" / "tasks.json"))
        result = daily_report(self.config, now=TODAY)
        record = read_record(Path(result["record_path"]))["report"]
        self.assertEqual(record["last_run"]["status"], "UNKNOWN")
        self.assertFalse(record["task_registry_exists"])
        self.assertFalse(record["ledger_initialized"])

    def test_markdown_metadata_is_escaped(self):
        self.sync()
        self.add_paper()
        self.source["parents"][PARENT_KEY]["title"] = "<script>evil</script> ![track](https://example.invalid) | table"
        self.sync()
        result = daily_report(self.config, now=TODAY)
        md = Path(result["report_path"]).read_text(encoding="utf-8")
        self.assertNotIn("<script>", md)
        self.assertNotIn("![track]", md)

    def test_cli_routes_both_commands(self):
        for command, target in (("activity-sync", "sync_activity"), ("daily-report", "daily_report")):
            with self.subTest(command=command), patch("hydro_platform.cli." + target, return_value={"ok": True}) as call, redirect_stdout(io.StringIO()) as out:
                code = main([command, "--config", str(self.config_path), "--json"])
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(out.getvalue())["ok"])
            call.assert_called_once()


if __name__ == "__main__":
    unittest.main()
