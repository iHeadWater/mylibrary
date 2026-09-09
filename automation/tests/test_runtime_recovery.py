from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.cli import main
from hydro_platform.config import load_config
from hydro_platform.runtime_recovery import recover_runtime
from hydro_platform.snapshot import load_snapshot, save_snapshot
from hydro_platform.tasks import PipelineRunLock, load_task_registry, save_task_registry
from test_card_generation import GenerationFixture, FakeAdapter, NOW, PARENT_KEY, ATTACHMENT_KEY, PDF_HASH
from test_config import write_config


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.f = GenerationFixture(root)
        self.path = write_config(root)
        self.config = load_config(self.path)
        self.snapshot = {"schema_version": 1, "group_id": self.f.zotero.group_id,
            "captured_at": NOW.isoformat(), "library_version": 10,
            "parents": {PARENT_KEY: {"title": "Test paper"}}, "pdf_attachments": {}}
        self.gate = {"ok": True, "gate_status": "READY", "reason_code": "PDF_READY", "message": "ready",
                     "pdf": {"attachment_key": ATTACHMENT_KEY, "sha256": PDF_HASH}}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.ready = self.stack.enter_context(patch("hydro_platform.runtime_recovery.preflight", return_value={"ok": True}))
        self.fetch = self.stack.enter_context(patch("hydro_platform.runtime_recovery.fetch_snapshot", return_value=self.snapshot))
        self.gates = self.stack.enter_context(patch("hydro_platform.runtime_recovery.evaluate_pdf_gate", side_effect=lambda *args: self.gate))
        self.stack.enter_context(patch("hydro_platform.card_generators.build_card_generator_adapter",
                                      side_effect=AssertionError("Recovery must not construct a model adapter")))

    def fresh(self):
        root = self.f.root / "fresh-runtime"
        self.config = replace(self.config, paths=replace(self.config.paths, runtime_dir=root,
            tasks_file=root / "tasks.json", snapshot_file=root / "snapshot.json", lock_file=root / "worker.lock",
            logs_dir=root / "logs", card_trials_dir=root / "card-trials"))

    def run_recovery(self, **kwargs):
        return recover_runtime(self.config, now=NOW + timedelta(hours=3), **kwargs)

    def protected(self):
        return {str(p): p.read_bytes() for p in self.f.evidence_root.rglob("*") if p.is_file()}

    def test_fresh_runtime_recovers_complete_card_and_is_idempotent(self):
        self.f.generate(FakeAdapter())
        protected = self.protected()
        old_runtime = self.f.task_path.read_bytes()
        self.fresh()
        first = self.run_recovery()
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["counts"], {"COMPLETED": 1})
        self.assertEqual(first["changed_task_count"], 1)
        state = self.config.paths.tasks_file.read_bytes()
        second = self.run_recovery()
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["changed_task_count"], 0)
        self.assertEqual(self.config.paths.tasks_file.read_bytes(), state)
        self.assertEqual(second["model_call_count"], 0)
        self.assertEqual(second["contribution_events_written"], 0)
        self.assertEqual(self.f.task_path.read_bytes(), old_runtime)
        self.assertEqual(protected, self.protected())
        self.assertEqual(load_snapshot(self.config.paths.snapshot_file), self.snapshot)

    def test_dry_run_scans_but_creates_no_directory(self):
        self.fresh()
        result = self.run_recovery(dry_run=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "PREVIEW")
        self.assertFalse(self.config.paths.runtime_dir.exists())
        self.assertNotIn("report_path", result)
        self.fetch.assert_called_once()

    def test_missing_pdf_and_unsynced_file_are_waiting_not_conflicts(self):
        self.fresh()
        for reason, expected in (("PDF_MISSING", "WAITING_FOR_PDF"), ("PDF_FILE_NOT_SYNCED", "WAITING_FOR_FILE_SYNC"),
                                 ("FULLTEXT_NOT_INDEXED", "WAITING_FOR_FULLTEXT")):
            with self.subTest(reason=reason):
                self.gate = {"gate_status": "WAITING", "reason_code": reason, "message": "waiting"}
                result = self.run_recovery()
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["counts"], {expected: 1})

    def test_no_evidence_root_leaves_new_paper_ready_without_creating_package(self):
        self.fresh()
        self.config = replace(self.config, paths=replace(self.config.paths, evidence_packs_dir=self.f.root / "new-packs"))
        result = self.run_recovery()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["counts"], {"READY_FOR_EXTRACTION": 1})
        self.assertFalse(self.config.paths.evidence_packs_dir.exists())

    def test_source_change_conflict_does_not_replace_existing_state(self):
        self.f.generate(FakeAdapter())
        before = self.f.task_path.read_bytes()
        save_snapshot(self.config.paths.snapshot_file, self.snapshot)
        old_snapshot = self.config.paths.snapshot_file.read_bytes()
        self.gate["pdf"]["sha256"] = "b" * 64
        result = self.run_recovery()
        self.assertFalse(result["ok"])
        self.assertEqual(result["items"][0]["error"]["code"], "EVIDENCE_INPUT_MISMATCH")
        self.assertEqual(result["state_files_written"], [])
        self.assertEqual(self.f.task_path.read_bytes(), before)
        self.assertEqual(self.config.paths.snapshot_file.read_bytes(), old_snapshot)

    def test_modified_card_is_preserved_and_not_recovered(self):
        self.f.generate(FakeAdapter())
        card = self.f.package / "card.md"
        card.write_text("My edited card", encoding="utf-8")
        self.fresh()
        result = self.run_recovery()
        self.assertFalse(result["ok"])
        self.assertEqual(result["counts"], {"CONFLICT": 1})
        self.assertFalse(self.config.paths.tasks_file.exists())
        self.assertEqual(card.read_text(encoding="utf-8"), "My edited card")

    def test_duplicate_package_is_not_selected_arbitrarily(self):
        (self.f.evidence_root / f"EV-{PARENT_KEY}-duplicate").mkdir()
        result = self.run_recovery()
        self.assertFalse(result["ok"])
        self.assertEqual(result["items"][0]["error"]["code"], "EVIDENCE_PACKAGE_DUPLICATE")

    def test_valid_lease_blocks_before_snapshot_fetch(self):
        registry = load_task_registry(self.f.task_path, self.f.zotero.group_id)
        registry["tasks"][PARENT_KEY].update(state="PROCESSING", lease={
            "expires_at": (NOW + timedelta(hours=4)).isoformat()})
        save_task_registry(self.f.task_path, registry)
        before = self.f.task_path.read_bytes()
        result = self.run_recovery()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "TASK_NOT_CLAIMABLE")
        self.fetch.assert_not_called()
        self.assertEqual(before, self.f.task_path.read_bytes())

    def test_pipeline_and_theme_locks_are_respected(self):
        for suffix in (".pipeline", ".themes"):
            with self.subTest(suffix=suffix), PipelineRunLock(self.f.lock_path.with_name(self.f.lock_path.name + suffix)):
                result = self.run_recovery()
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "TASK_STORE_BUSY")
        self.fetch.assert_not_called()

    def test_invalid_tasks_are_not_replaced(self):
        self.f.task_path.write_text("broken", encoding="utf-8")
        result = self.run_recovery()
        self.assertEqual(result["error"]["code"], "TASK_STORE_INVALID")
        self.assertEqual(self.f.task_path.read_text(encoding="utf-8"), "broken")
        self.fetch.assert_not_called()

    def test_snapshot_from_another_group_is_not_replaced(self):
        save_snapshot(self.config.paths.snapshot_file, {**self.snapshot, "group_id": 999})
        result = self.run_recovery()
        self.assertEqual(result["error"]["code"], "SNAPSHOT_GROUP_MISMATCH")
        self.assertEqual(load_snapshot(self.config.paths.snapshot_file)["group_id"], 999)

    def test_zotero_unavailable_does_not_rewrite_tasks(self):
        before = self.f.task_path.read_bytes()
        self.ready.return_value = {"ok": False, "error": {"code": "UNAVAILABLE", "message": "Unavailable"}}
        result = self.run_recovery()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "UNAVAILABLE")
        self.assertEqual(before, self.f.task_path.read_bytes())

    def test_partial_state_save_failure_reports_what_was_written(self):
        self.fresh()
        with patch("hydro_platform.runtime_recovery.save_snapshot", side_effect=OSError("fixture")):
            result = self.run_recovery()
        self.assertFalse(result["ok"])
        self.assertEqual(result["state_files_written"], [str(self.config.paths.tasks_file)])
        again = self.run_recovery()
        self.assertTrue(again["ok"], again)

    def test_cli_routes_recovery_without_generator(self):
        with patch("hydro_platform.cli.recover_runtime", return_value={"ok": True}) as recover, redirect_stdout(io.StringIO()) as out:
            code = main(["recover", "--config", str(self.path), "--dry-run", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["ok"])
        self.assertTrue(recover.call_args.kwargs["dry_run"])


if __name__ == "__main__":
    unittest.main()
