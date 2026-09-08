# AI 提示词

所有参与证据卡生成或更新的提示词都必须纳入版本控制，并有稳定的版本标识。

独立实验提示词 `pdf-direct-read-trial-v2.md` 仅用于 `pdf-direct-read-trial`：要求从给定本地路径自主读文字和页面图像，返回读取声明、图表观察和读取限制；不要求摘录，不使用 MCP、不制卡，不替代正式卡片生成。位置由 `card_generator.pdf_direct_trial.prompt_file` 配置，总配置、示例和默认路径已同步。

当前提示词为 evidence-card-generation-v7.md，共用 pdf-local-reading-v1.md，协议 rough-card-single-agent-v1。一个 Agent 完成自动选型及详细粗卡，区分原文陈述/转述、AI 推理和信息边界；不加子 Agent、摘录任务、固定数量门槛或人工复核要求。v7 保留必需二级章节，允许额外小节、图表和排版变化，避免扩展详细内容反而无法保存；不改变内容与来源要求。v6 及 v1/v2 六角色提示词保留为历史兼容，当前配置不引用。

成功生成后，证据包清单记录合成提示词版本和 SHA-256、模型配置、输出 schema 指纹及工作流协议；模型输出、执行参数和质量门结果写入 `quality-audit.json`。模型再次运行时允许文字不同，但流程与验收规则必须一致。模板正文仍保存在 `templates/evidence-cards/`，不复制到提示词文件中；Python 在运行时读取已启用模板并拼接请求。
