from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hydrolitagent.cards.config import TaskConfig
from hydrolitagent.cards.evidence_packages import (
    PLACEHOLDER_CARD,
    EvidencePackageError,
    sync_evidence_packages,
)
from hydrolitagent.cards.tasks import build_task_id, save_task_registry

GROUP_ID = 6618088
PARENT_KEY = "PARENT01"
ATTACHMENT_KEY = "PDF00001"
PDF_HASH = "a" * 64
TASK_ID = build_task_id(GROUP_ID, PARENT_KEY, ATTACHMENT_KEY, PDF_HASH)

def ready_task(
    *,
    title: str = "Rainfall: Risk / Response?",
    pdf_hash: str = PDF_HASH,
    task_id: str | None = None,
    state: str = "READY_FOR_EXTRACTION",
) -> dict[str, object]:
    resolved_task_id = task_id or build_task_id(
        GROUP_ID,
        PARENT_KEY,
        ATTACHMENT_KEY,
        pdf_hash,
    )
    return {
        "record_id": f"{GROUP_ID}:{PARENT_KEY}",
        "group_id": GROUP_ID,
        "parent_key": PARENT_KEY,
        "title": title,
        "task_id": resolved_task_id,
        "input": {
            "attachment_key": ATTACHMENT_KEY,
            "pdf_sha256": pdf_hash,
        },
        "state": state,
        "reason_code": "PDF_READY",
        "message": "PDF ready",
        "attempt_count": 0,
        "lease": None,
        "created_at": "2026-09-05T02:00:00Z",
        "updated_at": "2026-09-05T02:00:00Z",
        "history": [],
    }

def write_registry(path: Path, task: dict[str, object]) -> None:
    save_task_registry(
        path,
        {
            "schema_version": 1,
            "group_id": GROUP_ID,
            "created_at": "2026-09-05T02:00:00Z",
            "updated_at": "2026-09-05T02:00:00Z",
            "tasks": {PARENT_KEY: task},
        },
    )

class EvidencePackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task_config = TaskConfig(
            lease_seconds=60,
            lock_stale_seconds=60,
            max_history_entries=20,
        )
        self.now = datetime(2026, 9, 5, 3, 0, tzinfo=timezone.utc)

    def _paths(self, root: Path) -> tuple[Path, Path, Path]:
        runtime = root / ".runtime"
        return runtime / "tasks.json", runtime / "worker.lock", root / "evidence-packs"

    def _sync(self, root: Path, *, now: datetime | None = None) -> dict[str, object]:
        task_path, lock_path, evidence_root = self._paths(root)
        return sync_evidence_packages(
            GROUP_ID,
            self.task_config,
            task_path,
            lock_path,
            evidence_root,
            now=now or self.now,
        )

    def test_creates_manifest_and_minimal_placeholder_card(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _, evidence_root = self._paths(root)
            write_registry(task_path, ready_task())

            result = self._sync(root)

            package_path = evidence_root / "EV-PARENT01-rainfall-risk-response"
            manifest = json.loads((package_path / "manifest.json").read_text(encoding="utf-8"))
            card = (package_path / "card.md").read_text(encoding="utf-8")

        self.assertEqual(result["created_count"], 1)
        self.assertEqual(result["unchanged_count"], 0)
        self.assertEqual(manifest["evidence_id"], "EV-PARENT01")
        self.assertEqual(manifest["group_id"], GROUP_ID)
        self.assertEqual(manifest["attachment_key"], ATTACHMENT_KEY)
        self.assertEqual(manifest["pdf_sha256"], PDF_HASH)
        self.assertEqual(manifest["source_task_id"], TASK_ID)
        self.assertEqual(manifest["card_status"], "PLACEHOLDER")
        self.assertEqual(card, PLACEHOLDER_CARD)
        self.assertFalse((package_path / "topic-readings").exists())

    def test_repeated_sync_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _, evidence_root = self._paths(root)
            write_registry(task_path, ready_task())
            first = self._sync(root)
            package_path = next(path for path in evidence_root.iterdir() if path.is_dir())
            manifest_before = (package_path / "manifest.json").read_bytes()

            second = self._sync(root, now=self.now + timedelta(minutes=1))
            manifest_after = (package_path / "manifest.json").read_bytes()

        self.assertEqual(first["created_count"], 1)
        self.assertEqual(second["created_count"], 0)
        self.assertEqual(second["unchanged_count"], 1)
        self.assertEqual(manifest_after, manifest_before)

    def test_existing_non_placeholder_card_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _, evidence_root = self._paths(root)
            write_registry(task_path, ready_task())
            self._sync(root)
            package_path = next(path for path in evidence_root.iterdir() if path.is_dir())
            card_path = package_path / "card.md"
            card_path.write_text("# 人工填写的证据卡\n", encoding="utf-8")

            result = self._sync(root, now=self.now + timedelta(minutes=1))
            preserved = card_path.read_text(encoding="utf-8")

        self.assertEqual(result["packages"][0]["card_state"], "PRESERVED")
        self.assertEqual(preserved, "# 人工填写的证据卡\n")

    def test_title_change_reuses_package_located_by_parent_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _, evidence_root = self._paths(root)
            write_registry(task_path, ready_task())
            self._sync(root)
            original_path = next(path for path in evidence_root.iterdir() if path.is_dir())
            write_registry(task_path, ready_task(title="Renamed Paper"))

            result = self._sync(root, now=self.now + timedelta(minutes=1))
            directories = [path for path in evidence_root.iterdir() if path.is_dir()]

        self.assertEqual(result["unchanged_count"], 1)
        self.assertEqual(directories, [original_path])

    def test_incomplete_existing_package_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _, evidence_root = self._paths(root)
            write_registry(task_path, ready_task())
            package_path = evidence_root / "EV-PARENT01-partial"
            package_path.mkdir(parents=True)
            (package_path / "card.md").write_text(PLACEHOLDER_CARD, encoding="utf-8")

            with self.assertRaises(EvidencePackageError) as raised:
                self._sync(root)

        self.assertEqual(raised.exception.code, "EVIDENCE_PACKAGE_INCOMPLETE")

    def test_corrupt_manifest_is_not_silently_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _, evidence_root = self._paths(root)
            write_registry(task_path, ready_task())
            self._sync(root)
            package_path = next(path for path in evidence_root.iterdir() if path.is_dir())
            manifest_path = package_path / "manifest.json"
            manifest_path.write_text("{broken", encoding="utf-8")

            with self.assertRaises(EvidencePackageError) as raised:
                self._sync(root, now=self.now + timedelta(minutes=1))
            preserved = manifest_path.read_text(encoding="utf-8")

        self.assertEqual(raised.exception.code, "EVIDENCE_MANIFEST_INVALID")
        self.assertEqual(preserved, "{broken")

    def test_duplicate_package_directories_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _, evidence_root = self._paths(root)
            write_registry(task_path, ready_task())
            self._sync(root)
            (evidence_root / "EV-PARENT01-duplicate").mkdir()

            with self.assertRaises(EvidencePackageError) as raised:
                self._sync(root, now=self.now + timedelta(minutes=1))

        self.assertEqual(raised.exception.code, "EVIDENCE_PACKAGE_DUPLICATE")

    def test_changed_pdf_input_does_not_overwrite_existing_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _, _ = self._paths(root)
            write_registry(task_path, ready_task())
            self._sync(root)
            write_registry(
                task_path,
                ready_task(pdf_hash="c" * 64),
            )

            with self.assertRaises(EvidencePackageError) as raised:
                self._sync(root, now=self.now + timedelta(minutes=1))

        self.assertEqual(raised.exception.code, "EVIDENCE_INPUT_MISMATCH")

    def test_invalid_task_identity_is_rejected_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _, evidence_root = self._paths(root)
            write_registry(task_path, ready_task(task_id="TASK-not-a-valid-hash"))

            with self.assertRaises(EvidencePackageError) as raised:
                self._sync(root)
            evidence_entries = list(evidence_root.iterdir())

        self.assertEqual(raised.exception.code, "EVIDENCE_TASK_INVALID")
        self.assertEqual(evidence_entries, [])

    def test_non_ready_task_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, _, evidence_root = self._paths(root)
            write_registry(task_path, ready_task(state="WAITING_FOR_PDF"))

            result = self._sync(root)
            evidence_entries = list(evidence_root.iterdir())

        self.assertEqual(result["eligible_task_count"], 0)
        self.assertEqual(result["package_count"], 0)
        self.assertEqual(evidence_entries, [])

if __name__ == "__main__":
    unittest.main()
