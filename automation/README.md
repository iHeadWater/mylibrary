# 自动化程序

本目录将承载以下自动化能力：

1. 读取指定的 Zotero 共享群组库；
2. 检测新增父条目和后续补充的 PDF；
3. 检查 PDF 是否存在且可读取；
4. 防止同一父条目被重复制卡；
5. 创建或更新共享证据包；
6. 记录关键事件，并将可共享结果同步到 GitHub。

当前已完成 US-01 至 US-07B1 的代码、自动化测试和真实正向验收。现有能力包括 Zotero 检测、PDF 门禁、任务状态机、证据包骨架、原始 PDF 只读交付、Codex CLI 登录预检和无论文模型调用探针。正式制卡、Git 自动同步和调度尚未实现。详细证据卡模板不是运行探针的前置条件。

## 可复现材料

    automation/
    ├─ src/       自动化源代码
    ├─ prompts/   受版本控制的 AI 提示词
    ├─ schemas/   manifest、事件和任务的数据结构
    ├─ setup/     新电脑安装、配置和调度脚本
    └─ tests/     自动化与恢复测试

自动化还必须支持在本地运行状态丢失时进行全量对账并重建状态。

依赖及其版本必须通过锁定文件进入 Git。具体文件形式将在确定实现语言后决定。

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

该命令只运行 `codex --version` 和 `codex login status`，不会运行 `codex exec`，也不会读取 Zotero、PDF、模板、任务或证据包。只有明确检测到 ChatGPT 登录时才返回成功；API Key 登录、未登录或无法确认认证方式都会失败。登录凭据和登录命令的原始输出不会写入结果。

这只是运行环境预检，不代表已调用模型或已经具备正式制卡能力，也不能证明订阅档位或剩余额度。

## 当前实现：US-07B1

执行一次固定、无论文内容的最小模型调用：

    python automation/run.py generator-smoke-test --json

该命令先执行 US-07A 预检，再在系统临时创建的空目录中通过 `codex exec` 期待固定响应 `HYDRO_GENERATOR_OK`。调用强制使用只读沙箱、临时会话、忽略用户 MCP/配置和 JSONL 输出；项目仓库不是模型工作目录，临时目录在调用结束后删除，不会读取 PDF、模板、任务或证据包，也不会写入模型输出文件。模型、推理强度和 120 秒调用超时来自 `config/config.json`；模型或推理强度为 `null` 时使用模型默认值。

它能验证当前时刻的真实调用链，并区分认证、限流、额度、模型、推理强度兼容性、超时和协议错误；它不是证据卡生成器。真实论文、模板路由、正式制卡所选推理强度、输出结构和写卡保护属于 US-07B2。真实验收即使只返回固定标记，也消耗了 16,324 个输入 token，因此本命令不能作为每日健康检查，只应在安装、认证、模型或推理强度变化后受控执行一次。

## 配置原则

程序不依赖调用命令时的工作目录。所有可调整的项目路径和固定运行参数由 `config/config.json` 集中管理；运行时产生的 Key、哈希、时间和任务状态不属于配置；Codex CLI 登录凭据、API Key、Token 等秘密不得写入配置或 Git。当前制卡适配层位于 `automation/src/hydro_platform/card_generators/`，只注册了 `codex_cli`。
