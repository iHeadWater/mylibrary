from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from hydro_platform.config import ZoteroConfig
from hydro_platform.snapshot import SnapshotError, compare_snapshots, fetch_snapshot, scan_group
from hydro_platform.zotero import ApiResponse


def item(
    key: str,
    item_type: str,
    *,
    version: int = 1,
    parent_key: str | None = None,
    title: str | None = None,
    filename: str | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {
        "key": key,
        "version": version,
        "itemType": item_type,
        "title": title,
    }
    if parent_key is not None:
        data["parentItem"] = parent_key
    if filename is not None:
        data["filename"] = filename
        data["contentType"] = "application/pdf"
        data["linkMode"] = "imported_file"
    return {"key": key, "version": version, "data": data}


class FakeClient:
    def __init__(self, records: list[dict[str, object]], library_version: int = 1):
        self.records = records
        self.library_version = library_version

    def get_json(self, path: str) -> ApiResponse:
        if "start=0" not in path:
            raise AssertionError(f"unexpected path: {path}")
        return ApiResponse(
            data=self.records,
            headers={
                "Total-Results": str(len(self.records)),
                "Last-Modified-Version": str(self.library_version),
            },
        )


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ZoteroConfig(group_id=6618088)

    def test_contributor_is_only_read_from_group_creation_metadata(self):
        paper = item("PARENT01", "journalArticle", title="Paper")
        paper["meta"] = {"createdByUser": {"id": 101, "username": "student", "links": {"private": "not copied"}},
                         "lastModifiedByUser": {"id": 102}, "creatorSummary": "Author"}
        result = fetch_snapshot(self.config, page_size=100, client=FakeClient([paper]))
        self.assertEqual(result["parents"]["PARENT01"]["created_by_user"], {"id": 101, "username": "student"})
        paper["meta"].pop("createdByUser")
        unknown = fetch_snapshot(self.config, page_size=100, client=FakeClient([paper]))
        self.assertIsNone(unknown["parents"]["PARENT01"]["created_by_user"])

    def test_adding_actor_metadata_is_not_a_pdf_replacement(self):
        old = {"parents": {}, "pdf_attachments": {"PDF00001": {"parent_key": "PARENT01", "version": 1}}}
        new = {"parents": {}, "pdf_attachments": {"PDF00001": {"parent_key": "PARENT01", "version": 1,
                "created_by_user": {"id": 101}, "date_added": "2026-09-09T00:00:00Z"}}}
        self.assertEqual(compare_snapshots(old, new), [])

    def test_missing_total_header_still_reads_later_pages(self):
        class Pages:
            def get_json(self, path):
                rows = [item("PARENT01", "journalArticle")] if "start=0" in path else []
                return ApiResponse(data=rows, headers={})
        result = fetch_snapshot(self.config, page_size=1, client=Pages())
        self.assertEqual(result["counts"]["parents"], 1)

    def test_version_change_between_pages_does_not_create_a_false_baseline(self):
        class Pages:
            def get_json(self, path):
                first = "start=0" in path
                return ApiResponse(data=[item("PARENT01" if first else "PARENT02", "journalArticle")],
                                   headers={"Total-Results": "2", "Last-Modified-Version": "1" if first else "2"})
        with self.assertRaises(SnapshotError) as context:
            fetch_snapshot(self.config, page_size=1, client=Pages())
        self.assertEqual(context.exception.code, "SNAPSHOT_CHANGED_DURING_READ")

    def test_premature_end_or_duplicate_page_fails_closed(self):
        for duplicate in (False, True):
            class Pages:
                def get_json(self, path):
                    rows = [item("PARENT01", "journalArticle")] if "start=0" in path or duplicate else []
                    return ApiResponse(data=rows, headers={"Total-Results": "2"})
            with self.subTest(duplicate=duplicate), self.assertRaises(SnapshotError) as context:
                fetch_snapshot(self.config, page_size=1, client=Pages())
            self.assertEqual(context.exception.code, "SNAPSHOT_INCOMPLETE")

    def test_first_scan_creates_baseline_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "snapshot.json"
            result = scan_group(self.config, state, page_size=100, client=FakeClient([]))

            self.assertEqual(result["mode"], "baseline")
            self.assertEqual(result["change_count"], 0)
            self.assertTrue(state.is_file())

    def test_second_identical_scan_has_no_changes(self) -> None:
        records = [
            item("PARENT01", "journalArticle", title="Paper"),
            item("PDF00001", "attachment", parent_key="PARENT01", filename="paper.pdf"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "snapshot.json"
            scan_group(self.config, state, page_size=100, client=FakeClient(records))
            result = scan_group(self.config, state, page_size=100, client=FakeClient(records))

            self.assertEqual(result["mode"], "incremental")
            self.assertEqual(result["changes"], [])

    def test_detects_new_parent_and_pdf(self) -> None:
        records = [
            item("PARENT01", "journalArticle", title="Paper"),
            item("PDF00001", "attachment", parent_key="PARENT01", filename="paper.pdf"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "snapshot.json"
            scan_group(self.config, state, page_size=100, client=FakeClient([]))
            result = scan_group(
                self.config,
                state,
                page_size=100,
                client=FakeClient(records, library_version=2),
            )

            self.assertEqual(
                [change["type"] for change in result["changes"]],
                ["ITEM_ADDED", "PDF_ADDED"],
            )

    def test_detects_pdf_added_to_existing_parent(self) -> None:
        parent = item("PARENT01", "journalArticle", title="Paper")
        pdf = item("PDF00001", "attachment", parent_key="PARENT01", filename="paper.pdf")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "snapshot.json"
            scan_group(self.config, state, page_size=100, client=FakeClient([parent]))
            result = scan_group(
                self.config,
                state,
                page_size=100,
                client=FakeClient([parent, pdf], 2),
            )

            self.assertEqual(result["change_count"], 1)
            self.assertEqual(result["changes"][0]["type"], "PDF_ADDED")

    def test_detects_replaced_pdf_attachment(self) -> None:
        parent = item("PARENT01", "journalArticle", title="Paper")
        old_pdf = item(
            "PDF00001",
            "attachment",
            version=1,
            parent_key="PARENT01",
            filename="paper.pdf",
        )
        new_pdf = item(
            "PDF00001",
            "attachment",
            version=2,
            parent_key="PARENT01",
            filename="paper-final.pdf",
        )
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "snapshot.json"
            scan_group(
                self.config,
                state,
                page_size=100,
                client=FakeClient([parent, old_pdf]),
            )
            result = scan_group(
                self.config,
                state,
                page_size=100,
                client=FakeClient([parent, new_pdf], 2),
            )

            self.assertEqual(result["change_count"], 1)
            self.assertEqual(result["changes"][0]["type"], "PDF_ATTACHMENT_CHANGED")

    def test_refuses_to_overwrite_corrupt_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "snapshot.json"
            state.write_text("{broken", encoding="utf-8")

            with self.assertRaises(SnapshotError) as raised:
                scan_group(self.config, state, page_size=100, client=FakeClient([]))

            self.assertEqual(raised.exception.code, "SNAPSHOT_INVALID")
            self.assertEqual(state.read_text(encoding="utf-8"), "{broken")


if __name__ == "__main__":
    unittest.main()
