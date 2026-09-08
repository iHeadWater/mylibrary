# 证据包

这是团队唯一的证据包存储区，不按学生拆分。

## 一篇论文一个证据包

目录命名约定：

`EV-<Zotero父条目Key>-<简短标题>`

单个证据包的目标结构：

```text
EV-<parentKey>-<slug>/
├─ manifest.json
├─ card.md
└─ topic-readings/
```

- `manifest.json`：身份、来源和处理版本信息，不承载科研结论。
- `card.md`：主证据卡。`packages-sync` 先写入标题“待生成证据卡”和状态 `PLACEHOLDER`；强制多 Agent 质量门通过后首次替换为 `ROUGH` 粗证据卡。
- `quality-audit.json`：成功制卡的机器审计记录，包含六个隔离角色的输出、模型参数、PDF 读取回执和全部质量门。它不是人工复核结论。
- `topic-readings/`：同一论文面向不同主题的定向精读；需要时再创建。

PDF 全文继续由 Zotero 管理，不复制到本仓库。主题目录只能引用证据包，不复制证据卡。

当前可以先同步骨架，再对单篇论文生成粗卡：

```powershell
python automation/run.py packages-sync --json
python automation/run.py evidence-generate --item-key CEXH4PQA --json
```

这些命令只处理本地任务清单中的就绪任务。相同输入重复运行不会创建第二个目录，也不会覆盖已经填写的 card.md。制卡器只允许把 `PLACEHOLDER` 首次替换为 `ROUGH` 粗证据卡；成功后的 manifest 会记录 PDF、模型、提示词、输出 schema、模板、分类、质量审计和卡片内容哈希。已有非占位卡永远跳过。PDF 输入变化、manifest 损坏或目录不完整时，系统会拒绝静默覆盖。对已有卡的多 Agent 对比测试只写入 `.runtime/card-trials/`，不改正式证据包。
