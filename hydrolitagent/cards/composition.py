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

from hydrolitagent.cards.adapters.pdf.pymupdf_converter import PymupdfConverter
from hydrolitagent.cards.adapters.runners.registry import RegistryError, create
from hydrolitagent.cards.adapters.storage.paper_store import PaperStore
from hydrolitagent.cards.config import ConfigError
from hydrolitagent.cards.ports.paper import (
    ConversionOptions,
    PaperConverter,
    PaperStore as PaperStorePort,
)
from hydrolitagent.cards.ports.runner import CardRunner

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


def _cache_dir(app_config: Any) -> Path:
    converter_config = getattr(app_config, "converter", None)
    configured = getattr(converter_config, "cache_dir", None)
    if configured:
        return Path(configured)
    runtime = getattr(app_config.card_generator, "runtime_dir", None) or getattr(
        app_config.paths, "runtime_dir", None
    )
    return Path(runtime) if runtime else Path(tempfile.gettempdir())


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
    runner_options = dict(getattr(app_config, "runner_options", None) or {})
    try:
        runner = create(
            card_generator.adapter,
            executable=getattr(card_generator, "executable", None),
            model=getattr(card_generator, "model", None),
            proxy=getattr(card_generator, "proxy", None),
            connection_guard=getattr(card_generator, "connection_guard", None),
            base_url=runner_options.get("base_url"),
            max_input_tokens=runner_options.get("max_input_tokens"),
            max_output_tokens=runner_options.get("max_output_tokens"),
        )
    except RegistryError as exc:
        raise ConfigError(f"未注册的制卡运行器：{card_generator.adapter!r}；{exc}") from exc
    return MarkdownPipeline(
        converter=PymupdfConverter(),
        store=PaperStore(_cache_dir(app_config)),
        runner=runner,
        options=_conversion_options(converter_config),
    )


__all__ = [
    "KNOWN_CONVERTERS",
    "MarkdownPipeline",
    "build_markdown_pipeline",
]
