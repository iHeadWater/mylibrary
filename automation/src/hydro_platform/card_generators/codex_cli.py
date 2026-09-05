from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from hydro_platform.config import CardGeneratorConfig


CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]
ExecutableFinder = Callable[[str], str | None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _run_command(
    command: Sequence[str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(
        part.strip()
        for part in (result.stdout or "", result.stderr or "")
        if part and part.strip()
    )


class CodexCliAdapter:
    """Preflight for the local Codex CLI; model execution is intentionally absent."""

    def __init__(
        self,
        config: CardGeneratorConfig,
        *,
        executable_finder: ExecutableFinder = shutil.which,
        runner: CommandRunner = _run_command,
    ):
        self.config = config
        self._executable_finder = executable_finder
        self._runner = runner

    def _failure(
        self,
        checks: list[dict[str, str]],
        code: str,
        message: str,
        *,
        resolved_executable: str | None,
        cli_version: str | None = None,
        detected_auth_mode: str | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": False,
            "component": "card_generator",
            "checked_at": _now(),
            "adapter": self.config.adapter,
            "configured_executable": self.config.executable,
            "resolved_executable": resolved_executable,
            "configured_auth_mode": self.config.auth_mode,
            "detected_auth_mode": detected_auth_mode,
            "cli_version": cli_version,
            "checks": checks,
            "error": {"code": code, "message": message},
        }

    def preflight(self) -> dict[str, Any]:
        checks: list[dict[str, str]] = []
        executable = self._executable_finder(self.config.executable)
        if executable is None:
            checks.append(
                _check(
                    "executable",
                    "fail",
                    f"找不到配置的 Codex CLI：{self.config.executable}",
                )
            )
            return self._failure(
                checks,
                "CODEX_CLI_NOT_FOUND",
                "找不到 Codex CLI；请安装后检查 card_generator.executable",
                resolved_executable=None,
            )

        checks.append(_check("executable", "pass", "已找到 Codex CLI 可执行程序"))
        try:
            version_result = self._runner(
                [executable, "--version"],
                self.config.preflight_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            checks.append(_check("version", "fail", "Codex CLI 版本检查超时"))
            return self._failure(
                checks,
                "CODEX_CLI_TIMEOUT",
                "Codex CLI 版本检查超时",
                resolved_executable=executable,
            )
        except (OSError, subprocess.SubprocessError):
            checks.append(_check("version", "fail", "Codex CLI 无法启动"))
            return self._failure(
                checks,
                "CODEX_CLI_UNAVAILABLE",
                "Codex CLI 已找到但无法启动",
                resolved_executable=executable,
            )

        version_output = _combined_output(version_result)
        if version_result.returncode != 0 or not version_output:
            checks.append(_check("version", "fail", "Codex CLI 未返回有效版本"))
            return self._failure(
                checks,
                "CODEX_CLI_UNAVAILABLE",
                "Codex CLI 版本检查失败",
                resolved_executable=executable,
            )

        cli_version = version_output.splitlines()[0].strip()
        checks.append(_check("version", "pass", f"Codex CLI 可运行：{cli_version}"))

        try:
            auth_result = self._runner(
                [executable, "login", "status"],
                self.config.preflight_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            checks.append(_check("authentication", "fail", "Codex 登录状态检查超时"))
            return self._failure(
                checks,
                "CODEX_CLI_TIMEOUT",
                "Codex 登录状态检查超时",
                resolved_executable=executable,
                cli_version=cli_version,
            )
        except (OSError, subprocess.SubprocessError):
            checks.append(_check("authentication", "fail", "无法检查 Codex 登录状态"))
            return self._failure(
                checks,
                "CODEX_CLI_UNAVAILABLE",
                "Codex CLI 无法执行登录状态检查",
                resolved_executable=executable,
                cli_version=cli_version,
            )

        auth_output = _combined_output(auth_result)
        normalized_auth = auth_output.casefold()
        if auth_result.returncode != 0:
            checks.append(_check("authentication", "fail", "Codex CLI 当前未登录"))
            return self._failure(
                checks,
                "CODEX_NOT_LOGGED_IN",
                "Codex CLI 当前未登录；请先使用 ChatGPT 账号登录",
                resolved_executable=executable,
                cli_version=cli_version,
            )

        if any(
            marker in normalized_auth
            for marker in ("api key", "api-key", "api_key")
        ):
            checks.append(
                _check(
                    "authentication",
                    "fail",
                    "检测到 API Key 登录，与当前 ChatGPT 账号认证要求不一致",
                )
            )
            return self._failure(
                checks,
                "CODEX_AUTH_MODE_MISMATCH",
                "当前要求使用 ChatGPT 账号认证，但 Codex CLI 报告为 API Key 登录",
                resolved_executable=executable,
                cli_version=cli_version,
                detected_auth_mode="api_key",
            )

        if "chatgpt" not in normalized_auth:
            checks.append(
                _check(
                    "authentication",
                    "fail",
                    "Codex CLI 已返回成功，但无法确认是否使用 ChatGPT 账号",
                )
            )
            return self._failure(
                checks,
                "CODEX_AUTH_MODE_UNKNOWN",
                "无法从 Codex CLI 输出确认 ChatGPT 账号登录方式",
                resolved_executable=executable,
                cli_version=cli_version,
                detected_auth_mode="unknown",
            )

        checks.append(
            _check(
                "authentication",
                "pass",
                "已确认 Codex CLI 使用 ChatGPT 账号登录",
            )
        )
        return {
            "schema_version": 1,
            "ok": True,
            "component": "card_generator",
            "checked_at": _now(),
            "adapter": self.config.adapter,
            "configured_executable": self.config.executable,
            "resolved_executable": executable,
            "configured_auth_mode": self.config.auth_mode,
            "detected_auth_mode": "chatgpt_account",
            "cli_version": cli_version,
            "checks": checks,
        }
