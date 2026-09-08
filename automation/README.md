# 自动化程序

当前默认单 Agent、模板驱动、详细粗卡。一个会话读原始 PDF、自动选型并详细填写；Python 验证来源、归因和模板结构，保留信息不确定性，不设人工核卡任务。八类模板 1.1.0，新流程 rough-card-single-agent-v1。已有卡用 evidence-generate-trial，未有卡用 evidence-generate。

当前样本下一步：

```powershell
python automation/run.py evidence-generate-trial --item-key CEXH4PQA --json
```

不会覆盖已有卡，不会推送 Git。详细操作见 [手册](../documentation/operator-manual.md) 与 [单 Agent 规则](../documentation/single-agent-rough-card.md)。原始模型输出先存本地草稿，清理失败不丢结果。真实新流程未代跑。

每日调度、统一批处理入口、关键贡献事件、Git 同步、安装及恢复脚本尚未完成。setup/ 目前只有说明，不是已经交付的换机工具。

## 当前实现：US-01

当前已实现只读、非交互的 Zotero 群组发现与目标群组预检：

    python automation/run.py discover-groups --json
    python automation/run.py preflight --group-id 1234567 --json

目标团队库配置已经进入 config/config.json，可直接运行：

    python automation/run.py preflight --json

返回码：

- 0：预检通过；
- 2：配置错误；
- 3：Zotero、接口、群组或权限检查失败。

US-01 不修改 Zotero，不读取 PDF，也不写入 GitHub。自动启动 Zotero、等待同步和计划调度属于后续用户故事。

## 当前实现：US-02

建立本地基线或检测父条目与 PDF 附件变化：

    python automation/run.py scan --json

第一次运行返回 baseline，只建立快照，不把已有文献记为当天贡献。以后运行返回 incremental，并可输出：

- ITEM_ADDED；
- ITEM_REMOVED；
- PDF_ADDED；
- PDF_REMOVED；
- PDF_ATTACHMENT_CHANGED。

本地快照默认保存在 `.runtime/zotero-snapshot.json`，实际路径来自 `config/config.json`，已被 Git 忽略。快照损坏或属于另一群组时，程序会拒绝覆盖。

## 当前实现：US-03

对单个 Zotero 父条目执行只读 PDF 全文门禁：

    python automation/run.py pdf-gate --item-key CEXH4PQA --json

门禁检查 PDF 是否唯一、是否已同步为本地文件、文件大小、基础 PDF 结构、SHA-256，以及 Zotero 全文索引中的可提取文字数量。结果分为 `READY`、`WAITING` 和 `BLOCKED`。`pdf-gate` 命令自身不会复制 PDF 或生成证据包；证据包骨架由 US-05 的 `packages-sync` 创建。

## 当前实现：US-04

同步并查看本地任务清单：

    python automation/run.py tasks-sync --json
    python automation/run.py tasks-list --json

任务清单使用群组 ID、父条目 Key、PDF 附件 Key 和 SHA-256 形成输入指纹，支持幂等同步、输入版本变化、原子写入、进程锁、处理租约、过期重试和完成保护。当前命令只把门禁通过的任务推进到 `READY_FOR_EXTRACTION`，不会假装已经提取全文或完成制卡。

## 当前实现：US-05

根据本地任务清单，为所有 `READY_FOR_EXTRACTION` 任务创建共享证据包骨架：

    python automation/run.py packages-sync --json

每个证据包包含 `manifest.json` 和最小占位 `card.md`。目录用 Zotero 父条目 Key 定位；相同输入重复运行不会创建第二个目录，也不会覆盖已经填写的卡片。manifest 损坏、目录不完整或 PDF 输入与已有证据包不一致时，命令拒绝静默覆盖。

创建骨架不会改变任务状态，也不代表全文已经提取或证据卡已经完成。

## 当前实现：US-06

对一个已就绪任务重新定位 Zotero 原始 PDF，复核附件 Key、任务 ID、manifest 和 PDF SHA-256，并返回可供后续制卡器消费的本地文件路径：

    python automation/run.py pdf-delivery --item-key CEXH4PQA --json

该命令不复制 PDF、不导出全文文本、不调用 AI，也不修改任务或证据包。PDF 缺失、附件变化、哈希变化、任务未就绪或证据包不完整时直接失败，不交付旧路径。

## 当前实现：US-07A

检查总配置指定的 Codex CLI 是否存在、能否返回版本，以及当前是否明确使用 ChatGPT 账号登录：

    python automation/run.py generator-preflight --json

该命令只运行 `codex --version` 和 `codex login status`，读取共用读取指引，并定位所选本机工具。当前 `local_path` 不检查或启动 MCP，pypdf 模式不要求 pdftotext。不会调用模型、读取 Zotero PDF、任务或证据包，也不会保存登录凭据。

这只是运行环境预检，不代表已调用模型或已经具备正式制卡能力，也不能证明订阅档位或剩余额度。

## 当前实现：US-07B1

执行一次固定、无论文内容的最小模型调用：

    python automation/run.py generator-smoke-test --json

该命令先执行 US-07A 预检，再在系统临时创建的空目录中通过 `codex exec` 期待固定响应 `HYDRO_GENERATOR_OK`。调用强制使用只读沙箱、临时会话、忽略用户 MCP/配置和 JSONL 输出；项目仓库不是模型工作目录，临时目录在调用结束后删除，不会读取 PDF、模板、任务或证据包，也不会写入模型输出文件。模型、推理强度和 120 秒调用超时来自 `config/config.json`；模型或推理强度为 `null` 时使用模型默认值。

它能验证当前时刻的真实调用链，并区分认证、限流、额度、模型、推理强度兼容性、超时和协议错误；它不是证据卡生成器。真实论文、模板路由、制卡配置、输出结构和写卡保护属于 US-07B4。真实验收即使只返回固定标记，也消耗了 16,324 个输入 token，因此本命令不能作为每日健康检查，只应在安装、认证、模型或推理强度变化后受控执行一次。

## 当前实现：US-07B2

校验八类证据卡模板的目录、来源、版本和机器字段：

    python automation/run.py evidence-templates-validate --json

模板目录和清单文件由 `config/config.json` 的 `paths.evidence_card_templates_dir` 与 `paths.evidence_card_template_catalog_file` 指定。命令会检查模板 ID 和文件唯一、文件未逃出配置目录、来源 commit 与 blob SHA 已记录、本地版本格式正确、front matter 含平台必填字段，以及适配后内容 SHA-256 没有静默变化。

八类模板都已启用，供单 Agent 自动选择唯一模板；不设置“待人工确认类型”。分类置信度和理由将被记录但不阻塞生成，非法模板 ID 由 US-07B4 按质量合约失败处理。该命令不访问 Zotero、不调用模型、不读取 PDF，也不修改现有证据包。

## 制卡实现与历史兼容

US-07B3 验证过单调用技术链路；US-07B4 六角色试运行暴露耗时与结果保全问题。当前实现替代为单 Agent 详细粗卡，保留旧代码、旧审计与测试以读取历史结果；不自动回退。现有卡仍跳过，试运行只写 .runtime/card-trials。

实时进度显示 [1/1 全文阅读与详细制卡]。模型、强度和一次会话时限来自总配置；当前 1200 秒是上限，不是预期耗时。连接保护未改动，不等于网络已修复。

## 配置原则

程序不依赖调用命令时的工作目录。所有可调整的项目路径和固定运行参数由 `config/config.json` 集中管理；运行时产生的 Key、哈希、时间和任务状态不属于配置；Codex CLI 登录凭据、API Key、Token 等秘密不得写入配置或 Git。当前制卡适配层位于 `automation/src/hydro_platform/card_generators/`；当前默认单 Agent，底层只注册了 `codex_cli` 提供者。
