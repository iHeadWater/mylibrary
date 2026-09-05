from __future__ import annotations

from hydro_platform.card_generators.base import CardGeneratorAdapter
from hydro_platform.card_generators.codex_cli import CodexCliAdapter
from hydro_platform.config import CardGeneratorConfig


def build_card_generator_adapter(
    config: CardGeneratorConfig,
) -> CardGeneratorAdapter:
    if config.adapter == "codex_cli":
        return CodexCliAdapter(config)
    raise ValueError(f"未注册的证据卡生成适配器：{config.adapter}")


__all__ = ["CardGeneratorAdapter", "build_card_generator_adapter"]
