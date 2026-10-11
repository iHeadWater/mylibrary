# 统一文献池与主题池

**一个研究问题 = 一个长期主题。** 文献增加时已有主题持续演化，而不是每批新文献各生成一套。

候选主题可以**自动**补充、修正、合并、拆分；**正式主题不自动覆盖**；人**不**逐卡、逐次审批。

## 怎么用

跟 agent 说「看看能聚出哪些主题」或「主题池现在什么样」。自己敲的话：

```bash
uv run hydrolitagent cards themes-run --json                 # 生成 / 更新候选主题
uv run hydrolitagent cards themes-run --dry-run --json       # 只预览：不扫 Zotero、不写文件、不调模型
uv run hydrolitagent cards themes-run --migrate-only --json  # 只把已有旧成果接进统一池
```

**阅读入口是 `themes/index.md`** —— 当前候选、历史主题与版本都在那里。进入某个主题后，
日常主要看精读回填的 `revised.md`，不必从文件夹猜最新版。

## 产物长什么样

```text
themes/
  index.md                       给人看的总入口：当前候选、历史主题与版本链接
  _registry.json                 稳定编号、当前版本、历史版本、合并/拆分关系
  candidates/TH-编号/versions/CHANGE-编号/
    initial.md / revised.md      初版与精读回填结果
    plan.json / manifest.json    变更类型、理由、父主题与来源引用
  changes/CHANGE-编号/            一次处理的输入、规划与提交记录
evidence-packs/…/readings/       独立保存的精读结果（主题只引用，不复制）
```

> **怎么看产出**：卡片与主题都是带 `[[双向链接]]` 的 Markdown ——
> 用 **Obsidian** 把产物目录（`证据卡/`、`主题/`，落点由 `paths.artifact_root` 决定）
> 当 vault 打开，就能沿链接读、按目录导航。**今天就能这样用。**
>
> 另一件**尚未实现**的事：让平台受控地搜索 / 写入你的 Obsidian（Vault 接入选型见
> [项目级设计](../../development/platform/project-design.md)）。两件事别混。

## 边界

- **正式主题不能被自动改写**：候选必须**由人确认**才能转正式；`themes-run` 只产出候选，**不自动晋级**。
  专用确认入口**尚未实现** —— 现在没有把候选转正式的命令，别去找它、也别手改注册表来「模拟确认」。
- **不要手改**索引或注册表 —— 手改会被判为冲突，程序**保留现场而不覆盖**。
- 目录里出现半成品**不代表**它已成为当前主题。
- **精读适用时复用**：换批次**不构成**重读原始 PDF 的理由。
- 主题只**引用**证据包，不复制论文或粗卡。
- 输入指纹变化只说明「有新输入」，**不限制**跨批次关联。
- 当前面向**小样本**文献库；**大规模上下文的检索/压缩尚未实现**。

## 相关

[公共模板](templates.md) · [运行维护](runtime-maintenance.md)
