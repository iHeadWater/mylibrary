from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from hydro_platform.config import PdfGateConfig, ZoteroConfig
from hydro_platform.cli import main
from hydro_platform.paper_input import (
    DEMO_PAPER,
    PaperInputError,
    prepare_demo_paper,
    prepare_paper_batch,
    prepare_paper_input,
)
from hydro_platform.zotero import ApiResponse, ZoteroApiError


class FakeClient:
    def __init__(
        self,
        responses: dict[str, object],
        *,
        text_responses: dict[str, object] | None = None,
    ):
        self.responses = responses
        self.text_responses = text_responses or {}
        self.calls: list[str] = []

    def get_json(self, path: str) -> ApiResponse:
        self.calls.append(path)
        if path not in self.responses:
            raise AssertionError(f"unexpected JSON path: {path}")
        value = self.responses[path]
        if isinstance(value, Exception):
            raise value
        return ApiResponse(data=value, headers={})

    def get_text(self, path: str) -> ApiResponse:
        self.calls.append(path)
        if path not in self.text_responses:
            raise AssertionError(f"unexpected text path: {path}")
        value = self.text_responses[path]
        if isinstance(value, Exception):
            raise value
        return ApiResponse(data=value, headers={})


class PaperInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.zotero = ZoteroConfig(group_id=6618088)
        self.gate = PdfGateConfig(
            min_file_size_bytes=64,
            min_text_characters=20,
            hash_chunk_size_bytes=32,
        )

    def test_query_returns_candidates_and_requires_explicit_selection(self) -> None:
        client = FakeClient(
            {
                "/api/groups/6618088/items/top?q=flood+mapping&qmode=everything&limit=10": [
                    {
                        "key": "PARENT01",
                        "meta": {"creatorSummary": "Twele et al.", "numChildren": 1},
                        "data": {
                            "itemType": "journalArticle",
                            "title": "Sentinel-1-based flood mapping",
                            "date": "2016",
                            "DOI": "10.1080/example",
                        },
                    },
                    {
                        "key": "PDF00001",
                        "data": {
                            "itemType": "attachment",
                            "title": "Unrelated full-text hit",
                        },
                    },
                ]
            }
        )

        result = prepare_paper_input(
            self.zotero,
            self.gate,
            query="flood mapping",
            client=client,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "SELECTION_REQUIRED")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["item_key"], "PARENT01")
        self.assertEqual(result["candidates"][0]["title"], "Sentinel-1-based flood mapping")
        self.assertEqual(
            client.calls,
            ["/api/groups/6618088/items/top?q=flood+mapping&qmode=everything&limit=10"],
        )

    def test_invalid_item_key_has_stable_error_code(self) -> None:
        with self.assertRaises(PaperInputError) as caught:
            prepare_paper_input(
                self.zotero,
                self.gate,
                item_key="bad-key",
                client=FakeClient({}),
            )

        self.assertEqual(caught.exception.code, "INVALID_ITEM_KEY")

    def test_item_key_is_ready_with_local_pdf_when_fulltext_is_not_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.7\n" + b"body" * 32 + b"\n%%EOF\n")
            client = FakeClient(
                {
                    "/api/users/0/items/PARENT01": {
                        "key": "PARENT01",
                        "meta": {"creatorSummary": "Wing et al.", "numChildren": 1},
                        "data": {
                            "itemType": "journalArticle",
                            "title": "Continental flood simulation",
                            "date": "2021",
                            "DOI": "10.5194/example",
                        },
                    },
                    "/api/users/0/items/PARENT01/children": [
                        {
                            "key": "PDF00001",
                            "data": {
                                "key": "PDF00001",
                                "itemType": "attachment",
                                "parentItem": "PARENT01",
                                "filename": "paper.pdf",
                                "contentType": "application/pdf",
                                "linkMode": "imported_file",
                            },
                        }
                    ],
                    "/api/users/0/items/PDF00001/fulltext": ZoteroApiError(
                        "GROUP_NOT_AVAILABLE", "not found", 404
                    ),
                },
                text_responses={
                    "/api/users/0/items/PDF00001/file/view/url": pdf_path.as_uri()
                },
            )

            result = prepare_paper_input(
                self.zotero,
                self.gate,
                item_key="parent01",
                library_type="user",
                client=client,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["reason_code"], "PDF_READY")
        self.assertEqual(result["item"]["item_key"], "PARENT01")
        self.assertEqual(result["pdf"]["attachment_key"], "PDF00001")
        self.assertFalse(result["pdf"]["fulltext_indexed"])
        self.assertEqual(len(result["pdf"]["sha256"]), 64)

    def test_empty_fulltext_response_is_ready_but_not_marked_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.7\n" + b"body" * 32 + b"\n%%EOF\n")
            client = FakeClient(
                {
                    "/api/users/0/items/PARENT01": {
                        "key": "PARENT01",
                        "data": {"itemType": "journalArticle", "title": "Flood paper"},
                    },
                    "/api/users/0/items/PARENT01/children": [
                        {
                            "key": "PDF00001",
                            "data": {
                                "key": "PDF00001",
                                "itemType": "attachment",
                                "parentItem": "PARENT01",
                                "filename": "paper.pdf",
                                "contentType": "application/pdf",
                            },
                        }
                    ],
                    "/api/users/0/items/PDF00001/fulltext": {"content": "   \n"},
                },
                text_responses={
                    "/api/users/0/items/PDF00001/file/view/url": pdf_path.as_uri()
                },
            )

            result = prepare_paper_input(
                self.zotero,
                self.gate,
                item_key="PARENT01",
                library_type="user",
                client=client,
            )

        self.assertEqual(result["status"], "READY")
        self.assertFalse(result["pdf"]["fulltext_indexed"])
        self.assertEqual(result["pdf"]["text_characters"], 0)

    def test_item_key_blocks_and_lists_all_pdf_candidates(self) -> None:
        item = {
            "key": "PARENT01",
            "data": {"itemType": "journalArticle", "title": "Flood study"},
        }
        pdfs = [
            {
                "key": key,
                "data": {
                    "key": key,
                    "itemType": "attachment",
                    "parentItem": "PARENT01",
                    "filename": filename,
                    "contentType": "application/pdf",
                    "linkMode": "imported_file",
                },
            }
            for key, filename in (
                ("PDF00001", "main.pdf"),
                ("PDF00002", "supplement.pdf"),
            )
        ]
        client = FakeClient(
            {
                "/api/groups/6618088/items/PARENT01": item,
                "/api/groups/6618088/items/PARENT01/children": pdfs,
            }
        )

        result = prepare_paper_input(
            self.zotero,
            self.gate,
            item_key="PARENT01",
            client=client,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason_code"], "MULTIPLE_PDFS")
        self.assertEqual(result["pdf_attachment_count"], 2)
        self.assertEqual(
            [candidate["filename"] for candidate in result["candidates"]],
            ["main.pdf", "supplement.pdf"],
        )
        self.assertEqual(len(client.calls), 2)

    def test_item_key_reports_missing_pdf_without_stopping_the_run(self) -> None:
        client = FakeClient(
            {
                "/api/groups/6618088/items/PARENT01": {
                    "key": "PARENT01",
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Paper without PDF",
                        "url": "https://doi.org/10.1000/example",
                    },
                },
                "/api/groups/6618088/items/PARENT01/children": [],
            }
        )

        result = prepare_paper_input(
            self.zotero,
            self.gate,
            item_key="PARENT01",
            client=client,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "WAITING")
        self.assertEqual(result["reason_code"], "PDF_MISSING")
        self.assertEqual(result["pdf_attachment_count"], 0)

    def test_demo_requires_connector_import_when_article_is_not_local(self) -> None:
        client = FakeClient(
            {
                (
                    "/api/users/0/items/top?"
                    "q=10.5194%2Fnhess-21-559-2021&qmode=everything&limit=10"
                ): []
            }
        )

        result = prepare_demo_paper(self.zotero, self.gate, client=client)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "IMPORT_REQUIRED")
        self.assertEqual(result["reason_code"], "ITEM_NOT_IN_LIBRARY")
        self.assertEqual(result["doi"], "10.5194/nhess-21-559-2021")
        self.assertEqual(result["source_url"], DEMO_PAPER["source_url"])
        self.assertEqual(result["pdf_url"], DEMO_PAPER["pdf_url"])
        self.assertEqual(
            result["destination"],
            "我的文库 → 科研平台 → 证据卡训练集",
        )

    def test_attachment_key_is_resolved_to_its_parent_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.7\n" + b"body" * 32 + b"\n%%EOF\n")
            client = FakeClient(
                {
                    "/api/users/0/items/PDF00001": {
                        "key": "PDF00001",
                        "data": {
                            "itemType": "attachment",
                            "parentItem": "PARENT01",
                            "filename": "paper.pdf",
                            "contentType": "application/pdf",
                        },
                    },
                    "/api/users/0/items/PARENT01": {
                        "key": "PARENT01",
                        "data": {
                            "itemType": "journalArticle",
                            "title": "Resolved parent",
                        },
                    },
                    "/api/users/0/items/PARENT01/children": [
                        {
                            "key": "PDF00001",
                            "data": {
                                "key": "PDF00001",
                                "itemType": "attachment",
                                "parentItem": "PARENT01",
                                "filename": "paper.pdf",
                                "contentType": "application/pdf",
                                "linkMode": "imported_file",
                            },
                        }
                    ],
                    "/api/users/0/items/PDF00001/fulltext": {"content": "indexed text"},
                },
                text_responses={
                    "/api/users/0/items/PDF00001/file/view/url": pdf_path.as_uri()
                },
            )

            result = prepare_paper_input(
                self.zotero,
                self.gate,
                item_key="PDF00001",
                library_type="user",
                client=client,
            )

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["requested_item_key"], "PDF00001")
        self.assertEqual(result["item"]["item_key"], "PARENT01")

    def test_any_child_with_parent_item_is_resolved_to_parent(self) -> None:
        client = FakeClient(
            {
                "/api/users/0/items/NOTE0001": {
                    "key": "NOTE0001",
                    "data": {"itemType": "note", "parentItem": "PARENT01"},
                },
                "/api/users/0/items/PARENT01": {
                    "key": "PARENT01",
                    "data": {"itemType": "journalArticle", "title": "Resolved parent"},
                },
                "/api/users/0/items/PARENT01/children": [],
            }
        )

        result = prepare_paper_input(
            self.zotero,
            self.gate,
            item_key="NOTE0001",
            library_type="user",
            client=client,
        )

        self.assertEqual(result["status"], "WAITING")
        self.assertEqual(result["requested_item_key"], "NOTE0001")
        self.assertEqual(result["item"]["item_key"], "PARENT01")

    def test_missing_local_attachment_is_recorded_without_stopping(self) -> None:
        client = FakeClient(
            {
                "/api/groups/6618088/items/PARENT01": {
                    "key": "PARENT01",
                    "data": {"itemType": "journalArticle", "title": "Flood paper"},
                },
                "/api/groups/6618088/items/PARENT01/children": [
                    {
                        "key": "PDF00001",
                        "data": {
                            "key": "PDF00001",
                            "itemType": "attachment",
                            "parentItem": "PARENT01",
                            "filename": "paper.pdf",
                            "contentType": "application/pdf",
                            "linkMode": "imported_file",
                        },
                    }
                ],
            },
            text_responses={
                "/api/groups/6618088/items/PDF00001/file/view/url": ZoteroApiError(
                    "GROUP_NOT_AVAILABLE", "not found", 404
                )
            },
        )

        result = prepare_paper_input(
            self.zotero,
            self.gate,
            item_key="PARENT01",
            client=client,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "WAITING")
        self.assertEqual(result["reason_code"], "PDF_FILE_NOT_SYNCED")

    def test_invalid_pdf_structure_is_recorded_without_stopping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid_path = Path(directory) / "broken.pdf"
            invalid_path.write_bytes(b"not a real pdf" * 20)
            client = FakeClient(
                {
                    "/api/groups/6618088/items/PARENT01": {
                        "key": "PARENT01",
                        "data": {"itemType": "journalArticle", "title": "Broken PDF"},
                    },
                    "/api/groups/6618088/items/PARENT01/children": [
                        {
                            "key": "PDF00001",
                            "data": {
                                "key": "PDF00001",
                                "itemType": "attachment",
                                "parentItem": "PARENT01",
                                "filename": "broken.pdf",
                                "contentType": "application/pdf",
                            },
                        }
                    ],
                },
                text_responses={
                    "/api/groups/6618088/items/PDF00001/file/view/url": invalid_path.as_uri()
                },
            )

            result = prepare_paper_input(
                self.zotero,
                self.gate,
                item_key="PARENT01",
                client=client,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason_code"], "PDF_STRUCTURE_INVALID")

    def test_unknown_item_key_is_a_recorded_problem(self) -> None:
        client = FakeClient(
            {
                "/api/groups/6618088/items/MISSING1": ZoteroApiError(
                    "GROUP_NOT_AVAILABLE", "not found", 404
                )
            }
        )

        result = prepare_paper_input(
            self.zotero,
            self.gate,
            item_key="MISSING1",
            client=client,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason_code"], "ITEM_NOT_FOUND")
        self.assertEqual(result["requested_item_key"], "MISSING1")

    def test_batch_continues_after_multiple_pdfs_and_summarizes_problem(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "ready.pdf"
            pdf_path.write_bytes(b"%PDF-1.7\n" + b"body" * 32 + b"\n%%EOF\n")
            client = FakeClient(
                {
                    "/api/groups/6618088/items/PROBLEM1": {
                        "key": "PROBLEM1",
                        "data": {"itemType": "journalArticle", "title": "Problem paper"},
                    },
                    "/api/groups/6618088/items/PROBLEM1/children": [
                        {
                            "key": key,
                            "data": {
                                "key": key,
                                "itemType": "attachment",
                                "parentItem": "PROBLEM1",
                                "filename": filename,
                                "contentType": "application/pdf",
                            },
                        }
                        for key, filename in (
                            ("PDF00001", "one.pdf"),
                            ("PDF00002", "two.pdf"),
                        )
                    ],
                    "/api/groups/6618088/items/READY001": {
                        "key": "READY001",
                        "data": {"itemType": "journalArticle", "title": "Ready paper"},
                    },
                    "/api/groups/6618088/items/READY001/children": [
                        {
                            "key": "PDF00003",
                            "data": {
                                "key": "PDF00003",
                                "itemType": "attachment",
                                "parentItem": "READY001",
                                "filename": "ready.pdf",
                                "contentType": "application/pdf",
                            },
                        }
                    ],
                    "/api/groups/6618088/items/PDF00003/fulltext": ZoteroApiError(
                        "GROUP_NOT_AVAILABLE", "not found", 404
                    ),
                },
                text_responses={
                    "/api/groups/6618088/items/PDF00003/file/view/url": pdf_path.as_uri()
                },
            )

            result = prepare_paper_batch(
                self.zotero,
                self.gate,
                ["PROBLEM1", "READY001"],
                client=client,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "COMPLETED_WITH_PROBLEMS")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["ready_count"], 1)
        self.assertEqual(result["problem_count"], 1)
        self.assertEqual(result["problems"][0]["item_key"], "PROBLEM1")
        self.assertEqual(result["problems"][0]["reason_code"], "MULTIPLE_PDFS")

    @patch("hydro_platform.cli.prepare_demo_paper")
    def test_cli_exposes_reproducible_demo_without_fixed_item_key(self, demo) -> None:
        demo.return_value = {
            "schema_version": 1,
            "ok": True,
            "operation": "paper_input",
            "status": "IMPORT_REQUIRED",
            "reason_code": "ITEM_NOT_IN_LIBRARY",
            "source_url": DEMO_PAPER["source_url"],
        }
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(["paper-input", "--demo", "--json"])

        payload = __import__("json").loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "IMPORT_REQUIRED")
        demo.assert_called_once()

    @patch("hydro_platform.cli.prepare_paper_batch")
    def test_cli_accepts_repeated_item_keys_for_non_stopping_batch(self, batch) -> None:
        batch.return_value = {
            "schema_version": 1,
            "ok": True,
            "operation": "paper_input_batch",
            "status": "COMPLETED_WITH_PROBLEMS",
            "total": 2,
            "ready_count": 1,
            "problem_count": 1,
            "results": [],
            "problems": [],
        }
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(
                [
                    "paper-input",
                    "--item-key",
                    "PROBLEM1",
                    "--item-key",
                    "READY001",
                    "--json",
                ]
            )

        payload = __import__("json").loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "COMPLETED_WITH_PROBLEMS")
        self.assertEqual(batch.call_args.args[2], ["PROBLEM1", "READY001"])

    @patch("hydro_platform.cli.prepare_demo_paper")
    def test_cli_human_output_describes_import_required(self, demo) -> None:
        demo.return_value = {
            "schema_version": 1,
            "ok": True,
            "operation": "paper_input",
            "status": "IMPORT_REQUIRED",
            "reason_code": "ITEM_NOT_IN_LIBRARY",
            "message": "请先抓取",
            "source_url": DEMO_PAPER["source_url"],
        }
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(["paper-input", "--demo"])

        self.assertEqual(exit_code, 0)
        self.assertIn("IMPORT_REQUIRED", output.getvalue())
        self.assertIn(DEMO_PAPER["source_url"], output.getvalue())
        self.assertNotIn("失败", output.getvalue())


if __name__ == "__main__":
    unittest.main()
