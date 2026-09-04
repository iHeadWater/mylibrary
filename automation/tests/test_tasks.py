from __future__ import annotations

import os
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from hydro_platform.config import PdfGateConfig, TaskConfig, ZoteroConfig
from hydro_platform.tasks import (
    RuntimeLock,
    TaskStoreError,
    claim_task,
    finish_task,
    load_task_registry,
    reconcile_tasks,
    save_task_registry,
    sync_tasks,
)
from hydro_platform.zotero import ApiResponse


GROUP_ID = 6618088
PARENT_KEY = "PARENT01"
ATTACHMENT_KEY = "PDF00001"


def snapshot() -> dict[str, object]:
    return {
        "schema_version": 1,
        "group_id": GROUP_ID,
        "parents": {
            PARENT_KEY: {
                "title": "Research Paper",
                "version": 1,
            }
        },
        "pdf_attachments": {},
    }


def ready_gate(pdf_hash: str = "a" * 64) -> dict[str, object]:
    return {
        "ok": True,
        "gate_status": "READY",
        "reason_code": "PDF_READY",
        "message": "PDF ready",
        "pdf": {
            "attachment_key": ATTACHMENT_KEY,
            "sha256": pdf_hash,
        },
    }


class SyncClient:
    def __init__(self, pdf_path: Path):
        self.pdf_path = pdf_path

    def get_json(self, path: str) -> ApiResponse:
        if "/items?" in path:
            records = [
                {
                    "key": PARENT_KEY,
                    "version": 1,
                    "data": {
                        "key": PARENT_KEY,
                        "version": 1,
                        "itemType": "journalArticle",
                        "title": "Research Paper",
                    },
                },
                {
                    "key": ATTACHMENT_KEY,
                    "version": 1,
                    "data": {
                        "key": ATTACHMENT_KEY,
                        "version": 1,
                        "itemType": "attachment",
                        "parentItem": PARENT_KEY,
                        "filename": "paper.pdf",
                        "contentType": "application/pdf",
                        "linkMode": "imported_file",
                    },
                },
            ]
            return ApiResponse(
                data=records,
                headers={"Total-Results": "2", "Last-Modified-Version": "1"},
            )
        if path.endswith("/children"):
            return ApiResponse(
                data=[
                    {
                        "key": ATTACHMENT_KEY,
                        "data": {
                            "key": ATTACHMENT_KEY,
                            "itemType": "attachment",
                            "parentItem": PARENT_KEY,
                            "filename": "paper.pdf",
                            "contentType": "application/pdf",
                            "linkMode": "imported_file",
                        },
                    }
                ],
                headers={},
            )
        if path.endswith("/fulltext"):
            return ApiResponse(data={"content": "research text " * 20}, headers={})
        raise AssertionError(f"unexpected JSON path: {path}")

    def get_text(self, path: str) -> ApiResponse:
        if not path.endswith("/file/view/url"):
            raise AssertionError(f"unexpected text path: {path}")
        return ApiResponse(data=self.pdf_path.as_uri(), headers={})


class TaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = TaskConfig(
            lease_seconds=60,
            lock_stale_seconds=60,
            max_history_entries=20,
        )
        self.now = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)

    def _registry(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "group_id": GROUP_ID,
            "created_at": "2026-09-04T14:00:00Z",
            "updated_at": "2026-09-04T14:00:00Z",
            "tasks": {},
        }

    def test_reconcile_creates_one_unique_ready_task(self) -> None:
        registry = self._registry()

        changed = reconcile_tasks(
            registry,
            snapshot(),
            {PARENT_KEY: ready_gate()},
            self.config,
            now=self.now,
        )

        task = registry["tasks"][PARENT_KEY]
        self.assertEqual(changed, 1)
        self.assertEqual(task["state"], "READY_FOR_EXTRACTION")
        self.assertTrue(task["task_id"].startswith("TASK-"))
        self.assertEqual(len(task["history"]), 1)

    def test_repeated_reconcile_does_not_duplicate_state_history(self) -> None:
        registry = self._registry()
        reconcile_tasks(
            registry,
            snapshot(),
            {PARENT_KEY: ready_gate()},
            self.config,
            now=self.now,
        )

        changed = reconcile_tasks(
            registry,
            snapshot(),
            {PARENT_KEY: ready_gate()},
            self.config,
            now=self.now + timedelta(minutes=1),
        )

        self.assertEqual(changed, 0)
        self.assertEqual(len(registry["tasks"][PARENT_KEY]["history"]), 1)

    def test_second_claim_is_refused_while_first_lease_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task_path = Path(directory) / "tasks.json"
            lock_path = Path(directory) / "worker.lock"
            registry = self._registry()
            reconcile_tasks(
                registry,
                snapshot(),
                {PARENT_KEY: ready_gate()},
                self.config,
                now=self.now,
            )
            save_task_registry(task_path, registry)
            claim_task(
                GROUP_ID,
                PARENT_KEY,
                self.config,
                task_path,
                lock_path,
                now=self.now,
                token_factory=lambda: "first-token",
            )

            with self.assertRaises(TaskStoreError) as raised:
                claim_task(
                    GROUP_ID,
                    PARENT_KEY,
                    self.config,
                    task_path,
                    lock_path,
                    now=self.now + timedelta(seconds=30),
                )

        self.assertEqual(raised.exception.code, "TASK_NOT_CLAIMABLE")

    def test_expired_processing_lease_can_be_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task_path = Path(directory) / "tasks.json"
            lock_path = Path(directory) / "worker.lock"
            registry = self._registry()
            reconcile_tasks(
                registry,
                snapshot(),
                {PARENT_KEY: ready_gate()},
                self.config,
                now=self.now,
            )
            save_task_registry(task_path, registry)
            claim_task(
                GROUP_ID,
                PARENT_KEY,
                self.config,
                task_path,
                lock_path,
                now=self.now,
                token_factory=lambda: "first-token",
            )

            claimed = claim_task(
                GROUP_ID,
                PARENT_KEY,
                self.config,
                task_path,
                lock_path,
                now=self.now + timedelta(seconds=61),
                token_factory=lambda: "second-token",
            )

        self.assertEqual(claimed["lease_token"], "second-token")
        self.assertEqual(claimed["task"]["attempt_count"], 2)
        self.assertEqual(claimed["task"]["state"], "PROCESSING")

    def test_completed_unchanged_input_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task_path = Path(directory) / "tasks.json"
            lock_path = Path(directory) / "worker.lock"
            registry = self._registry()
            reconcile_tasks(
                registry,
                snapshot(),
                {PARENT_KEY: ready_gate()},
                self.config,
                now=self.now,
            )
            save_task_registry(task_path, registry)
            claim_task(
                GROUP_ID,
                PARENT_KEY,
                self.config,
                task_path,
                lock_path,
                now=self.now,
                token_factory=lambda: "lease-token",
            )
            finish_task(
                GROUP_ID,
                PARENT_KEY,
                "lease-token",
                self.config,
                task_path,
                lock_path,
                completed=True,
                reason_code="PROCESSING_COMPLETED",
                message="processing complete",
                now=self.now + timedelta(seconds=10),
            )
            completed_registry = load_task_registry(task_path, GROUP_ID)

            changed = reconcile_tasks(
                completed_registry,
                snapshot(),
                {PARENT_KEY: ready_gate()},
                self.config,
                now=self.now + timedelta(minutes=2),
            )

        self.assertEqual(changed, 0)
        self.assertEqual(completed_registry["tasks"][PARENT_KEY]["state"], "COMPLETED")

    def test_changed_pdf_hash_resets_completed_task_to_ready(self) -> None:
        registry = self._registry()
        reconcile_tasks(
            registry,
            snapshot(),
            {PARENT_KEY: ready_gate("a" * 64)},
            self.config,
            now=self.now,
        )
        task = registry["tasks"][PARENT_KEY]
        old_task_id = task["task_id"]
        task["state"] = "COMPLETED"
        task["attempt_count"] = 3

        changed = reconcile_tasks(
            registry,
            snapshot(),
            {PARENT_KEY: ready_gate("b" * 64)},
            self.config,
            now=self.now + timedelta(minutes=1),
        )

        self.assertEqual(changed, 1)
        self.assertNotEqual(task["task_id"], old_task_id)
        self.assertEqual(task["state"], "READY_FOR_EXTRACTION")
        self.assertEqual(task["attempt_count"], 0)

    def test_changed_pdf_hash_is_saved_even_when_state_stays_ready(self) -> None:
        registry = self._registry()
        reconcile_tasks(
            registry,
            snapshot(),
            {PARENT_KEY: ready_gate("a" * 64)},
            self.config,
            now=self.now,
        )
        task = registry["tasks"][PARENT_KEY]
        old_task_id = task["task_id"]

        changed = reconcile_tasks(
            registry,
            snapshot(),
            {PARENT_KEY: ready_gate("b" * 64)},
            self.config,
            now=self.now + timedelta(minutes=1),
        )

        self.assertEqual(changed, 1)
        self.assertNotEqual(task["task_id"], old_task_id)
        self.assertEqual(task["input"]["pdf_sha256"], "b" * 64)
        self.assertEqual(task["history"][-1]["reason_code"], "INPUT_CHANGED")

    def test_runtime_lock_rejects_concurrent_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "worker.lock"
            with RuntimeLock(lock_path, stale_seconds=60):
                with self.assertRaises(TaskStoreError) as raised:
                    with RuntimeLock(lock_path, stale_seconds=60):
                        pass

        self.assertEqual(raised.exception.code, "TASK_STORE_BUSY")

    def test_runtime_lock_recovers_dead_stale_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "worker.lock"
            lock_path.write_text(
                json.dumps({"schema_version": 1, "pid": 99999999, "token": "dead"}),
                encoding="utf-8",
            )
            old_time = datetime.now().timestamp() - 120
            os.utime(lock_path, (old_time, old_time))

            with RuntimeLock(lock_path, stale_seconds=60):
                self.assertTrue(lock_path.exists())

        self.assertFalse(lock_path.exists())

    def test_corrupt_task_store_is_not_silently_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task_path = Path(directory) / "tasks.json"
            task_path.write_text("{broken", encoding="utf-8")

            with self.assertRaises(TaskStoreError) as raised:
                load_task_registry(task_path, GROUP_ID)

            self.assertEqual(raised.exception.code, "TASK_STORE_INVALID")
            self.assertEqual(task_path.read_text(encoding="utf-8"), "{broken")

    def test_sync_tasks_writes_registry_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.7\n" + b"body" * 32 + b"\n%%EOF\n")
            task_path = root / "tasks.json"
            lock_path = root / "worker.lock"
            client = SyncClient(pdf_path)
            zotero = ZoteroConfig(group_id=GROUP_ID)
            gate = PdfGateConfig(
                min_file_size_bytes=64,
                min_text_characters=20,
                hash_chunk_size_bytes=32,
            )

            first = sync_tasks(
                zotero,
                gate,
                self.config,
                task_path,
                lock_path,
                page_size=100,
                client=client,
                now=self.now,
            )
            second = sync_tasks(
                zotero,
                gate,
                self.config,
                task_path,
                lock_path,
                page_size=100,
                client=client,
                now=self.now + timedelta(minutes=1),
            )

        self.assertEqual(first["task_count"], 1)
        self.assertEqual(first["changed_count"], 1)
        self.assertEqual(first["state_counts"], {"READY_FOR_EXTRACTION": 1})
        self.assertEqual(second["changed_count"], 0)


if __name__ == "__main__":
    unittest.main()
