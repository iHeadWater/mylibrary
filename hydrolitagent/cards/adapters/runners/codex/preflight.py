"""Executable, version, login and PDF-reader dependency checks for Codex CLI.

Stage 1.6 moved this out of ``card_generators/codex_cli.py`` without changing
the reported checks, codes or messages. The adapter instance is passed in
because the checks use its configured runner/finder and its ``_failure``
record builder; no global state is read.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any

from hydrolitagent.cards.adapters.runners.codex.common import _check, _now
from hydrolitagent.cards.adapters.runners.codex.events import _combined_output
from hydrolitagent.cards.card_generators.proxy import proxy_summary


def run_preflight(adapter: Any, *, check_pdf_reader: bool = True) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    executable = adapter._executable_finder(adapter.config.executable)
    if executable is None:
        checks.append(
            _check(
                "executable",
                "fail",
                f"找不到配置的 Codex CLI：{adapter.config.executable}",
            )
        )
        return adapter._failure(
            checks,
            "CODEX_CLI_NOT_FOUND",
            "找不到 Codex CLI；请安装后检查 card_generator.executable",
            resolved_executable=None,
        )

    checks.append(_check("executable", "pass", "已找到 Codex CLI 可执行程序"))
    try:
        version_result = adapter._runner(
            [executable, "--version"],
            adapter.config.preflight_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        checks.append(_check("version", "fail", "Codex CLI 版本检查超时"))
        return adapter._failure(
            checks,
            "CODEX_CLI_TIMEOUT",
            "Codex CLI 版本检查超时",
            resolved_executable=executable,
        )
    except (OSError, subprocess.SubprocessError):
        checks.append(_check("version", "fail", "Codex CLI 无法启动"))
        return adapter._failure(
            checks,
            "CODEX_CLI_UNAVAILABLE",
            "Codex CLI 已找到但无法启动",
            resolved_executable=executable,
        )

    version_output = _combined_output(version_result)
    if version_result.returncode != 0 or not version_output:
        checks.append(_check("version", "fail", "Codex CLI 未返回有效版本"))
        return adapter._failure(
            checks,
            "CODEX_CLI_UNAVAILABLE",
            "Codex CLI 版本检查失败",
            resolved_executable=executable,
        )

    cli_version = version_output.splitlines()[0].strip()
    checks.append(_check("version", "pass", f"Codex CLI 可运行：{cli_version}"))

    try:
        auth_result = adapter._runner(
            [executable, "login", "status"],
            adapter.config.preflight_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        checks.append(_check("authentication", "fail", "Codex 登录状态检查超时"))
        return adapter._failure(
            checks,
            "CODEX_CLI_TIMEOUT",
            "Codex 登录状态检查超时",
            resolved_executable=executable,
            cli_version=cli_version,
        )
    except (OSError, subprocess.SubprocessError):
        checks.append(_check("authentication", "fail", "无法检查 Codex 登录状态"))
        return adapter._failure(
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
        return adapter._failure(
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
        return adapter._failure(
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
        return adapter._failure(
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
    if not check_pdf_reader:
        return {
            "schema_version": 1, "ok": True, "component": "card_generator",
            "resolved_executable": executable, "cli_version": cli_version,
            "detected_auth_mode": "chatgpt_account", "checks": checks,
            "proxy": proxy_summary(adapter.config.proxy),
        }
    reader = adapter.config.pdf_reader
    if not reader.server_file.is_file():
        checks.append(
            _check("pdf_reader_server", "fail", "项目内置 PDF MCP 服务文件不存在")
        )
        return adapter._failure(
            checks,
            "PDF_READER_SERVER_NOT_FOUND",
            "找不到项目内置 PDF MCP 服务文件；请检查 card_generator.pdf_reader.server_file",
            resolved_executable=executable,
            cli_version=cli_version,
            detected_auth_mode="chatgpt_account",
        )
    checks.append(
        _check("pdf_reader_server", "pass", "项目内置只读 PDF MCP 服务文件可用")
    )

    dependency_requests = {
        "python": reader.python_executable or sys.executable,
        "pdfinfo": reader.pdfinfo_executable,
        "pdftotext": reader.pdftotext_executable,
        "pdftoppm": reader.pdftoppm_executable,
    }
    resolved_dependencies: dict[str, str] = {}
    for name, requested in dependency_requests.items():
        resolved = adapter._executable_finder(requested)
        if resolved is None:
            checks.append(
                _check(
                    f"pdf_reader_{name}",
                    "fail",
                    f"找不到 PDF 读取依赖：{name}",
                )
            )
            return adapter._failure(
                checks,
                "PDF_READER_DEPENDENCY_NOT_FOUND",
                f"找不到 PDF 读取依赖 {name}；请检查 card_generator.pdf_reader 配置",
                resolved_executable=executable,
                cli_version=cli_version,
                detected_auth_mode="chatgpt_account",
            )
        resolved_dependencies[name] = resolved
        checks.append(
            _check(
                f"pdf_reader_{name}",
                "pass",
                f"已找到 PDF 读取依赖：{name}",
            )
        )
    return {
        "schema_version": 1,
        "ok": True,
        "component": "card_generator",
        "checked_at": _now(),
        "adapter": adapter.config.adapter,
        "configured_executable": adapter.config.executable,
        "resolved_executable": executable,
        "configured_auth_mode": adapter.config.auth_mode,
        "proxy": proxy_summary(adapter.config.proxy),
        "detected_auth_mode": "chatgpt_account",
        "cli_version": cli_version,
        "pdf_reader": {
            "adapter": reader.adapter,
            "server_name": reader.server_name,
            "server_file": str(reader.server_file),
            "resolved_python_executable": resolved_dependencies["python"],
            "resolved_pdfinfo_executable": resolved_dependencies["pdfinfo"],
            "resolved_pdftotext_executable": resolved_dependencies["pdftotext"],
            "resolved_pdftoppm_executable": resolved_dependencies["pdftoppm"],
            "render_dpi": reader.render_dpi,
            "max_pages_per_call": reader.max_pages_per_call,
            "output_token_limit": reader.output_token_limit,
        },
        "checks": checks,
    }


__all__ = ["run_preflight"]
