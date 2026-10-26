"""Composition root: the one module that binds configuration to adapters.

Every other layer talks to ports. ``composition`` is allowed to name concrete
implementations because it is the place where a deployment choice is made: which
PDF library converts, where prepared papers are cached and which runner executes
a card task.

Keeping this in one module means "how the pipeline is wired" can be read in one
screen, and nothing below it can quietly grow a provider branch. Runner
selection itself is a registry lookup (``adapters/runners/registry.py``), so
adding a runner does not require editing this file: composition hands every
factory the same bag of dependencies and each one takes what it needs.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydrolitagent._config import PathConfigError, resolve_literature_root
from hydrolitagent.cards.adapters.pdf.doctor import probe_pymupdf
from hydrolitagent.cards.adapters.runners.registry import RegistryError, create, ids as runner_ids
from hydrolitagent.cards.adapters.storage.doctor import storage_checks
from hydrolitagent.cards.adapters.storage.paper_store import PaperStore
from hydrolitagent.cards.application.doctor import (
    build_report,
    converter_checks,
    runner_checks,
    summarize_capabilities,
)
from hydrolitagent.cards.config import ConfigError
from hydrolitagent.cards.ports.doctor import DoctorCheck
from hydrolitagent.cards.ports.paper import (
    ConversionOptions,
    PaperConverter,
    PaperStore as PaperStorePort,
)
from hydrolitagent.cards.ports.runner import CardRunner, RunnerDoctor

# Converter ids this stage can build. ``none`` means "configuration did not
# choose a converter", which the Markdown pipeline resolves to the only
# available implementation instead of silently skipping conversion.
KNOWN_CONVERTERS = frozenset({"none", "pymupdf"})


@dataclass(frozen=True)
class MarkdownPipeline:
    """The three ports one Markdown-first card run needs, plus its options."""

    converter: PaperConverter
    store: PaperStorePort
    runner: CardRunner
    options: ConversionOptions


def _conversion_options(converter_config: Any) -> ConversionOptions:
    if converter_config is None:
        return ConversionOptions()
    return ConversionOptions(
        mode=getattr(converter_config, "mode", "layout"),
        extract_figures=getattr(converter_config, "extract_figures", True),
        table_mode=getattr(converter_config, "table_mode", "markdown"),
        ocr=getattr(converter_config, "ocr", False),
        min_text_coverage=getattr(converter_config, "min_text_coverage", 0.60),
    )


def _runtime_root(app_config: Any) -> Path:
    configured = getattr(app_config.card_generator, "runtime_dir", None) or getattr(
        app_config.paths, "runtime_dir", None
    )
    return Path(configured) if configured else Path(tempfile.gettempdir())


def _cache_dir(app_config: Any) -> Path:
    converter_config = getattr(app_config, "converter", None)
    configured = getattr(converter_config, "cache_dir", None)
    if configured:
        return Path(configured)
    return _runtime_root(app_config)


def _default_converter() -> PaperConverter:
    # Imported lazily so ``cards doctor`` can diagnose a missing PyMuPDF instead
    # of failing while importing the composition root itself.
    from hydrolitagent.cards.adapters.pdf.pymupdf_converter import PymupdfConverter

    return PymupdfConverter()


def _runner_options(app_config: Any, runner_id: str) -> dict[str, Any]:
    card_generator = app_config.card_generator
    runner_options = dict(getattr(app_config, "runner_options", None) or {})
    return {
        "executable": getattr(card_generator, "executable", None),
        "model": getattr(card_generator, "model", None),
        "proxy": getattr(card_generator, "proxy", None),
        "connection_guard": getattr(card_generator, "connection_guard", None),
        "base_url": runner_options.get("base_url"),
        "max_input_tokens": runner_options.get("max_input_tokens"),
        "max_output_tokens": runner_options.get("max_output_tokens"),
    }


def build_markdown_pipeline(app_config: Any) -> MarkdownPipeline:
    """Wire one converter, one store and one runner for a single card run.

    The runner is chosen from the configured adapter name through the registry,
    not from an environment probe: an unknown name fails here instead of
    silently falling back to a different provider.
    """

    converter_config = getattr(app_config, "converter", None)
    converter_id = getattr(converter_config, "converter_id", "none")
    if converter_id not in KNOWN_CONVERTERS:
        raise ConfigError(
            f"未知的 PDF 转换器：{converter_id!r}；当前支持 {sorted(KNOWN_CONVERTERS)}"
        )
    card_generator = app_config.card_generator
    # ``runner_options`` comes from the AI selection (base_url and token
    # budgets). Everything else is the ordinary card-generator configuration;
    # factories ignore the keys they do not use.
    try:
        runner = create(card_generator.adapter, **_runner_options(app_config, card_generator.adapter))
    except RegistryError as exc:
        raise ConfigError(f"未注册的制卡运行器：{card_generator.adapter!r}；{exc}") from exc
    return MarkdownPipeline(
        converter=_default_converter(),
        store=PaperStore(_cache_dir(app_config)),
        runner=runner,
        options=_conversion_options(converter_config),
    )


def build_session_pipeline(app_config: Any) -> MarkdownPipeline:
    """Wire the file-based, two-phase pipeline (``cards run prepare|finalize``).

    The runner is data, not a deployment choice here: an external agent does the
    reading, so there is nothing about the selected AI provider to configure.
    """

    converter_config = getattr(app_config, "converter", None)
    converter_id = getattr(converter_config, "converter_id", "none")
    if converter_id not in KNOWN_CONVERTERS:
        raise ConfigError(
            f"未知的 PDF 转换器：{converter_id!r}；当前支持 {sorted(KNOWN_CONVERTERS)}"
        )
    try:
        runner = create("in_session")
    except RegistryError as exc:  # pragma: no cover - built-in registration
        raise ConfigError(f"缺少 in_session 运行器：{exc}") from exc
    return MarkdownPipeline(
        converter=_default_converter(),
        store=PaperStore(_cache_dir(app_config)),
        runner=runner,
        options=_conversion_options(converter_config),
    )


# --------------------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------------------


def _configured_runner_id(app_config: Any) -> str:
    configured = str(getattr(app_config.card_generator, "adapter", "")).strip().casefold()
    if configured.endswith("_cli") and len(configured) > 4:
        configured = configured[:-4]
    return configured


def _doctor_runner_options(app_config: Any, runner_id: str) -> dict[str, Any]:
    """Probe each runner with *its own* executable, not the selected one's.

    The configured executable belongs to whichever runner a card run would use.
    Reusing it for every doctor check made the local-agent checks report the
    same binary; the others must fall back to their own command name.
    """

    options = _runner_options(app_config, runner_id)
    if runner_id != _configured_runner_id(app_config) or not options["executable"]:
        options["executable"] = runner_id
    return options


def _runner_doctors(app_config: Any) -> list[RunnerDoctor]:
    """Build every registered runner and ask it for a self-report.

    A runner that cannot even be constructed becomes an unavailable report
    rather than an exception: one broken deployment must not hide the rest of
    the diagnosis. No factory call here invokes a model or reads a paper.
    """

    reports: list[RunnerDoctor] = []
    for runner_id in runner_ids():
        try:
            runner = create(runner_id, **_doctor_runner_options(app_config, runner_id))
            report = runner.doctor()
            # Report the registry id the operator can pass to --ai-provider; the
            # adapter's internal id is an implementation detail.
            reports.append(
                RunnerDoctor(
                    runner_id=runner_id,
                    available=report.available,
                    detail=report.detail,
                    fix=report.fix,
                )
            )
        except Exception as exc:  # noqa: BLE001 - the failure *is* the diagnosis
            reports.append(
                RunnerDoctor(
                    runner_id=runner_id,
                    available=False,
                    detail=f"无法构建该运行器：{type(exc).__name__}: {exc}",
                    fix="检查该运行器的配置（可执行文件、地址、令牌环境变量）",
                )
            )
    return reports


def _network_checks(app_config: Any) -> tuple[DoctorCheck, ...]:
    """Zotero probes, only on explicit ``--network``."""

    zotero = getattr(app_config, "zotero", None)
    if zotero is None or getattr(zotero, "group_id", None) is None:
        return (
            DoctorCheck(
                name="zotero.target_group",
                capability="zotero.read",
                status="skip",
                detail="未配置目标群组，跳过联网检查",
                fix="在配置中设置 zotero.group_id，或继续使用 --network 之外的本地检查",
            ),
        )
    from hydrolitagent.cards.zotero import preflight

    try:
        result = preflight(zotero)
    except Exception as exc:  # noqa: BLE001 - network failure is a check result
        return (
            DoctorCheck(
                name="zotero.preflight",
                capability="zotero.read",
                status="fail",
                detail=f"Zotero 检查失败：{type(exc).__name__}: {exc}",
                fix="确认 Zotero 正在运行并允许本地 API 访问",
            ),
        )
    statuses = {"pass": "pass", "warn": "warn", "fail": "fail", "skip": "skip"}
    checks = [
        DoctorCheck(
            name=f"zotero.{item.get('name', 'check')}",
            capability="zotero.read",
            status=statuses.get(item.get("status"), "warn"),
            detail=str(item.get("detail", "")),
            fix=None if item.get("status") == "pass" else "确认 Zotero 本地 API 与目标群组可访问",
        )
        for item in result.get("checks", [])
        if isinstance(item, dict)
    ]
    if not checks:
        checks.append(
            DoctorCheck(
                name="zotero.preflight",
                capability="zotero.read",
                status="fail" if not result.get("ok") else "pass",
                detail=str((result.get("error") or {}).get("message", "未返回检查项")),
                fix=None if result.get("ok") else "确认 Zotero 正在运行并允许本地 API 访问",
            )
        )
    return tuple(checks)


def build_doctor_report(app_config: Any, *, output_root: Any = None, network: bool = False) -> dict:
    """Collect converter, runner, storage (and optional Zotero) checks."""

    checks: list[DoctorCheck] = list(converter_checks(probe_pymupdf()))
    checks.extend(runner_checks(_runner_doctors(app_config)))

    try:
        literature_root = resolve_literature_root(root=output_root)
        checks.extend(
            storage_checks(
                output_root=literature_root,
                runtime_dir=_runtime_root(app_config),
            )
        )
    except PathConfigError as exc:
        checks.append(
            DoctorCheck(
                name="storage.output_root",
                capability="storage.write",
                status="fail",
                detail=f"产物根无法解析：{exc}",
                fix="检查 --output-root 与 paths 配置后重试",
            )
        )

    if network:
        checks.extend(_network_checks(app_config))

    capabilities = summarize_capabilities(
        checks,
        extra={
            "network_checked": bool(network),
            "runners_registered": list(runner_ids()),
        },
    )
    return build_report(checks, capabilities=capabilities)


__all__ = [
    "KNOWN_CONVERTERS",
    "MarkdownPipeline",
    "build_doctor_report",
    "build_markdown_pipeline",
    "build_session_pipeline",
]
