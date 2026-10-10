from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from hydrolitagent.cards.config import PdfGateConfig, ZoteroConfig
from hydrolitagent.cards.pdf_gate import evaluate_pdf_gate
from hydrolitagent.cards.zotero import ApiResponse, ZoteroApiError


def attachment(key: str, parent_key: str, filename: str = "paper.pdf") -> dict[str, object]:
    return {
        "key": key,
        "data": {
            "key": key,
            "itemType": "attachment",
            "parentItem": parent_key,
            "filename": filename,
            "contentType": "application/pdf",
            "linkMode": "imported_file",
        },
    }


class FakeClient:
    def __init__(
        self,
        *,
        children: list[dict[str, object]],
        file_url: str | None = None,
        fulltext: str | None = "Extracted research text",
        fulltext_missing: bool = False,
    ):
        self.children = children
        self.file_url = file_url
        self.fulltext = fulltext
        self.fulltext_missing = fulltext_missing
        self.text_calls = 0

    def get_json(self, path: str) -> ApiResponse:
        if path.endswith("/children"):
            return ApiResponse(data=self.children, headers={})
        if path.endswith("/fulltext"):
            if self.fulltext_missing:
                raise ZoteroApiError("GROUP_NOT_AVAILABLE", "not found", 404)
            return ApiResponse(data={"content": self.fulltext}, headers={})
        raise AssertionError(f"unexpected JSON path: {path}")

    def get_text(self, path: str) -> ApiResponse:
        if not path.endswith("/file/view/url"):
            raise AssertionError(f"unexpected text path: {path}")
        self.text_calls += 1
        if self.file_url is None:
            raise ZoteroApiError("GROUP_NOT_AVAILABLE", "not found", 404)
        return ApiResponse(data=self.file_url, headers={})


class PdfGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.zotero = ZoteroConfig(group_id=6618088)
        self.gate = PdfGateConfig(
            min_file_size_bytes=64,
            min_text_characters=20,
            hash_chunk_size_bytes=32,
        )

    @staticmethod
    def _write_pdf(directory: str, *, valid: bool = True) -> Path:
        path = Path(directory) / "paper.pdf"
        if valid:
            path.write_bytes(b"%PDF-1.7\n" + b"body" * 32 + b"\n%%EOF\n")
        else:
            path.write_bytes(b"not-a-pdf" * 20)
        return path

    def test_waits_when_parent_has_no_pdf(self) -> None:
        result = evaluate_pdf_gate(
            self.zotero,
            self.gate,
            "PARENT01",
            client=FakeClient(children=[]),
        )

        self.assertEqual(result["gate_status"], "WAITING")
        self.assertEqual(result["reason_code"], "PDF_MISSING")

    def test_ready_when_local_pdf_and_fulltext_are_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_pdf(directory)
            client = FakeClient(
                children=[attachment("PDF00001", "PARENT01")],
                file_url=path.as_uri(),
                fulltext="This is enough extracted text for a research paper.",
            )

            result = evaluate_pdf_gate(
                self.zotero,
                self.gate,
                "PARENT01",
                client=client,
            )

        self.assertEqual(result["gate_status"], "READY")
        self.assertEqual(result["reason_code"], "PDF_READY")
        self.assertEqual(len(result["pdf"]["sha256"]), 64)
        self.assertGreater(result["pdf"]["text_characters"], 20)

    def test_blocks_multiple_pdfs_without_choosing_one(self) -> None:
        client = FakeClient(
            children=[
                attachment("PDF00001", "PARENT01", "main.pdf"),
                attachment("PDF00002", "PARENT01", "supplement.pdf"),
            ]
        )

        result = evaluate_pdf_gate(
            self.zotero,
            self.gate,
            "PARENT01",
            client=client,
        )

        self.assertEqual(result["gate_status"], "BLOCKED")
        self.assertEqual(result["reason_code"], "MULTIPLE_PDFS")
        self.assertEqual(client.text_calls, 0)

    def test_waits_when_attachment_file_is_not_synced(self) -> None:
        result = evaluate_pdf_gate(
            self.zotero,
            self.gate,
            "PARENT01",
            client=FakeClient(children=[attachment("PDF00001", "PARENT01")]),
        )

        self.assertEqual(result["gate_status"], "WAITING")
        self.assertEqual(result["reason_code"], "PDF_FILE_NOT_SYNCED")

    def test_waits_when_zotero_has_not_indexed_fulltext(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_pdf(directory)
            result = evaluate_pdf_gate(
                self.zotero,
                self.gate,
                "PARENT01",
                client=FakeClient(
                    children=[attachment("PDF00001", "PARENT01")],
                    file_url=path.as_uri(),
                    fulltext_missing=True,
                ),
            )

        self.assertEqual(result["gate_status"], "WAITING")
        self.assertEqual(result["reason_code"], "FULLTEXT_NOT_INDEXED")

    def test_blocks_pdf_without_enough_extractable_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_pdf(directory)
            result = evaluate_pdf_gate(
                self.zotero,
                self.gate,
                "PARENT01",
                client=FakeClient(
                    children=[attachment("PDF00001", "PARENT01")],
                    file_url=path.as_uri(),
                    fulltext="scan",
                ),
            )

        self.assertEqual(result["gate_status"], "BLOCKED")
        self.assertEqual(result["reason_code"], "TEXT_NOT_EXTRACTABLE")

    def test_blocks_file_that_is_not_a_structural_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_pdf(directory, valid=False)
            result = evaluate_pdf_gate(
                self.zotero,
                self.gate,
                "PARENT01",
                client=FakeClient(
                    children=[attachment("PDF00001", "PARENT01")],
                    file_url=path.as_uri(),
                ),
            )

        self.assertEqual(result["gate_status"], "BLOCKED")
        self.assertEqual(result["reason_code"], "PDF_STRUCTURE_INVALID")


if __name__ == "__main__":
    unittest.main()
