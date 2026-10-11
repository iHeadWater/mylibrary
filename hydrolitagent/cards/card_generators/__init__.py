from __future__ import annotations

from hydrolitagent.cards.card_generators.base import CardGeneratorAdapter
from hydrolitagent.cards.config import CardGeneratorConfig
from hydrolitagent.cards.progress import ProgressCallback


def build_card_generator_adapter(
    config: CardGeneratorConfig,
    *, progress: ProgressCallback | None = None,
) -> CardGeneratorAdapter:
    """按配置装配单篇制卡适配器。

    收敛到最小核心后只保留两个后端，且都要求 single_agent + local_path：
    - `claude_cli`：Claude Code CLI
    - `codex_cli`：Codex CLI（经 CodexLocalPdfAdapter 直读本地 PDF）

    已随本次收敛移除：multi_agent 工作流（`multi_agent.py`）、
    以及 codex_cli 非 local_path 的 MCP 读取分支（`pdf_reader_mcp.py`）。
    """
    if config.adapter == "claude_cli":
        from hydrolitagent.cards.card_generators.claude_cli import ClaudeCliAdapter
        from hydrolitagent.cards.card_generators.single_agent import SingleAgentCardGeneratorAdapter
        if config.workflow_mode != "single_agent" or config.pdf_reader.adapter != "local_path":
            raise ValueError("Claude 适配器只接入单篇 single_agent + local_path 工作流")
        return SingleAgentCardGeneratorAdapter(ClaudeCliAdapter(config, progress=progress), progress=progress)
    if config.adapter == "codex_cli":
        from hydrolitagent.cards.card_generators.codex_local_pdf import CodexLocalPdfAdapter
        from hydrolitagent.cards.card_generators.single_agent import SingleAgentCardGeneratorAdapter
        if config.workflow_mode != "single_agent" or config.pdf_reader.adapter != "local_path":
            raise ValueError("Codex 适配器只接入单篇 single_agent + local_path 工作流")
        return SingleAgentCardGeneratorAdapter(
            CodexLocalPdfAdapter(config, progress=progress), progress=progress,
        )
    raise ValueError(f"未注册的证据卡生成适配器：{config.adapter}")


__all__ = ["CardGeneratorAdapter", "build_card_generator_adapter"]
