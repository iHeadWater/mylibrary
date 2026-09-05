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
- `card.md`：主证据卡。正式模板尚未确定，当前由 `packages-sync` 写入最小占位内容：标题“待生成证据卡”和状态 `PLACEHOLDER`。
- `topic-readings/`：同一论文面向不同主题的定向精读；需要时再创建。

PDF 全文继续由 Zotero 管理，不复制到本仓库。主题目录只能引用证据包，不复制证据卡。

当前可以运行：

```powershell
python automation/run.py packages-sync --json
```

命令只处理本地任务清单中的 `READY_FOR_EXTRACTION` 任务。相同输入重复运行不会创建第二个目录，也不会覆盖已经填写的 card.md。后续制卡 Agent 也只允许把 `PLACEHOLDER` 首次替换为粗证据卡；已有非占位卡永远跳过。PDF 输入变化、manifest 损坏或目录不完整时，系统会拒绝静默覆盖。
