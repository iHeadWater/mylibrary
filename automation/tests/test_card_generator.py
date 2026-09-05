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

from hydro_platform.card_generators.codex_cli import CodexCliAdapter
from hydro_platform.cli import main
from hydro_platform.config import CardGeneratorConfig


def generator_config() -> CardGeneratorConfig:
    return CardGeneratorConfig(
        adapter="codex_cli",
        executable="codex",
        auth_mode="chatgpt_account",
        preflight_timeout_seconds=10,
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


if __name__ == "__main__":
    unittest.main()
