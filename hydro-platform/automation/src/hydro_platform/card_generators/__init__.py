from __future__ import annotations

from hydro_platform.card_generators.base import CardGeneratorAdapter
from hydro_platform.card_generators.codex_cli import CodexCliAdapter
from hydro_platform.card_generators.multi_agent import MultiAgentCardGeneratorAdapter
from hydro_platform.config import CardGeneratorConfig
from hydro_platform.progress import ProgressCallback


def build_card_generator_adapter(
    config: CardGeneratorConfig,
    *, progress: ProgressCallback | None = None,
) -> CardGeneratorAdapter:
    if config.adapter == "codex_cli":
        if config.pdf_reader.adapter == "local_path":
            from hydro_platform.card_generators.codex_local_pdf import CodexLocalPdfAdapter
            provider = CodexLocalPdfAdapter(config, progress=progress)
        else:
            provider = CodexCliAdapter(config, progress=progress)
        if config.workflow_mode == "single_agent":
            from hydro_platform.card_generators.single_agent import SingleAgentCardGeneratorAdapter
            if config.pdf_reader.adapter != "local_path":
                raise ValueError("单 Agent 当前要求本地 PDF 路径读取")
            return SingleAgentCardGeneratorAdapter(provider, progress=progress)
        if config.multi_agent_workflow is None:
            raise ValueError("证据卡生成必须配置强制多 Agent 工作流")
        return MultiAgentCardGeneratorAdapter(
            provider,
            config.multi_agent_workflow,
            progress=progress,
        )
    raise ValueError(f"未注册的证据卡生成适配器：{config.adapter}")


__all__ = ["CardGeneratorAdapter", "build_card_generator_adapter"]
