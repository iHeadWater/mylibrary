from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from hydro_platform import pdf_reader_mcp


class BoundPdfReaderTests(unittest.TestCase):
    def test_transport_json_is_ascii_safe_and_round_trips_unicode(self) -> None:
        message = {"jsonrpc": "2.0", "id": 1, "result": {"filename": "论文📄.pdf"}}

        serialized = pdf_reader_mcp._serialize_transport_message(message)

        serialized.encode("ascii")
        self.assertEqual(json.loads(serialized), message)

    def test_tools_are_declared_read_only_and_server_requires_full_read(self) -> None:
        reader = object.__new__(pdf_reader_mcp.BoundPdfReader)
        definitions = pdf_reader_mcp._tool_definitions(reader)

        self.assertIn("first action", pdf_reader_mcp.SERVER_INSTRUCTIONS)
        self.assertIn("read_full_source_pdf", pdf_reader_mcp.SERVER_INSTRUCTIONS)
        self.assertEqual(
            [definition["name"] for definition in definitions],
            ["read_full_source_pdf"],
        )
        for definition in definitions:
            self.assertEqual(
                definition["annotations"],
                {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            )

    def test_full_read_tool_batches_every_page_inside_one_call(self) -> None:
        class FakeReader:
            max_pages_per_call = 4

            def __init__(self) -> None:
                self.ranges: list[tuple[int, int]] = []

            def inspect(self) -> dict[str, object]:
                return {"page_count": 10, "max_pages_per_call": 4}

            def read_pages(self, start_page: int, end_page: int) -> list[dict[str, str]]:
                self.ranges.append((start_page, end_page))
                return [{"type": "text", "text": f"{start_page}-{end_page}"}]

        reader = FakeReader()

        result = pdf_reader_mcp._tool_call(
            reader,  # type: ignore[arg-type]
            {"name": "read_full_source_pdf", "arguments": {}},
        )

        self.assertEqual(reader.ranges, [(1, 4), (5, 8), (9, 10)])
        self.assertFalse(result["isError"])
        self.assertEqual(len(result["content"]), 4)

    def test_serves_text_and_page_images_and_writes_complete_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "paper.pdf"
            source_pdf.write_bytes(b"%PDF-1.7\nfixture")
            source_sha256 = hashlib.sha256(source_pdf.read_bytes()).hexdigest()
            receipt_path = root / "receipt.json"
            environment = {
                "HYDRO_SOURCE_PDF": str(source_pdf),
                "HYDRO_SOURCE_PDF_SHA256": source_sha256,
                "HYDRO_PDF_RECEIPT": str(receipt_path),
                "HYDRO_ZOTERO_PARENT_KEY": "CEXH4PQA",
                "HYDRO_PDFINFO_EXECUTABLE": "pdfinfo",
                "HYDRO_PDFTOTEXT_EXECUTABLE": "pdftotext",
                "HYDRO_PDFTOPPM_EXECUTABLE": "pdftoppm",
                "HYDRO_PDF_RENDER_DPI": "120",
                "HYDRO_PDF_MAX_PAGES_PER_CALL": "4",
                "HYDRO_PDF_DEPENDENCY_TIMEOUT_SECONDS": "30",
            }

            def fake_run(
                command: list[str], *, timeout_seconds: int
            ) -> subprocess.CompletedProcess[bytes]:
                self.assertEqual(timeout_seconds, 30)
                if command[0] == "pdfinfo":
                    return subprocess.CompletedProcess(
                        command, 0, stdout=b"Pages:          2\n", stderr=b""
                    )
                if command[0] == "pdftotext":
                    page = command[command.index("-f") + 1]
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=f"page {page} text".encode(),
                        stderr=b"",
                    )
                if command[0] == "pdftoppm":
                    Path(command[-1]).with_suffix(".jpg").write_bytes(b"jpeg-data")
                    return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
                raise AssertionError(command)

            with (
                patch.dict(os.environ, environment, clear=False),
                patch.object(pdf_reader_mcp, "_run", side_effect=fake_run),
            ):
                reader = pdf_reader_mcp.BoundPdfReader()
                inspection = reader.inspect()
                content = reader.read_pages(1, 2)

            self.assertEqual(inspection["page_count"], 2)
            self.assertEqual([item["type"] for item in content], ["text", "image"] * 2)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["source_sha256"], source_sha256)
            self.assertEqual(set(receipt["pages"]), {"1", "2"})
            self.assertTrue(receipt["pages"]["1"]["image_delivered"])

    def test_rejects_hash_mismatch_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "paper.pdf"
            source_pdf.write_bytes(b"%PDF-1.7\nfixture")
            environment = {
                "HYDRO_SOURCE_PDF": str(source_pdf),
                "HYDRO_SOURCE_PDF_SHA256": "0" * 64,
                "HYDRO_PDF_RECEIPT": str(root / "receipt.json"),
                "HYDRO_ZOTERO_PARENT_KEY": "CEXH4PQA",
                "HYDRO_PDFINFO_EXECUTABLE": "pdfinfo",
                "HYDRO_PDFTOTEXT_EXECUTABLE": "pdftotext",
                "HYDRO_PDFTOPPM_EXECUTABLE": "pdftoppm",
                "HYDRO_PDF_RENDER_DPI": "120",
                "HYDRO_PDF_MAX_PAGES_PER_CALL": "4",
                "HYDRO_PDF_DEPENDENCY_TIMEOUT_SECONDS": "30",
            }
            with patch.dict(os.environ, environment, clear=False):
                reader = pdf_reader_mcp.BoundPdfReader()
                with self.assertRaisesRegex(pdf_reader_mcp.ToolError, "SHA-256"):
                    reader.inspect()


if __name__ == "__main__":
    unittest.main()
