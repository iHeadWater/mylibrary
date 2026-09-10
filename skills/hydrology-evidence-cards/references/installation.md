# 安装与接入

## 安装 Skill

把整个 `skills/hydrology-evidence-cards` 文件夹复制到个人 Codex skills 目录，保持文件夹名不变：

- Windows：`%USERPROFILE%\.codex\skills\hydrology-evidence-cards`
- macOS/Linux：`~/.codex/skills/hydrology-evidence-cards`

重新打开 Codex 后，用 `$hydrology-evidence-cards` 显式调用，或提出“从 Zotero 读取某篇材料并做证据卡”。

## 接入 Zotero

1. 安装并打开 Zotero Desktop。
2. 把合法取得的文献或报告保存到个人 Zotero；核对题名、作者、年份和稳定标识。
3. 确认本地 API 可用；执行 `python scripts/zotero_reader.py status`。
4. API 不可用时，在 Zotero 高级设置中启用本地 API，或安装官方 Zotero 插件 Skill 后按其说明启用。
5. 不共享 Zotero 数据库文件、私人附件路径和访问凭据。

## 接入 Obsidian 与 Git

将团队 GitHub 仓库克隆为独立 Obsidian 仓库。卡片写入团队约定目录；全文留在 Zotero 或授权文件系统。提交前确认 Git 只包含 Markdown、模板、脚本、稳定链接和允许共享的小型图件。

每位成员使用自己的分支提交证据卡。合并前至少完成结构校验和一次逐条原文复核。若团队要求独立同伴检查，只有真实检查发生后才填写检查人和日期。

## 最小试运行

1. 选择一篇允许本地读取的文献。
2. 搜索并确认唯一 Zotero item key。
3. 建立临时读取包。
4. 选择卡型并生成空白卡。
5. 填写至少一个有位置的 C01 声明和真实阅读范围。
6. 运行 draft 校验；完整处理后运行 final 校验。
7. 检查未把全文、临时包和凭据加入 Git。
