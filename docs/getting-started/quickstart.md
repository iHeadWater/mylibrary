# 5 分钟上手

## 先做两件事

**1. 配好前置** —— [前提与配置](installation.md)：装依赖、开 Zotero、登录一个模型 CLI。**配一次就够。**

**2. 在你的项目文件夹里操作** —— 就是 clone 下来的 `mylibrary` 目录（仓库根）。
所有命令与产物路径都以它为基准；在别处跑会找不到依赖、产物也会散到别处去。
**新开终端后先回到这里**：

```bash
cd /path/to/mylibrary        # 换成你 clone 下来的位置
```

> 下面每个场景先给「**你可以这么说**」—— 直接跟 agent 说人话就行；
> 后面的命令是等价做法，agent 不方便用时自己敲也一样。

## 场景 1：找文献

**你可以这么说**：

> 「我库里有哪些关于城市洪涝的论文？」

它会读你的 Zotero 库（题名 / 全文 / 标签），返回候选与元数据。
这套读取能力由 12 个 MCP 工具提供，详见 [MCP Server 工具](../user-guide/mcp-tools.md)。

## 场景 2：把论文加进 Zotero（只建条目）

**你可以这么说**：

> 「把 10.1038/s41586-024-07145-1 加进我的 Zotero」

只建条目，**不下载 PDF**：

```bash
uv run python -m hydrolitagent.zotero.paper_to_zotero --metadata-only "10.1038/s41586-024-07145-1"
uv run python -m hydrolitagent.zotero.paper_to_zotero --metadata-only "10.48550/arXiv.2501.08086"
uv run python -m hydrolitagent.zotero.paper_to_zotero --dry-run --metadata-only "10.1038/s41586-024-07145-1"   # 预览，不写入
```

## 场景 3：下载 PDF 并入库

**你可以这么说**：

> 「把 10.1038/s41586-024-07145-1 下载并入库」

它会解析 DOI → 下载 PDF → 建 Zotero 条目 + `linked_file` 附件。

- **arXiv 与开放获取**（science.org / Copernicus 等）走 curl，**秒级**。
- **付费墙**（ScienceDirect / Wiley / Nature 等）会**打开一个浏览器窗口** ——
  你按提示走完机构会话，剩下的它接着做。

新机器先自检一次，之后一条命令：

```bash
uv run python scripts/download_paper.py --setup-check
uv run python scripts/download_paper.py --doi "10.1038/s41586-024-07145-1" --sync
uv run python scripts/download_paper.py --arxiv 2501.08086 --sync
```

同一个 DOI 重跑，会把 PDF **补挂到已有条目**（条目在、缺 PDF 的常见情形）；
已经挂过同一份内容则**幂等跳过**。

**在容器里跑**（myopenclaw / hermes）：

```bash
docker compose exec hermes-coder /opt/hermes/scripts/run-paper-pipeline.sh "10.1038/s41586-024-07145-1"
docker compose exec hermes-coder /opt/hermes/scripts/run-paper-pipeline.sh --dry-run "10.1038/xxx"
```

## 场景 4：给已有条目补一个 GDrive 里的 PDF

**你可以这么说**：

> 「这条 Zotero 记录缺 PDF，文件在 GDrive 里，帮我挂上」

```bash
uv run python -m hydrolitagent.zotero.zot_link_gdrive <ZOTERO_KEY> <filename>
```

## 场景 5：精读成分析卡 / 公众号 / 播客

**你可以这么说**：

> 「把这批论文精读成分析卡」 · 「出一期公众号 + 播客」

精读由 `skills/weekly-review/` 驱动：每篇论文一个子代理读全文 → 8 段分析卡 → 主题聚类 →
公众号文章 → 播客，产物落在 `outputs/weekly-review/{日期}/`。

```bash
uv run python -m hydrolitagent.literature.zotero_notebooklm --collection water --artifact audio
uv run python -m hydrolitagent.literature.bilibili_upload audio.mp3 --title "标题" --dry-run
```

## 场景 6：把论文做成文献卡与主题卡（Windows）

**你可以这么说**：

> 「把《某某》这篇做成卡」 · 「看看能聚出哪些主题」

一条链路：文献卡 → 代码校验 → 候选主题。**运行时 Windows-only**，前置见[前提与配置](installation.md)。
详见[文献卡与主题卡](../user-guide/cards/index.md)。

## 下一步

- [前提与配置](installation.md) — 通用前提 + 按能力看额外要什么 + 凭据放哪
- [论文入库流水线](../user-guide/paper-pipeline.md) — 下载与入库的完整流程和故障排查
- [MCP Server 工具](../user-guide/mcp-tools.md) — 12 个工具的用途、参数与返回格式
- [文献深度处理](../user-guide/literature.md) — 精读、公众号、播客的 CLI
- [文献卡与主题卡](../user-guide/cards/index.md) — 自己 Zotero 的论文 → 文献卡 → 主题卡（Windows-only）
- [Zotero 配置参考](../user-guide/config.md) — 环境变量与配置文件
