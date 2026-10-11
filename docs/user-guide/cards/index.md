# 文献卡与主题卡

以**你自己的 Zotero 文献库**为来源：把一篇论文变成一张可校验的文献卡，再把若干文献卡组织成
持续演化的主题卡。**Codex 或 Claude CLI 负责内容提炼，Python 负责确定性的门禁、校验与安全写入。**
Git 只保存可复现的代码、配置、模板、测试和文档。

本页说明「这套东西是什么、有哪些命令、从哪里读起」。技术实现、字段与运行步骤由专项文档维护，
面向评审的总体设计见[项目级设计](../../development/platform/project-design.md)。

## 五条命令

| 阶段 | 命令 | 做什么 |
|---|---|---|
| 输入 | `paper-input` | 按题名搜索候选，或按条目 Key 检查单篇 Zotero 论文，得到 READY 输入记录 |
| 生成 | `evidence-generate` | 读取该篇 PDF 正文，调用所选模型生成主体卡草稿 |
| 校验 | `evidence-validate` | **离线**校验草稿并保存记录 —— 不调用模型、不正式发布 |
| 主题 | `themes-run` | 以若干文献卡为输入，生成候选主题、定向精读并回填修订 |
| 自查 | `ai-config` | 查看模型选择与产物根，不运行模型 |

命令一律**从仓库根**执行，完整清单：`uv run hydrolitagent cards --help`。

## 从这里开始

| 你想了解什么 | 阅读入口 |
| --- | --- |
| 单篇论文从输入到校验的完整命令行流程 | [单篇论文命令行流程](single-paper-quickstart.md) |
| 单篇 Zotero 论文输入 | [单篇 Zotero 论文输入](paper-input.md) |
| 主体卡草稿生成 | [从单篇 PDF 生成主体卡草稿](subject-card-draft.md) |
| 主体卡代码校验 | [主体卡代码校验门禁](subject-card-validation.md) |
| 主题池：候选主题的演化与版本 | [统一文献池与主题池](unified-theme-pool.md) |
| 技术架构、数据归属与模块边界 | [技术架构](../../development/platform/architecture.md) |
| 数据流、用户流程与失败处理 | [数据流与用户流程](../../development/platform/flows.md) |
| 配置字段、路径与密钥边界 | [总配置字段说明](../../development/platform/config.md) · [变量与密钥](../../development/platform/variables.md) |
| 证据卡与主题模板 | [公共模板](templates.md) |
| 验证与测试覆盖 | [验证地图](../../development/platform/tests.md) |
| 科研工作流（人读证据卡与主题综合） | [科研工作流](../../research-workflow/index.md) |
| 面向评审的总体设计 | [项目级设计](../../development/platform/project-design.md) |

## 单篇核心流程

```mermaid
flowchart TD
    A["用户指定 Zotero 论文 (paper-input)"] --> B{"输入有效？"}
    B -- 否 --> B1["停止并说明原因"]
    B -- 是 --> C["AI 生成主体卡片 (evidence-generate)"]
    C --> D["代码校验卡片 (evidence-validate)"]
    D --> E{"通过？"}
    E -- 否 --> E1["返回错误，定向修正后重新校验"]
    E -- 是 --> F["若干文献卡 → 候选主题 (themes-run)"]
```

## 边界

- **通过校验只表示确定性规则通过，不证明科研内容正确。**
- 正式主题必须**人工确认**；`themes-run` 只产出候选，不自动晋级。
- 输入论文必须已有可读取的全文；不满足时停止并说明原因。
- Zotero 条目负责论文身份，条目中的 PDF 负责正文内容。

## 什么进 Git，什么不进

产物落点：单篇流程写到**产物根**（`--output-root`，默认仓库 `outputs/`），主题池写到 `paths.themes_dir`。

| 进 Git | 不进 Git |
|---|---|
| 代码、Skills、模板、Schema、测试 | Zotero 数据库、原始 PDF、账号凭据 |
| 项目文档、依赖锁、非敏感团队配置 | `.runtime/`、`.venv/`、项目内原生工具 |
| 不含私人路径 / 账号 / 密钥的示例 | 实际生成的文献卡、主题、运行记录 |

程序**不会**自动提交或推送 Git。要共享科研产物，走团队另行确认的共享位置与权限策略 ——
**本地保存不等于已完成远端备份**。

## 文档维护规则

实现与目标设计分开写；旧方案与演示讲稿交给 Git 历史，不占正式导航。
模板的可执行版本以 `skills/` 与 `hydrolitagent/cards/assets/templates/` 为准，文档里不另留副本。
