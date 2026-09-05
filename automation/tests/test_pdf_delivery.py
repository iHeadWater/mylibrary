from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from hydro_platform.config import PdfGateConfig, TaskConfig, ZoteroConfig
from hydro_platform.evidence_packages import sync_evidence_packages
from hydro_platform.pdf_delivery import PdfDeliveryError, prepare_pdf_delivery
from hydro_platform.tasks import build_task_id, save_task_registry
from hydro_platform.zotero import ApiResponse, ZoteroApiError


GROUP_ID = 6618088
PARENT_KEY = "PARENT01"
ATTACHMENT_KEY = "PDF00001"


def attachment(key: str, parent_key: str) -> dict[str, object]:
    return {
        "key": key,
        "data": {
            "key": key,
            "itemType": "attachment",
            "parentItem": parent_key,
            "filename": "paper.pdf",
            "contentType": "application/pdf",
            "linkMode": "imported_file",
        },
    }


class FakeClient:
    def __init__(self, *, attachment_key: str, file_url: str | None):
        self.attachment_key = attachment_key
        self.file_url = file_url

    def get_json(self, path: str) -> ApiResponse:
        if path.endswith("/children"):
            return ApiResponse(
                data=[attachment(self.attachment_key, PARENT_KEY)],
                headers={},
            )
        if path.endswith("/fulltext"):
            return ApiResponse(
                data={"content": "Cross-page research evidence " * 10},
                headers={},
            )
        raise AssertionError(f"unexpected JSON path: {path}")

    def get_text(self, path: str) -> ApiResponse:
        if not path.endswith("/file/view/url"):
            raise AssertionError(f"unexpected text path: {path}")
        if self.file_url is None:
            raise ZoteroApiError("GROUP_NOT_AVAILABLE", "not found", 404)
        return ApiResponse(data=self.file_url, headers={})


class PdfDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.zotero = ZoteroConfig(group_id=GROUP_ID)
        self.gate = PdfGateConfig(
            min_file_size_bytes=64,
            min_text_characters=20,
            hash_chunk_size_bytes=32,
        )
        self.tasks = TaskConfig(
            lease_seconds=60,
            lock_stale_seconds=60,
            max_history_entries=20,
        )
        self.now = datetime(2026, 9, 5, 4, 0, tzinfo=timezone.utc)

    @staticmethod
    def _write_pdf(root: Path) -> Path:
        storage = root / "zotero-storage"
        storage.mkdir()
        path = storage / "paper.pdf"
        path.write_bytes(b"%PDF-1.7\n" + b"research body" * 20 + b"\n%%EOF\n")
        return path

    @staticmethod
    def _paths(root: Path) -> tuple[Path, Path, Path]:
        runtime = root / ".runtime"
        return runtime / "tasks.json", runtime / "worker.lock", root / "evidence-packs"

    def _write_task(
        self,
        root: Path,
        *,
        attachment_key: str = ATTACHMENT_KEY,
        pdf_hash: str,
        state: str = "READY_FOR_EXTRACTION",
    ) -> tuple[Path, Path, Path]:
        task_path, lock_path, evidence_root = self._paths(root)
        task_id = build_task_id(GROUP_ID, PARENT_KEY, attachment_key, pdf_hash)
        save_task_registry(
            task_path,
            {
                "schema_version": 1,
                "group_id": GROUP_ID,
                "created_at": "2026-09-05T04:00:00Z",
                "updated_at": "2026-09-05T04:00:00Z",
                "tasks": {
                    PARENT_KEY: {
                        "record_id": f"{GROUP_ID}:{PARENT_KEY}",
                        "group_id": GROUP_ID,
                        "parent_key": PARENT_KEY,
                        "title": "Test paper",
                        "task_id": task_id,
                        "input": {
                            "attachment_key": attachment_key,
                            "pdf_sha256": pdf_hash,
                        },
                        "state": state,
                        "reason_code": "PDF_READY",
                        "message": "PDF ready",
                        "attempt_count": 0,
                        "lease": None,
                        "created_at": "2026-09-05T04:00:00Z",
                        "updated_at": "2026-09-05T04:00:00Z",
                        "history": [],
                    }
                },
            },
        )
        return task_path, lock_path, evidence_root

    def _create_package(self, root: Path) -> None:
        task_path, lock_path, evidence_root = self._paths(root)
        sync_evidence_packages(
            GROUP_ID,
            self.tasks,
            task_path,
            lock_path,
            evidence_root,
            now=self.now,
        )

    def test_returns_verified_original_pdf_without_copying_or_mutating_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = self._write_pdf(root)
            pdf_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            pdf_size = pdf_path.stat().st_size
            task_path, lock_path, evidence_root = self._write_task(
                root,
                pdf_hash=pdf_hash,
            )
            self._create_package(root)
            task_before = task_path.read_bytes()

            delivery = prepare_pdf_delivery(
                self.zotero,
                self.gate,
                self.tasks,
                task_path,
                lock_path,
                evidence_root,
                PARENT_KEY,
                client=FakeClient(
                    attachment_key=ATTACHMENT_KEY,
                    file_url=pdf_path.as_uri(),
                ),
                now=self.now,
            )

            task_after = task_path.read_bytes()
            copied_pdfs = list(evidence_root.rglob("*.pdf")) + list(
                (root / ".runtime").rglob("*.pdf")
            )

        self.assertEqual(delivery.pdf_path, pdf_path.resolve())
        self.assertEqual(delivery.pdf_sha256, pdf_hash)
        self.assertEqual(delivery.attachment_key, ATTACHMENT_KEY)
        self.assertEqual(delivery.file_size_bytes, pdf_size)
        self.assertEqual(delivery.as_result()["delivery_mode"], "LOCAL_FILE_PATH")
        self.assertEqual(task_after, task_before)
        self.assertEqual(copied_pdfs, [])

    def test_rejects_pdf_whose_hash_changed_after_task_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = self._write_pdf(root)
            task_path, lock_path, evidence_root = self._write_task(
                root,
                pdf_hash="0" * 64,
            )
            self._create_package(root)

            with self.assertRaises(PdfDeliveryError) as raised:
                prepare_pdf_delivery(
                    self.zotero,
                    self.gate,
                    self.tasks,
                    task_path,
                    lock_path,
                    evidence_root,
                    PARENT_KEY,
                    client=FakeClient(
                        attachment_key=ATTACHMENT_KEY,
                        file_url=pdf_path.as_uri(),
                    ),
                )

        self.assertEqual(raised.exception.code, "PDF_INPUT_CHANGED")

    def test_rejects_attachment_changed_after_task_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = self._write_pdf(root)
            pdf_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            task_path, lock_path, evidence_root = self._write_task(
                root,
                attachment_key="PDF00002",
                pdf_hash=pdf_hash,
            )
            self._create_package(root)

            with self.assertRaises(PdfDeliveryError) as raised:
                prepare_pdf_delivery(
                    self.zotero,
                    self.gate,
                    self.tasks,
                    task_path,
                    lock_path,
                    evidence_root,
                    PARENT_KEY,
                    client=FakeClient(
                        attachment_key=ATTACHMENT_KEY,
                        file_url=pdf_path.as_uri(),
                    ),
                )

        self.assertEqual(raised.exception.code, "PDF_ATTACHMENT_CHANGED")

    def test_reports_zotero_file_not_synced_without_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, lock_path, evidence_root = self._write_task(
                root,
                pdf_hash="0" * 64,
            )
            self._create_package(root)

            with self.assertRaises(PdfDeliveryError) as raised:
                prepare_pdf_delivery(
                    self.zotero,
                    self.gate,
                    self.tasks,
                    task_path,
                    lock_path,
                    evidence_root,
                    PARENT_KEY,
                    client=FakeClient(
                        attachment_key=ATTACHMENT_KEY,
                        file_url=None,
                    ),
                )

        self.assertEqual(raised.exception.code, "PDF_FILE_NOT_SYNCED")

    def test_requires_existing_evidence_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, lock_path, evidence_root = self._write_task(
                root,
                pdf_hash="0" * 64,
            )
            evidence_root.mkdir()

            with self.assertRaises(PdfDeliveryError) as raised:
                prepare_pdf_delivery(
                    self.zotero,
                    self.gate,
                    self.tasks,
                    task_path,
                    lock_path,
                    evidence_root,
                    PARENT_KEY,
                    client=FakeClient(
                        attachment_key=ATTACHMENT_KEY,
                        file_url=None,
                    ),
                )

        self.assertEqual(raised.exception.code, "PDF_DELIVERY_PACKAGE_MISSING")

    def test_rejects_task_that_is_not_ready_for_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_path, lock_path, evidence_root = self._write_task(
                root,
                pdf_hash="0" * 64,
                state="WAITING_FOR_PDF",
            )

            with self.assertRaises(PdfDeliveryError) as raised:
                prepare_pdf_delivery(
                    self.zotero,
                    self.gate,
                    self.tasks,
                    task_path,
                    lock_path,
                    evidence_root,
                    PARENT_KEY,
                    client=FakeClient(
                        attachment_key=ATTACHMENT_KEY,
                        file_url=None,
                    ),
                )

        self.assertEqual(raised.exception.code, "PDF_DELIVERY_TASK_NOT_READY")


if __name__ == "__main__":
    unittest.main()
