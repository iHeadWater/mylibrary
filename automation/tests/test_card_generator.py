from __future__ import annotations

import io
import json
import subprocess
import sys
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
from hydro_platform.config import CardGeneratorConfig


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


class GeneratorPreflightCliTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
