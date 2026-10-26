from __future__ import annotations

from hydrolitagent.cards.card_generators.base import CardGeneratorAdapter
from hydrolitagent.cards.config import CardGeneratorConfig
from hydrolitagent.cards.progress import ProgressCallback


def build_card_generator_adapter(
    config: CardGeneratorConfig,
    *, progress: ProgressCallback | None = None,
) -> CardGeneratorAdapter:
    """按配置装配旧单篇制卡适配器。

    本地 PDF 直读路径（Codex 读 PDF）已随 Markdown 优先管线移除。这里保留
    Claude 的旧适配器，仅用于 ``evidence-generate --item-key`` 的历史兼容；
    ``--paper-input`` 走 ``adapters/runners/registry.py``，与本函数无关。
    """
    if config.adapter == "claude_cli":
        from hydrolitagent.cards.card_generators.claude_cli import ClaudeCliAdapter
        from hydrolitagent.cards.card_generators.single_agent import SingleAgentCardGeneratorAdapter
        if config.workflow_mode != "single_agent":
            raise ValueError("Claude 适配器只接入单篇 single_agent 工作流")
        return SingleAgentCardGeneratorAdapter(ClaudeCliAdapter(config, progress=progress), progress=progress)
    if config.adapter == "codex_cli":
        raise ValueError(
            "Codex 本地 PDF 直读适配器已移除；请改用 --paper-input 的 Markdown 路径，"
            "或选择 claude 兼容旧证据包流程"
        )
    raise ValueError(f"未注册的证据卡生成适配器：{config.adapter}")


__all__ = ["CardGeneratorAdapter", "build_card_generator_adapter"]
