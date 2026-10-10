from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from hydrolitagent.cards.config import PdfGateConfig, ZoteroConfig
from hydrolitagent.cards.cli import main
from hydrolitagent.cards.paper_input import (
    DEMO_PAPER,
    PaperInputError,
    prepare_demo_paper,
    prepare_paper_batch,
    prepare_paper_input,
)
from hydrolitagent.cards.zotero import ApiResponse, ZoteroApiError

class FakeClient:
    def __init__(
        self,
        responses: dict[str, object],
        *,
        text_responses: dict[str, object] | None = None,
    ) -> None:
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
                (
                    "/api/groups/6618088/items/top?"
                    "q=flood+mapping&qmode=everything&limit=10"
                ): [
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
        self.assertEqual(
            result["candidates"][0]["title"],
            "Sentinel-1-based flood mapping",
        )
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

    def test_item_key_is_ready_with_local_pdf_when_fulltext_is_not_indexed(
        self,
    ) -> None:
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

    def test_fulltext_api_error_does_not_block_a_readable_local_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.7\n" + b"body" * 32 + b"\n%%EOF\n")
            client = FakeClient(
                {
                    "/api/users/0/items/PARENT01": {
                        "key": "PARENT01",
                        "data": {
                            "itemType": "journalArticle",
                            "title": "Flood paper",
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
                            },
                        }
                    ],
                    "/api/users/0/items/PDF00001/fulltext": ZoteroApiError(
                        "ZOTERO_HTTP_ERROR",
                        "temporary fulltext failure",
                        500,
                    ),
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

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "READY")
        self.assertFalse(result["pdf"]["fulltext_indexed"])
        self.assertEqual(
            result["pdf"]["fulltext_error"]["code"],
            "ZOTERO_HTTP_ERROR",
        )

    def test_invalid_fulltext_payload_does_not_block_a_readable_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.7\n" + b"body" * 32 + b"\n%%EOF\n")
            client = FakeClient(
                {
                    "/api/users/0/items/PARENT01": {
                        "key": "PARENT01",
                        "data": {
                            "itemType": "journalArticle",
                            "title": "Flood paper",
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
                            },
                        }
                    ],
                    "/api/users/0/items/PDF00001/fulltext": {"content": 42},
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

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "READY")
        self.assertFalse(result["pdf"]["fulltext_indexed"])
        self.assertEqual(
            result["pdf"]["fulltext_error"]["code"],
            "INVALID_API_RESPONSE",
        )

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

        self.assertFalse(result["ok"])
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

        self.assertFalse(result["ok"])
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

        self.assertFalse(result["ok"])
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

        self.assertFalse(result["ok"])
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
                    (
                        "/api/groups/6618088/items/"
                        "PDF00001/file/view/url"
                    ): invalid_path.as_uri()
                },
            )

            result = prepare_paper_input(
                self.zotero,
                self.gate,
                item_key="PARENT01",
                client=client,
            )

        self.assertFalse(result["ok"])
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

        self.assertFalse(result["ok"])
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
                        "data": {
                            "itemType": "journalArticle",
                            "title": "Problem paper",
                        },
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
                    (
                        "/api/groups/6618088/items/"
                        "PDF00003/file/view/url"
                    ): pdf_path.as_uri()
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
        self.assertFalse(result["results"][0]["ok"])
        self.assertTrue(result["results"][1]["ok"])

    @patch("hydrolitagent.cards.cli.prepare_demo_paper")
    def test_cli_exposes_reproducible_demo_without_fixed_item_key(
        self,
        demo: Any,
    ) -> None:
        demo.return_value = {
            "schema_version": 1,
            "ok": False,
            "operation": "paper_input",
            "status": "IMPORT_REQUIRED",
            "reason_code": "ITEM_NOT_IN_LIBRARY",
            "source_url": DEMO_PAPER["source_url"],
        }
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(["paper-input", "--demo", "--json"])

        payload = __import__("json").loads(output.getvalue())
        self.assertEqual(exit_code, 3)
        self.assertEqual(payload["status"], "IMPORT_REQUIRED")
        demo.assert_called_once()

    @patch("hydrolitagent.cards.cli.prepare_paper_batch")
    def test_cli_accepts_repeated_item_keys_for_non_stopping_batch(
        self,
        batch: Any,
    ) -> None:
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
                    "--user-library",
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

    @patch("hydrolitagent.cards.cli.prepare_paper_batch")
    def test_cli_human_batch_output_lists_multiple_pdf_candidates(
        self,
        batch: Any,
    ) -> None:
        batch.return_value = {
            "schema_version": 1,
            "ok": True,
            "operation": "paper_input_batch",
            "status": "COMPLETED_WITH_PROBLEMS",
            "total": 2,
            "ready_count": 1,
            "problem_count": 1,
            "results": [],
            "problems": [
                {
                    "item_key": "PROBLEM1",
                    "title": "Problem paper",
                    "status": "BLOCKED",
                    "reason_code": "MULTIPLE_PDFS",
                    "message": "multiple PDFs",
                    "candidates": [
                        {"attachment_key": "PDF00001", "filename": "one.pdf"},
                        {"attachment_key": "PDF00002", "filename": "two.pdf"},
                    ],
                }
            ],
        }
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(
                [
                    "paper-input",
                    "--user-library",
                    "--item-key",
                    "PROBLEM1",
                    "--item-key",
                    "READY001",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("PROBLEM1", output.getvalue())
        self.assertIn("one.pdf", output.getvalue())
        self.assertIn("two.pdf", output.getvalue())

    @patch("hydrolitagent.cards.cli.prepare_demo_paper")
    def test_cli_human_output_describes_import_required(
        self,
        demo: Any,
    ) -> None:
        demo.return_value = {
            "schema_version": 1,
            "ok": False,
            "operation": "paper_input",
            "status": "IMPORT_REQUIRED",
            "reason_code": "ITEM_NOT_IN_LIBRARY",
            "message": "请先抓取",
            "source_url": DEMO_PAPER["source_url"],
        }
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(["paper-input", "--demo"])

        self.assertEqual(exit_code, 3)
        self.assertIn("IMPORT_REQUIRED", output.getvalue())
        self.assertIn(DEMO_PAPER["source_url"], output.getvalue())
        self.assertNotIn("失败", output.getvalue())

    def test_cli_human_output_handles_invalid_item_key(self) -> None:
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(["paper-input", "--user-library", "--item-key", "bad-key"])

        self.assertEqual(exit_code, 3)
        self.assertIn("INVALID_ITEM_KEY", output.getvalue())

@unittest.skipUnless(
    os.environ.get("HYDRO_RUN_ZOTERO_DEMO") == "1",
    "set HYDRO_RUN_ZOTERO_DEMO=1 after importing the public demo paper",
)
class PaperInputLiveIntegrationTests(unittest.TestCase):
    def test_public_demo_paper_resolves_to_a_readable_local_pdf(self) -> None:
        result = prepare_demo_paper(
            ZoteroConfig(),
            PdfGateConfig(
                min_file_size_bytes=1024,
                min_text_characters=1000,
                hash_chunk_size_bytes=1048576,
            ),
        )

        self.assertEqual(result["status"], "READY", result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["item"]["doi"], DEMO_PAPER["doi"])
        self.assertEqual(len(result["pdf"]["sha256"]), 64)

if __name__ == "__main__":
    unittest.main()

class StandaloneInputConfigTests(unittest.TestCase):
    def test_defaults_do_not_read_model_config(self):
        from hydrolitagent.cards.paper_input_config import load_paper_input_config
        with patch.dict(os.environ, {"HYDRO_PLATFORM_CONFIG": "absent-private-config.json"}):
            config = load_paper_input_config()
        self.assertEqual(config.zotero.base_url, "http://127.0.0.1:23119")
        self.assertIsNone(config.zotero.group_id)

    def test_input_environment_and_cli_override_file(self):
        from hydrolitagent.cards.paper_input_config import load_paper_input_config
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "input.toml"
            config.write_text('[zotero]\ngroup_id = 3\ntimeout_seconds = 4.0\n', encoding="utf-8")
            with patch.dict(os.environ, {"HYDRO_PLATFORM_ZOTERO_GROUP_ID": "5"}):
                self.assertEqual(load_paper_input_config(config).zotero.group_id, 5)
                self.assertEqual(load_paper_input_config(config, group_id="7").zotero.group_id, 7)

    def test_legacy_json_reads_only_input_fields(self):
        from hydrolitagent.cards.paper_input_config import load_paper_input_config
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "local.json"
            config.write_text('{"zotero":{"group_id":7},"card_generator":"invalid obsolete AI config"}', encoding="utf-8")
            self.assertEqual(load_paper_input_config(config).zotero.group_id, 7)

    def test_missing_group_is_actionable(self):
        from hydrolitagent.cards.paper_input_config import load_paper_input_config
        from hydrolitagent.cards.config import ConfigError
        with self.assertRaisesRegex(ConfigError, "--user-library"):
            load_paper_input_config(require_group=True)

    def test_invalid_network_config_is_rejected(self):
        from hydrolitagent.cards.paper_input_config import load_paper_input_config
        from hydrolitagent.cards.config import ConfigError
        for url in ("ftp://localhost", "http://user:pass@localhost", "http://localhost/anything", "http://localhost:invalid"):
            with self.subTest(url=url), self.assertRaises(ConfigError):
                load_paper_input_config(base_url=url)
        for timeout in (float("nan"), 0, -1, True):
            with self.subTest(timeout=timeout), self.assertRaises(ConfigError):
                load_paper_input_config(timeout_seconds=timeout)
