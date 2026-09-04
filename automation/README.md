# 自动化程序

本目录将承载以下自动化能力：

1. 读取指定的 Zotero 共享群组库；
2. 检测新增父条目和后续补充的 PDF；
3. 检查 PDF 是否存在且可读取；
4. 防止同一父条目被重复制卡；
5. 创建或更新共享证据包；
6. 记录关键事件，并将可共享结果同步到 GitHub。

当前只实现了 US-01 和 US-02；PDF 门禁、制卡、Git 同步和调度尚未实现。详细证据卡模板不是开始开发检测链路的前置条件。

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

## 配置原则

程序不依赖调用命令时的工作目录。所有可调整的项目路径和固定运行参数由 `config/config.json` 集中管理；运行时产生的 Key、哈希、时间和任务状态不属于配置；API Key、Token 等密钥不得写入配置或 Git。
