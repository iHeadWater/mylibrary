from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SERVER_NAME = "hydro-platform-pdf-reader"
SERVER_VERSION = "1.0.0"
RECEIPT_SCHEMA_VERSION = 1
PAGE_COUNT_PATTERN = re.compile(r"^Pages:\s*(\d+)\s*$", re.MULTILINE)
SERVER_INSTRUCTIONS = (
    "This server exposes the only authoritative source PDF for the current task. "
    "Your first action must be read_full_source_pdf. That single tool call internally "
    "reads every page from page 1 through the final page without gaps and returns both "
    "extracted text and a rendered image for every page. Do not produce the final answer "
    "before that tool call completes."
)


class ToolError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ToolError(f"missing required environment binding: {name}")
    return value


def _positive_int_environment(name: str) -> int:
    raw_value = _required_environment(name)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ToolError(f"invalid integer environment binding: {name}") from exc
    if value <= 0:
        raise ToolError(f"invalid positive environment binding: {name}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, timeout_seconds: int) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolError("PDF reader dependency could not be executed") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ToolError(
            "PDF reader dependency failed"
            + (f": {detail[:300]}" if detail else "")
        )
    return result


class BoundPdfReader:
    def __init__(self) -> None:
        self.source_pdf = Path(_required_environment("HYDRO_SOURCE_PDF")).resolve(
            strict=True
        )
        if not self.source_pdf.is_file() or self.source_pdf.suffix.casefold() != ".pdf":
            raise ToolError("bound source is not a readable PDF file")
        self.expected_sha256 = _required_environment(
            "HYDRO_SOURCE_PDF_SHA256"
        ).casefold()
        self.receipt_path = Path(
            _required_environment("HYDRO_PDF_RECEIPT")
        ).resolve()
        self.parent_key = _required_environment("HYDRO_ZOTERO_PARENT_KEY")
        self.pdfinfo_executable = _required_environment("HYDRO_PDFINFO_EXECUTABLE")
        self.pdftotext_executable = _required_environment("HYDRO_PDFTOTEXT_EXECUTABLE")
        self.pdftoppm_executable = _required_environment("HYDRO_PDFTOPPM_EXECUTABLE")
        self.render_dpi = _positive_int_environment("HYDRO_PDF_RENDER_DPI")
        self.max_pages_per_call = _positive_int_environment(
            "HYDRO_PDF_MAX_PAGES_PER_CALL"
        )
        self.dependency_timeout_seconds = _positive_int_environment(
            "HYDRO_PDF_DEPENDENCY_TIMEOUT_SECONDS"
        )
        self._page_count: int | None = None
        self._actual_sha256: str | None = None
        self._receipt: dict[str, Any] = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "reader": SERVER_NAME,
            "reader_version": SERVER_VERSION,
            "zotero_parent_key": self.parent_key,
            "source_filename": self.source_pdf.name,
            "source_sha256": None,
            "page_count": None,
            "inspected": False,
            "pages": {},
            "updated_at": _now(),
        }

    def _write_receipt(self) -> None:
        self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.receipt_path.with_suffix(
            self.receipt_path.suffix + ".tmp"
        )
        temporary_path.write_text(
            json.dumps(self._receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, self.receipt_path)

    def inspect(self) -> dict[str, Any]:
        actual_sha256 = _sha256(self.source_pdf)
        if actual_sha256.casefold() != self.expected_sha256:
            raise ToolError("bound PDF SHA-256 does not match the task input")
        result = _run(
            [self.pdfinfo_executable, str(self.source_pdf)],
            timeout_seconds=self.dependency_timeout_seconds,
        )
        info = result.stdout.decode("utf-8", errors="replace")
        match = PAGE_COUNT_PATTERN.search(info)
        if match is None:
            raise ToolError("pdfinfo did not return a valid page count")
        page_count = int(match.group(1))
        if page_count <= 0:
            raise ToolError("PDF page count must be positive")
        self._actual_sha256 = actual_sha256
        self._page_count = page_count
        self._receipt.update(
            {
                "source_sha256": actual_sha256,
                "page_count": page_count,
                "inspected": True,
                "inspected_at": _now(),
                "updated_at": _now(),
            }
        )
        self._write_receipt()
        return {
            "source_filename": self.source_pdf.name,
            "zotero_parent_key": self.parent_key,
            "source_sha256": actual_sha256,
            "page_count": page_count,
            "max_pages_per_call": self.max_pages_per_call,
        }

    def _ensure_inspected(self) -> int:
        if self._page_count is None:
            self.inspect()
        assert self._page_count is not None
        return self._page_count

    def _extract_page_text(self, page_number: int) -> str:
        result = _run(
            [
                self.pdftotext_executable,
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-layout",
                "-enc",
                "UTF-8",
                str(self.source_pdf),
                "-",
            ],
            timeout_seconds=self.dependency_timeout_seconds,
        )
        return result.stdout.decode("utf-8", errors="replace").strip()

    def _render_page(self, page_number: int, output_prefix: Path) -> bytes:
        _run(
            [
                self.pdftoppm_executable,
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-singlefile",
                "-jpeg",
                "-jpegopt",
                "quality=78,optimize=y",
                "-r",
                str(self.render_dpi),
                str(self.source_pdf),
                str(output_prefix),
            ],
            timeout_seconds=self.dependency_timeout_seconds,
        )
        image_path = output_prefix.with_suffix(".jpg")
        try:
            image = image_path.read_bytes()
        except OSError as exc:
            raise ToolError("pdftoppm did not produce the requested page image") from exc
        if not image:
            raise ToolError("rendered PDF page image is empty")
        return image

    def read_pages(self, start_page: int, end_page: int) -> list[dict[str, Any]]:
        page_count = self._ensure_inspected()
        if start_page < 1 or end_page < start_page or end_page > page_count:
            raise ToolError(f"page range must be within 1..{page_count}")
        if end_page - start_page + 1 > self.max_pages_per_call:
            raise ToolError(
                f"one call may read at most {self.max_pages_per_call} pages"
            )

        content: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix="hydro-pdf-pages-") as directory:
            temporary_directory = Path(directory)
            for page_number in range(start_page, end_page + 1):
                text = self._extract_page_text(page_number)
                image = self._render_page(
                    page_number,
                    temporary_directory / f"page-{page_number}",
                )
                content.append(
                    {
                        "type": "text",
                        "text": (
                            f"SOURCE PDF PAGE {page_number}/{page_count}\n"
                            + (text if text else "[No extractable text on this page]")
                        ),
                    }
                )
                content.append(
                    {
                        "type": "image",
                        "data": base64.b64encode(image).decode("ascii"),
                        "mimeType": "image/jpeg",
                    }
                )
                self._receipt["pages"][str(page_number)] = {
                    "text_characters": len(text),
                    "image_delivered": True,
                    "image_mime_type": "image/jpeg",
                    "served_at": _now(),
                }
                self._receipt["updated_at"] = _now()
                self._write_receipt()
        return content


def _tool_definitions(reader: BoundPdfReader) -> list[dict[str, Any]]:
    return [
        {
            "name": "read_full_source_pdf",
            "description": (
                "Required source-reading operation. Verify the SHA-256 of the one "
                "task-bound Zotero PDF, then read the complete document internally "
                "in bounded batches. Returns metadata plus extracted text and a "
                "rendered image for every page. This tool cannot open arbitrary paths."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
    ]


def _tool_call(reader: BoundPdfReader, params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise ToolError("tools/call params must be an object")
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ToolError("tool arguments must be an object")
    if name == "read_full_source_pdf":
        if arguments:
            raise ToolError("read_full_source_pdf does not accept arguments")
        inspection = reader.inspect()
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": "SOURCE PDF METADATA\n"
                + json.dumps(inspection, ensure_ascii=False),
            }
        ]
        page_count = inspection["page_count"]
        for start_page in range(1, page_count + 1, reader.max_pages_per_call):
            end_page = min(
                start_page + reader.max_pages_per_call - 1,
                page_count,
            )
            content.extend(reader.read_pages(start_page, end_page))
        return {
            "content": content,
            "isError": False,
        }
    raise ToolError("unknown PDF reader tool")


def _response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _serialize_transport_message(message: dict[str, Any]) -> str:
    """Return an ASCII-only JSON line so Windows code pages cannot corrupt MCP."""

    return json.dumps(message, ensure_ascii=True, separators=(",", ":"))


def _emit_transport_message(message: dict[str, Any]) -> None:
    print(_serialize_transport_message(message), flush=True)


def serve() -> int:
    try:
        reader = BoundPdfReader()
    except (OSError, ToolError) as exc:
        print(f"PDF MCP startup failed: {exc}", file=sys.stderr, flush=True)
        return 2

    for raw_line in sys.stdin:
        if not raw_line.strip():
            continue
        request_id: Any = None
        try:
            request = json.loads(raw_line)
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            request_id = request.get("id")
            method = request.get("method")
            if method == "initialize":
                params = request.get("params")
                requested_protocol = (
                    params.get("protocolVersion") if isinstance(params, dict) else None
                )
                result = {
                    "protocolVersion": requested_protocol or "2025-06-18",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "instructions": SERVER_INSTRUCTIONS,
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": _tool_definitions(reader)}
            elif method == "tools/call":
                result = _tool_call(reader, request.get("params"))
            elif isinstance(method, str) and method.startswith("notifications/"):
                continue
            else:
                response = _error_response(request_id, -32601, "method not found")
                _emit_transport_message(response)
                continue
            if request_id is not None:
                _emit_transport_message(_response(request_id, result))
        except (ValueError, TypeError, ToolError) as exc:
            if request_id is not None:
                _emit_transport_message(
                    _error_response(request_id, -32602, str(exc))
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
