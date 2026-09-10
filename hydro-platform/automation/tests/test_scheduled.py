from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.config import load_config
from hydro_platform.scheduled import scheduled_tick, state_path, read_state, due_status
from hydro_platform.tasks import PipelineRunLock
from test_config import write_config

NOW = datetime(2026, 9, 9, 9, tzinfo=timezone(timedelta(hours=8)))


class ScheduledTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = load_config(write_config(self.root))
        self.config = replace(config, scheduler=replace(config.scheduler, enabled=True))
        self.pipeline = Mock(return_value={"ok": True, "status": "COMPLETED", "generation_attempt_count": 0,
                                          "theme_pipeline": {"model_call_count": 0}, "report_path": "saved.json"})

    def tick(self, now=NOW):
        return scheduled_tick(self.config, now=now, pipeline=self.pipeline)

    def change_state(self, **values):
        data = json.loads(state_path(self.config).read_text())
        data.update(values)
        state_path(self.config).write_text(json.dumps(data))

    def test_disabled_is_no_write_no_pipeline(self):
        self.config = replace(self.config, scheduler=replace(self.config.scheduler, enabled=False))
        result = self.tick()
        self.assertEqual(result["status"], "DISABLED")
        self.pipeline.assert_not_called()
        self.assertFalse(self.config.paths.runtime_dir.exists())

    def test_first_due_then_many_polls_run_once(self):
        self.assertTrue(self.tick()["ok"])
        for minutes in (1, 30, 60, 700):
            self.assertEqual(self.tick(NOW + timedelta(minutes=minutes))["status"], "ALREADY_COMPLETED")
        self.pipeline.assert_called_once()
        self.assertEqual(read_state(self.config)["attempt_count"], 1)

    def test_next_day_runs_new_slot(self):
        self.tick()
        result = self.tick(NOW + timedelta(days=1))
        self.assertTrue(result["ok"])
        self.assertEqual(result["slot_date"], "2026-09-10")
        self.assertEqual(self.pipeline.call_count, 2)

    def test_pending_pdf_is_not_marked_complete_and_rechecks_after_cooldown(self):
        self.pipeline.return_value = {"ok": True, "status": "COMPLETED_WITH_PENDING", "pending_count": 1,
                                      "counts": {"waiting": 1}, "generation_attempt_count": 0}
        first = self.tick()
        self.assertEqual(first["status"], "PENDING")
        self.assertEqual(read_state(self.config)["pending_count"], 1)
        self.assertEqual(self.tick(NOW + timedelta(minutes=30))["status"], "RETRY_COOLDOWN")
        self.pipeline.return_value = {"ok": True, "status": "COMPLETED"}
        self.assertEqual(self.tick(NOW + timedelta(hours=1))["status"], "COMPLETED")
        self.assertEqual(self.tick(NOW + timedelta(hours=2))["status"], "ALREADY_COMPLETED")
        self.assertEqual(self.pipeline.call_count, 2)

    def test_pending_queue_has_finite_daily_attempts_not_infinite_model_retries(self):
        self.pipeline.return_value = {"ok": True, "status": "COMPLETED_WITH_PENDING", "counts": {"deferred": 1}}
        for hour in range(3):
            self.assertEqual(self.tick(NOW + timedelta(hours=hour))["status"], "PENDING")
        self.assertEqual(self.tick(NOW + timedelta(hours=3))["status"], "ATTEMPTS_EXHAUSTED")
        self.assertEqual(self.pipeline.call_count, 3)

    def test_legacy_completed_report_with_waiting_items_does_not_hide_them(self):
        self.pipeline.return_value = {"ok": True, "status": "COMPLETED", "counts": {"waiting": 1}}
        result = self.tick()
        self.assertEqual(result["status"], "PENDING")
        self.assertEqual(result["pending_count"], 1)

    def test_failure_with_pending_items_remains_failure(self):
        self.pipeline.return_value = {"ok": False, "status": "COMPLETED_WITH_BLOCKERS", "counts": {"waiting": 1}}
        self.assertEqual(self.tick()["status"], "FAILED")

    def test_before_daily_time_catches_only_latest_previous_day(self):
        result = self.tick(NOW - timedelta(hours=1))
        self.assertEqual(result["slot_date"], "2026-09-08")
        self.assertEqual(self.tick(NOW)["slot_date"], "2026-09-09")

    def test_days_off_do_not_replay_every_missing_day(self):
        self.tick()
        result = self.tick(NOW + timedelta(days=10))
        self.assertTrue(result["ok"])
        self.assertEqual(self.pipeline.call_count, 2)

    def test_failures_have_cooldown_and_daily_limit(self):
        self.pipeline.return_value = {"ok": False, "status": "FAILED", "error": {"code": "ZOTERO_DOWN"}}
        self.assertFalse(self.tick()["ok"])
        self.assertEqual(self.tick(NOW + timedelta(minutes=30))["status"], "RETRY_COOLDOWN")
        self.tick(NOW + timedelta(hours=1))
        self.tick(NOW + timedelta(hours=2))
        self.assertEqual(self.tick(NOW + timedelta(hours=3))["status"], "ATTEMPTS_EXHAUSTED")
        self.assertEqual(self.pipeline.call_count, 3)
        self.assertEqual(self.tick(NOW + timedelta(days=1))["attempt_count"], 1)

    def test_exception_is_recorded_without_raw_output(self):
        self.pipeline.side_effect = RuntimeError("secret-like output")
        result = self.tick()
        self.assertFalse(result["ok"])
        self.assertNotIn("secret-like", json.dumps(result))
        self.assertEqual(read_state(self.config)["status"], "FAILED")

    def test_crashed_reservation_is_not_forgotten(self):
        self.tick()
        self.change_state(status="RUNNING", next_retry_at=NOW.isoformat())
        self.assertEqual(self.tick(NOW + timedelta(hours=1))["attempt_count"], 2)

    def test_manual_pipeline_busy_does_not_consume_attempt(self):
        self.pipeline.return_value = {"ok": True, "status": "ALREADY_RUNNING"}
        result = self.tick()
        self.assertEqual(result["status"], "BUSY")
        self.assertEqual(read_state(self.config)["attempt_count"], 0)

    def test_live_scheduler_lock_prevents_parallel_processing(self):
        with PipelineRunLock(self.config.paths.runtime_dir / "scheduler.lock"):
            result = self.tick()
        self.assertEqual(result["status"], "ALREADY_RUNNING")
        self.pipeline.assert_not_called()

    def test_corrupt_state_is_preserved_not_reset(self):
        self.config.paths.runtime_dir.mkdir(parents=True)
        path = state_path(self.config)
        path.write_text("bad JSON")
        self.assertEqual(self.tick()["error"]["code"], "SCHEDULE_STATE_ERROR")
        self.assertEqual(path.read_text(), "bad JSON")
        self.pipeline.assert_not_called()

    def test_other_group_is_not_overwritten(self):
        self.tick()
        self.change_state(group_id=999999)
        before = state_path(self.config).read_bytes()
        self.assertFalse(self.tick()["ok"])
        self.assertEqual(before, state_path(self.config).read_bytes())

    def test_clock_backward_never_replays_future_slot(self):
        self.tick()
        self.assertEqual(self.tick(NOW - timedelta(days=1))["status"], "CLOCK_REVERSED")
        self.pipeline.assert_called_once()

    def test_local_timezone_boundary_not_utc_date(self):
        early = NOW.replace(hour=0, minute=30)
        self.config = replace(self.config, scheduler=replace(self.config.scheduler, daily_time="00:15"))
        self.assertEqual(self.tick(early)["slot_date"], "2026-09-09")

    def test_nonempty_outputs_do_not_trigger_quality_checks(self):
        self.pipeline.return_value = {"ok": True, "status": "COMPLETED", "generation_attempt_count": 1,
                                      "theme_pipeline": None}
        result = self.tick()
        self.assertTrue(result["ok"])
        self.assertIsNone(result["model_call_count"])
        self.assertEqual(result["generation_attempt_count"], 1)

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            due_status(self.config, None, NOW.replace(tzinfo=None))


if __name__ == "__main__":
    unittest.main()
