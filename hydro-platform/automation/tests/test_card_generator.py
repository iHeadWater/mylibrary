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


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from hydro_platform.card_generators.codex_cli import (
    SMOKE_TEST_EXPECTED_TEXT,
    SMOKE_TEST_PROMPT,
    CodexCliAdapter,
)
from hydro_platform.cli import main
from hydro_platform.config import CardGeneratorConfig, PdfReaderConfig


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
        pdf_reader=PdfReaderConfig(
            adapter="project_mcp",
            server_name="hydro_pdf_reader",
            python_executable=None,
            server_file=SOURCE_ROOT / "hydro_platform" / "pdf_reader_mcp.py",
            pdfinfo_executable="pdfinfo",
            pdftotext_executable="pdftotext",
            pdftoppm_executable="pdftoppm",
            render_dpi=120,
            max_pages_per_call=4,
            output_token_limit=60000,
            startup_timeout_seconds=15,
            tool_timeout_seconds=120,
        ),
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


class CodexCliAdapterTests(unittest.TestCase):
    def test_passes_for_chatgpt_login_without_invoking_model(self) -> None:
        executable = "C:/Program Files/OpenAI/codex.exe"
        runner = SequenceRunner(
            [
                command_result([executable, "--version"], stdout="codex-cli 0.149.1\n"),
                command_result(
                    [executable, "login", "status"],
                    stdout="Logged in using ChatGPT\n",
                ),
            ]
        )
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=runner,
        )

        result = adapter.preflight()

        self.assertTrue(result["ok"])
        self.assertEqual(result["cli_version"], "codex-cli 0.149.1")
        self.assertEqual(result["configured_auth_mode"], "chatgpt_account")
        self.assertEqual(result["detected_auth_mode"], "chatgpt_account")
        self.assertEqual(
            runner.calls,
            [
                ([executable, "--version"], 10),
                ([executable, "login", "status"], 10),
            ],
        )
        self.assertFalse(any("exec" in command for command, _ in runner.calls))

    def test_reports_missing_executable_without_running_command(self) -> None:
        runner = SequenceRunner([])
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: None,
            runner=runner,
        )

        result = adapter.preflight()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_CLI_NOT_FOUND")
        self.assertEqual(runner.calls, [])

    def test_reports_version_timeout(self) -> None:
        executable = "codex.exe"
        timeout = subprocess.TimeoutExpired([executable, "--version"], 10)
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner([timeout]),
        )

        result = adapter.preflight()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_CLI_TIMEOUT")

    def test_reports_invalid_version_result(self) -> None:
        executable = "codex.exe"
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [command_result([executable, "--version"], returncode=1)]
            ),
        )

        result = adapter.preflight()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_CLI_UNAVAILABLE")

    def test_reports_not_logged_in(self) -> None:
        executable = "codex.exe"
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        returncode=1,
                        stderr="Not logged in",
                    ),
                ]
            ),
        )

        result = adapter.preflight()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_NOT_LOGGED_IN")

    def test_rejects_api_key_login(self) -> None:
        executable = "codex.exe"
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using an API key",
                    ),
                ]
            ),
        )

        result = adapter.preflight()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_AUTH_MODE_MISMATCH")
        self.assertEqual(result["detected_auth_mode"], "api_key")

    def test_rejects_unverifiable_successful_login_output(self) -> None:
        executable = "codex.exe"
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Authenticated",
                    ),
                ]
            ),
        )

        result = adapter.preflight()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_AUTH_MODE_UNKNOWN")
        self.assertEqual(result["detected_auth_mode"], "unknown")

    def test_does_not_echo_raw_authentication_output(self) -> None:
        executable = "codex.exe"
        secret_marker = "secret-marker-that-must-not-be-returned"
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout=f"Logged in using ChatGPT {secret_marker}",
                    ),
                ]
            ),
        )

        result = adapter.preflight()

        self.assertTrue(result["ok"])
        self.assertNotIn(secret_marker, json.dumps(result))


class CodexCliSmokeTestTests(unittest.TestCase):
    def test_runs_ephemeral_read_only_probe_and_parses_usage(self) -> None:
        executable = "C:/Program Files/OpenAI/codex.exe"
        project_directory = Path.cwd().resolve()
        runner = SequenceRunner(
            [
                command_result([executable, "--version"], stdout="codex-cli 0.149.1"),
                command_result(
                    [executable, "login", "status"],
                    stdout="Logged in using ChatGPT",
                ),
                command_result([executable, "exec"], stdout=smoke_jsonl()),
            ]
        )
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=runner,
        )

        result = adapter.smoke_test()

        self.assertTrue(result["ok"])
        self.assertTrue(result["model_invoked"])
        self.assertEqual(result["model_source"], "codex_default")
        self.assertEqual(result["reasoning_effort_source"], "model_default")
        self.assertEqual(result["usage"]["output_tokens"], 5)
        command, timeout = runner.calls[2]
        self.assertEqual(command[:2], [executable, "exec"])
        self.assertEqual(command[-1], SMOKE_TEST_PROMPT)
        self.assertEqual(timeout, 120)
        self.assertIn("--json", command)
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        isolated_workspace = Path(command[command.index("--cd") + 1])
        self.assertNotEqual(isolated_workspace, project_directory)
        self.assertTrue(isolated_workspace.name.startswith("hydro-generator-smoke-"))
        self.assertFalse(isolated_workspace.exists())
        self.assertTrue(result["isolated_workspace"])
        self.assertNotIn("--model", command)
        self.assertNotIn("--config", command)
        self.assertNotIn("--output-last-message", command)

    def test_adds_configured_model_to_probe_command(self) -> None:
        executable = "codex.exe"
        runner = SequenceRunner(
            [
                command_result([executable, "--version"], stdout="codex-cli 1.0"),
                command_result(
                    [executable, "login", "status"],
                    stdout="Logged in using ChatGPT",
                ),
                command_result([executable, "exec"], stdout=smoke_jsonl()),
            ]
        )
        adapter = CodexCliAdapter(
            generator_config(model="gpt-test-model"),
            executable_finder=lambda _: executable,
            runner=runner,
        )

        result = adapter.smoke_test()

        self.assertTrue(result["ok"])
        self.assertEqual(result["configured_model"], "gpt-test-model")
        self.assertEqual(result["model_source"], "configured")
        command, _ = runner.calls[2]
        self.assertEqual(
            command[command.index("--model") + 1],
            "gpt-test-model",
        )

    def test_adds_configured_reasoning_effort_to_probe_command(self) -> None:
        executable = "codex.exe"
        runner = SequenceRunner(
            [
                command_result([executable, "--version"], stdout="codex-cli 1.0"),
                command_result(
                    [executable, "login", "status"],
                    stdout="Logged in using ChatGPT",
                ),
                command_result([executable, "exec"], stdout=smoke_jsonl()),
            ]
        )
        adapter = CodexCliAdapter(
            generator_config(reasoning_effort="high"),
            executable_finder=lambda _: executable,
            runner=runner,
        )

        result = adapter.smoke_test()

        self.assertTrue(result["ok"])
        self.assertEqual(result["configured_reasoning_effort"], "high")
        self.assertEqual(result["reasoning_effort_source"], "configured")
        command, _ = runner.calls[2]
        self.assertEqual(
            command[command.index("--config") + 1],
            'model_reasoning_effort="high"',
        )

    def test_does_not_invoke_model_when_preflight_fails(self) -> None:
        runner = SequenceRunner([])
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: None,
            runner=runner,
        )

        result = adapter.smoke_test()

        self.assertFalse(result["ok"])
        self.assertFalse(result["model_invoked"])
        self.assertEqual(result["error"]["code"], "CODEX_CLI_NOT_FOUND")
        self.assertEqual(runner.calls, [])

    def test_reports_smoke_test_timeout(self) -> None:
        executable = "codex.exe"
        timeout = subprocess.TimeoutExpired([executable, "exec"], 120)
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using ChatGPT",
                    ),
                    timeout,
                ]
            ),
        )

        result = adapter.smoke_test()

        self.assertFalse(result["ok"])
        self.assertTrue(result["model_invoked"])
        self.assertEqual(result["error"]["code"], "CODEX_SMOKE_TIMEOUT")

    def test_classifies_common_exec_failures(self) -> None:
        cases = (
            ("invalid_json_schema for response_format", "CODEX_OUTPUT_SCHEMA_INVALID"),
            ("context_length_exceeded", "CODEX_CONTEXT_LIMIT"),
            (
                "required MCP servers failed to initialize: hydro_pdf_reader: "
                "handshaking with MCP server failed: connection closed",
                "PDF_READER_INITIALIZATION_FAILED",
            ),
            ("stream_closed by server_error", "CODEX_SERVICE_UNAVAILABLE"),
            ("sandbox denied: access is denied", "CODEX_EXEC_PERMISSION_DENIED"),
            ("rate limit exceeded", "CODEX_RATE_LIMITED"),
            ("usage limit reached", "CODEX_USAGE_LIMIT"),
            ("401 unauthorized", "CODEX_NOT_LOGGED_IN"),
            (
                "unsupported model_reasoning_effort for this model",
                "CODEX_REASONING_EFFORT_UNAVAILABLE",
            ),
            ("model not found", "CODEX_MODEL_UNAVAILABLE"),
            ("unexpected backend failure", "CODEX_EXEC_FAILED"),
        )
        for raw_error, expected_code in cases:
            with self.subTest(raw_error=raw_error):
                executable = "codex.exe"
                adapter = CodexCliAdapter(
                    generator_config(),
                    executable_finder=lambda _: executable,
                    runner=SequenceRunner(
                        [
                            command_result(
                                [executable, "--version"],
                                stdout="codex-cli 1.0",
                            ),
                            command_result(
                                [executable, "login", "status"],
                                stdout="Logged in using ChatGPT",
                            ),
                            command_result(
                                [executable, "exec"],
                                returncode=1,
                                stderr=raw_error,
                            ),
                        ]
                    ),
                )

                result = adapter.smoke_test()

                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], expected_code)

    def test_rejects_invalid_jsonl_protocol(self) -> None:
        executable = "codex.exe"
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using ChatGPT",
                    ),
                    command_result([executable, "exec"], stdout="not-json"),
                ]
            ),
        )

        result = adapter.smoke_test()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_EXEC_PROTOCOL_ERROR")

    def test_rejects_tool_activity_during_probe(self) -> None:
        executable = "codex.exe"
        unexpected_event = {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": "pwd"},
        }
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using ChatGPT",
                    ),
                    command_result(
                        [executable, "exec"],
                        stdout=smoke_jsonl(extra_events=[unexpected_event]),
                    ),
                ]
            ),
        )

        result = adapter.smoke_test()

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"]["code"],
            "CODEX_SMOKE_UNEXPECTED_ACTIVITY",
        )
        self.assertEqual(result["unexpected_item_types"], ["command_execution"])

    def test_rejects_unexpected_model_message(self) -> None:
        executable = "codex.exe"
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using ChatGPT",
                    ),
                    command_result(
                        [executable, "exec"],
                        stdout=smoke_jsonl(message="unexpected response"),
                    ),
                ]
            ),
        )

        result = adapter.smoke_test()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_SMOKE_OUTPUT_INVALID")

    def test_does_not_echo_raw_exec_failure(self) -> None:
        executable = "codex.exe"
        secret_marker = "raw-error-secret-marker"
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using ChatGPT",
                    ),
                    command_result(
                        [executable, "exec"],
                        returncode=1,
                        stderr=f"backend failed {secret_marker}",
                    ),
                ]
            ),
        )

        result = adapter.smoke_test()

        self.assertFalse(result["ok"])
        self.assertNotIn(secret_marker, json.dumps(result))


class CodexCliGenerationTests(unittest.TestCase):
    def test_generation_uses_stdin_schema_isolated_workspace_and_bound_pdf_mcp(self) -> None:
        executable = "codex.exe"
        output = {
            "schema_version": 2,
            "source_read_status": "FULL_PDF_REVIEWED",
            "source_page_count": 12,
            "visual_content_status": "REVIEWED",
            "source_read_evidence": "共 12 页；已检查图 1。",
            "template_id": "original-research",
            "classification_confidence": 0.9,
            "classification_reason": "包含原创方法与结果",
            "card_body_markdown": "# 卡片\n",
        }
        prompt_runner = PromptSequenceRunner(
            [
                command_result(
                    [executable, "exec"],
                    stdout=smoke_jsonl(message=json.dumps(output)),
                )
            ]
        )
        adapter = CodexCliAdapter(
            generator_config(model="gpt-default", reasoning_effort="low"),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using ChatGPT",
                    ),
                ]
            ),
            prompt_runner=prompt_runner,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_directory = root / "zotero-item"
            pdf_directory.mkdir()
            source_pdf = pdf_directory / "paper.pdf"
            source_pdf.write_bytes(b"%PDF-1.7\nfixture")
            schema = root / "output.schema.json"
            schema.write_text("{}", encoding="utf-8")

            result = adapter.generate(
                "long prompt",
                working_directory=pdf_directory,
                source_pdf_path=source_pdf,
                zotero_parent_key="CEXH4PQA",
                output_schema_path=schema,
                model="gpt-role",
                reasoning_effort="xhigh",
                timeout_seconds=321,
                run_label="fact_extractor_a",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["output"], output)
        command, prompt, timeout, environment = prompt_runner.calls[0]
        self.assertEqual(prompt, "long prompt")
        self.assertEqual(timeout, 321)
        self.assertEqual(command[-1], "-")
        self.assertIn("--output-schema", command)
        isolated_workspace = Path(command[command.index("--cd") + 1])
        self.assertNotEqual(isolated_workspace, pdf_directory.resolve())
        self.assertFalse(isolated_workspace.exists())
        self.assertIn("read-only", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn(
            'mcp_servers.hydro_pdf_reader.required=true',
            command,
        )
        self.assertIn('approval_policy="never"', command)
        self.assertIn(
            'mcp_servers.hydro_pdf_reader.enabled_tools=["read_full_source_pdf"]',
            command,
        )
        self.assertIn(
            'mcp_servers.hydro_pdf_reader.default_tools_approval_mode="approve"',
            command,
        )
        self.assertIn(
            "mcp_servers.hydro_pdf_reader.tools.read_full_source_pdf."
            "output_token_limit=60000",
            command,
        )
        mcp_environment_overrides = [
            value
            for value in command
            if value.startswith("mcp_servers.hydro_pdf_reader.env=")
        ]
        self.assertEqual(len(mcp_environment_overrides), 1)
        self.assertIn("HYDRO_SOURCE_PDF=", mcp_environment_overrides[0])
        self.assertIn("HYDRO_PDF_RECEIPT=", mcp_environment_overrides[0])
        self.assertEqual(environment["HYDRO_SOURCE_PDF"], str(source_pdf.resolve()))
        self.assertEqual(environment["HYDRO_ZOTERO_PARENT_KEY"], "CEXH4PQA")
        self.assertEqual(command[command.index("--model") + 1], "gpt-role")
        self.assertIn('model_reasoning_effort="xhigh"', command)
        self.assertEqual(result["run_label"], "fact_extractor_a")
        self.assertEqual(
            result["source_access"],
            {
                "verified": True,
                "method": "bound_local_pdf_mcp",
                "server_name": "hydro_pdf_reader",
                "receipt_schema_version": 1,
                "page_count": 12,
                "pages_served": 12,
                "visual_pages_served": 12,
            },
        )

    def test_generation_rejects_shell_activity_even_when_pdf_receipt_exists(self) -> None:
        executable = "codex.exe"
        output = {
            "schema_version": 2,
            "source_read_status": "FULL_PDF_REVIEWED",
            "source_page_count": 12,
            "visual_content_status": "REVIEWED",
            "source_read_evidence": "共 12 页；已检查图 1。",
            "template_id": "original-research",
            "classification_confidence": 0.9,
            "classification_reason": "原创研究",
            "card_body_markdown": "# 卡片\n",
        }
        command_event = {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": "pdftotext paper.pdf -"},
        }
        mcp_event = {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "zotero",
                "tool": "read",
                "arguments": {"file": "paper.pdf"},
            },
        }
        prompt_runner = PromptSequenceRunner(
            [
                command_result(
                    [executable, "exec"],
                    stdout=smoke_jsonl(
                        message=json.dumps(output),
                        extra_events=[command_event, mcp_event],
                    ),
                )
            ]
        )
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using ChatGPT",
                    ),
                ]
            ),
            prompt_runner=prompt_runner,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "paper.pdf"
            source_pdf.write_bytes(b"%PDF-1.7\nfixture")
            schema = root / "schema.json"
            schema.write_text("{}", encoding="utf-8")
            result = adapter.generate(
                "prompt",
                working_directory=root,
                source_pdf_path=source_pdf,
                zotero_parent_key="CEXH4PQA",
                output_schema_path=schema,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"]["code"],
            "CODEX_GENERATION_UNEXPECTED_ACTIVITY",
        )

    def test_generation_rejects_page_count_mismatch_with_pdf_receipt(self) -> None:
        executable = "codex.exe"
        output = {
            "schema_version": 2,
            "source_read_status": "FULL_PDF_REVIEWED",
            "source_page_count": 12,
            "visual_content_status": "REVIEWED",
            "source_read_evidence": "共 12 页；已检查图 1。",
            "template_id": "original-research",
            "classification_confidence": 0.9,
            "classification_reason": "原创研究",
            "card_body_markdown": "# 卡片\n",
        }
        prompt_runner = PromptSequenceRunner(
            [
                command_result(
                    [executable, "exec"],
                    stdout=smoke_jsonl(message=json.dumps(output)),
                )
            ],
            receipt_page_count=11,
        )
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using ChatGPT",
                    ),
                ]
            ),
            prompt_runner=prompt_runner,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "paper.pdf"
            source_pdf.write_bytes(b"%PDF-1.7\nfixture")
            schema = root / "schema.json"
            schema.write_text("{}", encoding="utf-8")

            result = adapter.generate(
                "prompt",
                working_directory=root,
                source_pdf_path=source_pdf,
                zotero_parent_key="CEXH4PQA",
                output_schema_path=schema,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"]["code"],
            "CODEX_PDF_PAGE_COUNT_MISMATCH",
        )

    def test_generation_rejects_output_without_pdf_reader_receipt(self) -> None:
        executable = "codex.exe"
        output = {
            "schema_version": 2,
            "source_read_status": "FULL_PDF_REVIEWED",
            "source_page_count": 12,
            "visual_content_status": "REVIEWED",
            "source_read_evidence": "共 12 页；已检查图 1。",
            "template_id": "original-research",
            "classification_confidence": 0.9,
            "classification_reason": "原创研究",
            "card_body_markdown": "# 卡片\n",
        }
        prompt_runner = PromptSequenceRunner(
            [
                command_result(
                    [executable, "exec"],
                    stdout=smoke_jsonl(message=json.dumps(output)),
                )
            ],
            write_receipt=False,
        )
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using ChatGPT",
                    ),
                ]
            ),
            prompt_runner=prompt_runner,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "paper.pdf"
            source_pdf.write_bytes(b"%PDF-1.7\nfixture")
            schema = root / "schema.json"
            schema.write_text("{}", encoding="utf-8")

            result = adapter.generate(
                "prompt",
                working_directory=root,
                source_pdf_path=source_pdf,
                zotero_parent_key="CEXH4PQA",
                output_schema_path=schema,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_PDF_NOT_ACCESSED")
        self.assertEqual(result["diagnostic"]["stage"], "pdf_access_verification")
        self.assertEqual(result["diagnostic"]["mcp_event_count"], 0)
        self.assertEqual(
            result["diagnostic"]["model_claim"],
            {
                "source_read_status": "FULL_PDF_REVIEWED",
                "source_page_count": 12,
                "visual_content_status": "REVIEWED",
            },
        )

    def test_generation_rejects_file_change_activity(self) -> None:
        executable = "codex.exe"
        file_change = {
            "type": "item.completed",
            "item": {"type": "file_change", "path": "card.md"},
        }
        prompt_runner = PromptSequenceRunner(
            [
                command_result(
                    [executable, "exec"],
                    stdout=smoke_jsonl(
                        message="{}",
                        extra_events=[file_change],
                    ),
                )
            ]
        )
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using ChatGPT",
                    ),
                ]
            ),
            prompt_runner=prompt_runner,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "paper.pdf"
            source_pdf.write_bytes(b"%PDF-1.7\nfixture")
            schema = root / "schema.json"
            schema.write_text("{}", encoding="utf-8")
            result = adapter.generate(
                "prompt",
                working_directory=root,
                source_pdf_path=source_pdf,
                zotero_parent_key="CEXH4PQA",
                output_schema_path=schema,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"]["code"],
            "CODEX_GENERATION_UNEXPECTED_ACTIVITY",
        )

    def test_generation_timeout_is_bounded(self) -> None:
        executable = "codex.exe"
        prompt_runner = PromptSequenceRunner(
            [subprocess.TimeoutExpired([executable, "exec"], 900)]
        )
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using ChatGPT",
                    ),
                ]
            ),
            prompt_runner=prompt_runner,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "paper.pdf"
            source_pdf.write_bytes(b"%PDF-1.7\nfixture")
            schema = root / "schema.json"
            schema.write_text("{}", encoding="utf-8")
            result = adapter.generate(
                "prompt",
                working_directory=root,
                source_pdf_path=source_pdf,
                zotero_parent_key="CEXH4PQA",
                output_schema_path=schema,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_GENERATION_TIMEOUT")

    def test_generation_failure_returns_only_safe_structured_diagnostic(self) -> None:
        executable = "codex.exe"
        secret_marker = "sk-raw-error-secret-marker"
        prompt_runner = PromptSequenceRunner(
            [
                command_result(
                    [executable, "exec"],
                    returncode=1,
                    stderr=(
                        "invalid_json_schema for response_format "
                        f"api_key={secret_marker}"
                    ),
                )
            ]
        )
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using ChatGPT",
                    ),
                ]
            ),
            prompt_runner=prompt_runner,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "paper.pdf"
            source_pdf.write_bytes(b"%PDF-1.7\nfixture")
            schema = root / "schema.json"
            schema.write_text("{}", encoding="utf-8")
            result = adapter.generate(
                "prompt",
                working_directory=root,
                source_pdf_path=source_pdf,
                zotero_parent_key="CEXH4PQA",
                output_schema_path=schema,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_OUTPUT_SCHEMA_INVALID")
        self.assertEqual(result["diagnostic"]["stage"], "codex_exec")
        self.assertEqual(result["diagnostic"]["exit_code"], 1)
        self.assertEqual(
            result["diagnostic"]["category"],
            "CODEX_OUTPUT_SCHEMA_INVALID",
        )
        self.assertEqual(result["diagnostic"]["source"], "codex_stderr")
        self.assertIn("invalid_json_schema", result["diagnostic"]["summary"])
        self.assertNotIn(secret_marker, json.dumps(result))

    def test_generation_diagnostic_ignores_agent_message_content(self) -> None:
        executable = "codex.exe"
        private_model_text = "private-generated-card-body"
        stdout = "\n".join(
            json.dumps(event)
            for event in (
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": private_model_text},
                },
                {
                    "type": "turn.failed",
                    "error": {
                        "type": "server_error",
                        "code": "stream_closed",
                        "message": "connection closed before completion",
                    },
                },
            )
        )
        prompt_runner = PromptSequenceRunner(
            [command_result([executable, "exec"], returncode=1, stdout=stdout)]
        )
        adapter = CodexCliAdapter(
            generator_config(),
            executable_finder=lambda _: executable,
            runner=SequenceRunner(
                [
                    command_result([executable, "--version"], stdout="codex-cli 1.0"),
                    command_result(
                        [executable, "login", "status"],
                        stdout="Logged in using ChatGPT",
                    ),
                ]
            ),
            prompt_runner=prompt_runner,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "paper.pdf"
            source_pdf.write_bytes(b"%PDF-1.7\nfixture")
            schema = root / "schema.json"
            schema.write_text("{}", encoding="utf-8")
            result = adapter.generate(
                "prompt",
                working_directory=root,
                source_pdf_path=source_pdf,
                zotero_parent_key="CEXH4PQA",
                output_schema_path=schema,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CODEX_SERVICE_UNAVAILABLE")
        self.assertEqual(result["diagnostic"]["source"], "codex_error_event")
        self.assertIn("stream_closed", result["diagnostic"]["summary"])
        self.assertNotIn(private_model_text, json.dumps(result))


class GeneratorPreflightCliTests(unittest.TestCase):
    @staticmethod
    def _generation_app_config() -> SimpleNamespace:
        paths = SimpleNamespace(
            tasks_file=Path("tasks.json"),
            lock_file=Path("worker.lock"),
            evidence_packs_dir=Path("evidence-packs"),
            card_trials_dir=Path("card-trials"),
            evidence_card_templates_dir=Path("templates"),
            evidence_card_template_catalog_file=Path("catalog.json"),
            evidence_card_generation_prompt_file=Path("prompt.md"),
            card_generation_output_schema_file=Path("schema.json"),
        )
        return SimpleNamespace(
            zotero=SimpleNamespace(group_id=42),
            pdf_gate=SimpleNamespace(),
            tasks=SimpleNamespace(),
            paths=paths,
            card_generator=generator_config(),
        )

    def test_generator_preflight_command_emits_adapter_result(self) -> None:
        expected = {
            "schema_version": 1,
            "ok": True,
            "component": "card_generator",
            "adapter": "codex_cli",
            "cli_version": "codex-cli 1.0",
            "configured_auth_mode": "chatgpt_account",
            "detected_auth_mode": "chatgpt_account",
            "resolved_executable": "codex.exe",
        }
        adapter = Mock()
        adapter.preflight.return_value = expected
        app_config = SimpleNamespace(card_generator=generator_config())
        output = io.StringIO()

        with (
            patch("hydro_platform.cli.load_config", return_value=app_config),
            patch(
                "hydro_platform.cli.build_card_generator_adapter",
                return_value=adapter,
            ) as build_adapter,
            redirect_stdout(output),
        ):
            exit_code = main(
                ["generator-preflight", "--config", "unused.json", "--json"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue()), expected)
        build_adapter.assert_called_once_with(app_config.card_generator)
        adapter.preflight.assert_called_once_with()

    def test_generator_smoke_test_command_emits_adapter_result(self) -> None:
        expected = {
            "schema_version": 1,
            "ok": True,
            "component": "card_generator",
            "operation": "smoke_test",
        }
        adapter = Mock()
        adapter.smoke_test.return_value = expected
        app_config = SimpleNamespace(
            card_generator=generator_config(),
        )
        output = io.StringIO()

        with (
            patch("hydro_platform.cli.load_config", return_value=app_config),
            patch(
                "hydro_platform.cli.build_card_generator_adapter",
                return_value=adapter,
            ) as build_adapter,
            redirect_stdout(output),
        ):
            exit_code = main(
                ["generator-smoke-test", "--config", "unused.json", "--json"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue()), expected)
        build_adapter.assert_called_once_with(app_config.card_generator)
        adapter.smoke_test.assert_called_once_with()

    def test_trial_command_does_not_require_quality_retry_argument(self) -> None:
        app_config = self._generation_app_config()
        result = {
            "schema_version": 1,
            "ok": True,
            "operation": "evidence_generate_trial",
            "parent_key": "CEXH4PQA",
            "quality_status": "VALIDATED",
            "template_id": "original-research",
            "trial_path": "card-trials/run",
        }
        output = io.StringIO()

        with (
            patch("hydro_platform.cli.load_config", return_value=app_config),
            patch("hydro_platform.cli.preflight", return_value={"ok": True}),
            patch("hydro_platform.cli.build_card_generator_adapter", return_value=Mock()),
            patch(
                "hydro_platform.cli.generate_evidence_card_trial",
                return_value=result,
            ) as generate_trial,
            redirect_stdout(output),
        ):
            exit_code = main(
                [
                    "evidence-generate-trial",
                    "--config",
                    "unused.json",
                    "--item-key",
                    "CEXH4PQA",
                    "--json",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue()), result)
        self.assertNotIn("retry_quality_failed", generate_trial.call_args.kwargs)

    def test_generation_command_passes_explicit_quality_retry(self) -> None:
        app_config = self._generation_app_config()
        result = {
            "schema_version": 1,
            "ok": True,
            "operation": "evidence_generate",
            "action": "SKIPPED_EXISTING_CARD",
            "parent_key": "CEXH4PQA",
            "card_status": "ROUGH",
            "task_state": "COMPLETED",
            "card_path": "evidence-packs/card.md",
        }
        output = io.StringIO()

        with (
            patch("hydro_platform.cli.load_config", return_value=app_config),
            patch("hydro_platform.cli.preflight", return_value={"ok": True}),
            patch("hydro_platform.cli.build_card_generator_adapter", return_value=Mock()),
            patch(
                "hydro_platform.cli.generate_evidence_card",
                return_value=result,
            ) as generate_card,
            redirect_stdout(output),
        ):
            exit_code = main(
                [
                    "evidence-generate",
                    "--config",
                    "unused.json",
                    "--item-key",
                    "CEXH4PQA",
                    "--retry-quality-failed",
                    "--json",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue()), result)
        self.assertTrue(generate_card.call_args.kwargs["retry_quality_failed"])


if __name__ == "__main__":
    unittest.main()
