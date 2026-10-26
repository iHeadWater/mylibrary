"""Composition root: the one module that binds configuration to adapters.

Every other layer talks to ports. ``composition`` is allowed to name concrete
implementations because it is the place where a deployment choice is made: which
PDF library converts, where prepared papers are cached and which runner executes
a card task.

Keeping this in one module means "how the pipeline is wired" can be read in one
screen, and nothing below it can quietly grow a provider branch.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydrolitagent.cards.adapters.pdf.pymupdf_converter import PymupdfConverter
from hydrolitagent.cards.adapters.runners.codex.proxy import codex_proxy_environment
from hydrolitagent.cards.adapters.runners.markdown import (
    ClaudeMarkdownRunner,
    CodexMarkdownRunner,
)
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

    The runner is chosen from the configured adapter name, not from an
    environment probe: an unknown name fails here instead of silently falling
    back to a different provider.
    """

    converter_config = getattr(app_config, "converter", None)
    converter_id = getattr(converter_config, "converter_id", "none")
    if converter_id not in KNOWN_CONVERTERS:
        raise ConfigError(
            f"未知的 PDF 转换器：{converter_id!r}；当前支持 {sorted(KNOWN_CONVERTERS)}"
        )
    card_generator = app_config.card_generator
    adapter = card_generator.adapter
    if adapter == "claude_cli":
        runner: CardRunner = ClaudeMarkdownRunner(
            card_generator.executable,
            connection_guard=card_generator.connection_guard,
        )
    elif adapter == "codex_cli":
        runner = CodexMarkdownRunner(
            card_generator.executable,
            environment=codex_proxy_environment(card_generator.proxy),
            connection_guard=card_generator.connection_guard,
        )
    else:
        raise ConfigError(
            f"未注册的制卡运行器：{adapter!r}；Markdown 流程只支持 claude_cli 或 codex_cli"
        )
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
