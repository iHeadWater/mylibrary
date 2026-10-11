# 前提与配置

**先配好这一页，再去用任何一项能力。** 这里是全部**公共前提**的唯一出处 —— 各功能页只写「本页额外需要什么」，不再重复。

## 配好之后怎么用

**打开本项目文件夹，用一个编码 agent 让它替你干活。**

「本项目文件夹」就是你 `git clone` 下来的 `mylibrary` 目录。在**这个目录里**开一个编码 agent ——
**Claude Code · Codex · workbuddy · CC Switch 接的 Claude Code**，你顺手哪个都行 —— 然后**说人话**：

> 「把 10.1038/s41586-024-07145-1 下载并入库」 · 「把《某某》这篇做成卡」 · 「看看能聚出哪些主题」

**⚠️ 所有操作都要在 `mylibrary` 目录里做。** 命令与产物路径都以它为基准；在别处运行会找不到依赖。
新开终端先回到这里：

```bash
cd /path/to/mylibrary
```

## 一、通用（每项能力都要）

| 需要 | 说明 |
|---|---|
| **Git** | |
| **Python 3.12–3.14** | `requires-python = ">=3.12,<3.15"` |
| **uv** | [安装指引](https://docs.astral.sh/uv/) |
| **Zotero 桌面版** | 至少运行过一次（生成本地数据库） |

```bash
git clone git@github.com:iHeadWater/mylibrary.git     # 或 https://github.com/iHeadWater/mylibrary.git
cd mylibrary
uv sync --all-packages
```

> 本仓库只有**一个包 `hydrolitagent`**。入口是 `uv run hydrolitagent …`；
> 文献卡与主题卡走子命令组 `uv run hydrolitagent cards …`（**运行时 Windows-only**）。

## 二、按能力看还要什么

| 你要做的事 | 额外需要 | 凭据放哪 |
|---|---|---|
| **读 Zotero 库**（MCP 12 个工具） | Zotero **Web API key** | `.env`：`ZOTERO_API_KEY` · `ZOTERO_LIBRARY_ID` |
| **下载 + 入 Zotero**（入库） | 上面那条 + **GDrive 论文目录** + Zotero 里对应的「**链接附件根目录**」设置 | `.env`：`GDRIVE_PAPERS_PATH` |
| **机构访问下载 PDF** | **Playwright 浏览器** + 学校机构会话 | 见 [论文 PDF 下载](../user-guide/download-pdf.md) |
| **文献卡与主题卡** | Zotero Desktop **正在运行**且**允许其他应用通信**；一种**已登录**的模型 CLI（Codex 或 Claude）；读 PDF 页面用的 [Poppler](https://poppler.freedesktop.org/)（`pdftoppm` / `pdfinfo` / `pdftotext`）在 PATH 里 | 模型凭据由**那个 CLI 自己**管 —— **不进本仓库** |
| **深度处理**（精读 / 公众号 / 播客） | 看产出而定：**智谱**（配图）、**微信公众号**（发布）、**NotebookLM** | `.env`：`ZHIPUAI_API_KEY` · `WECHAT_APPID` + `WECHAT_APPSECRET` 等 |
| **只做离线校验** | **以上额外项都不需要** | — |

逐字段的环境变量清单见[配置参考](../user-guide/config.md)。
**密钥一律从环境变量读**，不要写进源码或提交。

## 三、凭据：`.env`

```bash
cp .env.example .env
```

`.env` 已被 Git 忽略。**按上表只填你要用的那几条** —— 空着不是错。

```bash
# 读 Zotero 库（必需）
ZOTERO_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxx
ZOTERO_LIBRARY_ID=1234567
ZOTERO_LIBRARY_TYPE=user          # user（默认）或 group

# Zotero 本地全文检索（可选；需 Zotero Desktop 运行）
# 只填 host 根，/api/users/0 由服务自己补。旧名 ZOTERO_LOCAL_API_URL 仍兼容。
#   裸 host  -> http://127.0.0.1:23119
#   容器内   -> http://host.docker.internal:23119
ZOTERO_LOCAL_BASE_URL=http://127.0.0.1:23119

# 论文入库（必需，仅入库那条线）
GDRIVE_PAPERS_PATH=G:\我的云端硬盘\Documents\Papers\Zotero_Papers
```

**Zotero API key 怎么拿**：[zotero.org/settings/keys](https://www.zotero.org/settings/keys) →
**Create New Private Key** → 勾选 **Allow library access** 与 **Allow notes access** →
记下 Key 和页面顶部的 **User ID**（数字）。

**入库还要在 Zotero 里配一次**：Preferences → Advanced → Files and Folders →
**链接附件根目录**（Zotero 里叫 Linked Attachment Base Directory）设成与 `GDRIVE_PAPERS_PATH` **同一个**路径；
并确认 ZotMoov / 「自动重命名并移动附件」对该文件夹**关闭**。

> 容器（myopenclaw hermes）可与裸 host 共用一份凭据文件 `~/.config/zot/config.toml`
> （`[zotero] library_id / api_key`）；可用 `ZOTERO_CONFIG_PATH` 改路径。
> 裸 host **无需 TOML**，脚本在无 TOML 时自动回退 `.env`。

## 四、验证

```bash
uv run python -c "import pyzotero; print('pyzotero OK')"    # 依赖装好了吗
uv run python scripts/download_paper.py --setup-check       # 入库链路自检（.env / API / GDrive）
```

文献卡那条线的自检不需要你的论文或模型账号，见[文献卡与主题卡](../user-guide/cards/index.md)。

## 下一步

配好通用部分后，按你要做的事往下走：

- **入库**（下载 PDF → Zotero）：[论文入库流水线](../user-guide/paper-pipeline.md)
- **读库 / 精读 / 内容产出**：[用户指南总览](../user-guide/index.md)
- **文献卡与主题卡**：[文献卡与主题卡](../user-guide/cards/index.md)
