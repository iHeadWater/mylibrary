from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hydrolitagent.cards.adapters.runners.codex import (
    SMOKE_TEST_EXPECTED_TEXT,
    SMOKE_TEST_PROMPT,
)
from hydrolitagent.cards.cli import main
from hydrolitagent.cards.config import CardGeneratorConfig

def generator_config(
    *,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> CardGeneratorConfig:
    return CardGeneratorConfig(
        adapter="codex_cli",
        executable="codex",
        auth_mode="chatgpt_account",
        preflight_timeout_seconds=10,
        model=model,
        reasoning_effort=reasoning_effort,
        smoke_test_timeout_seconds=120,
        generation_timeout_seconds=900,
    )

def command_result(
    args: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=args,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )

def smoke_jsonl(
    *,
    message: str = SMOKE_TEST_EXPECTED_TEXT,
    extra_events: list[dict[str, object]] | None = None,
) -> str:
    events: list[dict[str, object]] = [
        {"type": "thread.started", "thread_id": "test-thread"},
        {"type": "turn.started"},
        *(extra_events or []),
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": message},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 21,
                "cached_input_tokens": 0,
                "output_tokens": 5,
                "reasoning_output_tokens": 0,
            },
        },
    ]
    return "\n".join(json.dumps(event) for event in events)

class SequenceRunner:
    def __init__(
        self,
        responses: list[subprocess.CompletedProcess[str] | BaseException],
    ):
        self.responses = iter(responses)
        self.calls: list[tuple[list[str], float]] = []

    def __call__(
        self,
        command: list[str] | tuple[str, ...],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        normalized = list(command)
        self.calls.append((normalized, timeout_seconds))
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response

class PromptSequenceRunner:
    def __init__(
        self,
        responses: list[subprocess.CompletedProcess[str] | BaseException],
        *,
        write_receipt: bool = True,
        receipt_page_count: int = 12,
    ):
        self.responses = iter(responses)
        self.write_receipt = write_receipt
        self.receipt_page_count = receipt_page_count
        self.calls: list[tuple[list[str], str, float, dict[str, str]]] = []

    def __call__(
        self,
        command: list[str] | tuple[str, ...],
        prompt: str,
        timeout_seconds: float,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        normalized = list(command)
        normalized_environment = dict(environment or {})
        self.calls.append(
            (normalized, prompt, timeout_seconds, normalized_environment)
        )
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        if self.write_receipt and environment is not None and response.returncode == 0:
            receipt_path = Path(environment["HYDRO_PDF_RECEIPT"])
            receipt_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "reader": "hydro-platform-pdf-reader",
                        "source_sha256": environment["HYDRO_SOURCE_PDF_SHA256"],
                        "page_count": self.receipt_page_count,
                        "inspected": True,
                        "pages": {
                            str(page): {"image_delivered": True}
                            for page in range(1, self.receipt_page_count + 1)
                        },
                    }
                ),
                encoding="utf-8",
            )
        return response

if __name__ == "__main__":
    unittest.main()
