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
- `card.md`：主证据卡。详细模板尚未确定，当前不得将占位内容当作正式证据。
- `topic-readings/`：同一论文面向不同主题的定向精读；需要时再创建。

PDF 全文继续由 Zotero 管理，不复制到本仓库。主题目录只能引用证据包，不复制证据卡。
