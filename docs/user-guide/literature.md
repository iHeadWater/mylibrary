# 文献深度处理（Literature CLI）

从 dailyinfo 迁入的文献深度处理能力。以 **Zotero 库为分界线**:文献进入 Zotero 之前(采集/下载/入库)由 dailyinfo 负责;进入之后(精读/分析卡/主题/公众号/播客/B 站发布)由本仓库负责。

## 模块结构

```
hydrolitagent/literature/
├── _paths.py              # 路径助手(PROJECT_ROOT/OUTPUT_ROOT/NOTEBOOKLM_HOME)
├── download_pdf.py        # 论文 PDF 下载(机构访问)
├── zotero_sync.py         # Zotero 入库(linked_file)
├── bilibili_upload.py     # B 站发布(封面 → MP4 → biliup 上传)
├── zotero_notebooklm.py   # Zotero → NotebookLM 简报/音频/视频
└── wechat/
    ├── figure.py          # 配图/封面(从 Zotero PDF 提图,或智谱 CogView 生成)
    ├── polish.py          # 公众号文章润色
    └── push.py            # 公众号草稿箱发布
```

## CLI 用法（统一用 `uv run python -m`）

```bash
# 论文 PDF 下载 / 验证(需 Playwright MCP 插件)
uv run python -m hydrolitagent.literature.download_pdf verify <pdf>
uv run python -m hydrolitagent.literature.download_pdf detect <url>

# Zotero 入库(linked_file)
uv run python -m hydrolitagent.literature.zotero_sync <pdf> <doi> --json

# B 站上传(封面自动生成)
uv run python -m hydrolitagent.literature.bilibili_upload <audio.mp3> \
  --title "标题" --tags "AI,水文,科研" [--dry-run]

# NotebookLM 简报/音频
uv run python -m hydrolitagent.literature.zotero_notebooklm \
  --collection water --artifact audio --open-missing-pdfs

# 公众号发布
uv run python -m hydrolitagent.literature.wechat.push <polished.md> [--thumb <media_id>]

# 公众号润色
uv run python -m hydrolitagent.literature.wechat.polish <draft.md>

# 配图/封面(需 ZHIPUAI_API_KEY)
uv run python -m hydrolitagent.literature.wechat.figure <article.md>
```

## 依赖的环境变量

| 变量 | 用途 | 归属模块 |
|------|------|---------|
| `ZOTERO_API_KEY` | Zotero Web API 密钥 | zotero_sync.py |
| `ZOTERO_LIBRARY_ID` | Zotero 数字型用户 ID | zotero_sync.py |
| `GDRIVE_PAPERS_PATH` | GDrive 论文文件夹(Linked Attachment Base Directory) | zotero_sync.py |
| `ZHIPUAI_API_KEY` | 智谱 AI(CogView)配图/封面 | wechat/figure.py |
| `WECHAT_APPID` / `WECHAT_APPSECRET` / `WECHAT_THUMB_MEDIA_ID` | 公众号发布 | wechat/push.py |
| `NOTEBOOKLM_HOME` | NotebookLM CLI 配置目录(默认 `.tmp/notebooklm`) | zotero_notebooklm.py |
| `ZOTERO_LOCAL_BASE_URL` | Zotero 本地 API(默认 `http://127.0.0.1:23119`) | zotero_notebooklm.py |

> ⚠️ 凭据一律从环境变量读取,**不要把 API 密钥硬编码进源码**。`push.py` 曾硬编码微信凭据,迁移时已修复为 env 读取。

## 相关文档

- [论文 PDF 下载（机构访问）](download-pdf.md) — Playwright 浏览器下载
- [Zotero 入库（linked_file）](zotero-sync.md) — PDF → Zotero 条目
- [Zotero → NotebookLM 简报](zotero-notebooklm.md) — 新机器配置与完整工作流

## 精读产物(知识库)

每周文献综述的产出(分析卡、文章、播客)统一放在 `outputs/weekly-review/{YYYY-MM-DD}/`:

```
outputs/weekly-review/2026-08-04/
├── cards/         # 8 段分析卡(每篇一篇)
├── article/       # 公众号文章
├── podcast/       # 播客音频
└── 文献总览.md     # 本期论文分类总览
```

精读流程由 `skills/weekly-review/` 驱动:每篇论文一个子代理精读全文 → 写 8 段分析卡 → 主题聚类 → 文章 → 播客。

## 相关 Skill

| Skill | 功能 |
|-------|------|
| `weekly-review` | 每周文献综述:精读→卡片→主题→文章→播客 |
| `zotero-notebooklm` | Zotero 论文 → NotebookLM 简报/音频/视频 |
| `weekly-report-generator` | NotebookLM 输出 → 公众号周报 |
| `figure-skill-v2` | 配图/封面 |
| `bilibili-upload` | B 站发布 |
| `download-pdf` | 论文 PDF 下载(机构访问)+ Zotero 同步 |
