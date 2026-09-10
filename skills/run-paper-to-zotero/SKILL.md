---
name: run-paper-to-zotero
description: Alias skill for downloading a paper and adding it to Zotero. Full dual-mode instructions (myopenclaw/hermes container vs bare-host) live in the canonical `paper-to-zotero` skill. Trigger on "下载并加到Zotero", "同步至Zotero", "下载论文并导入", "加到文献库", "download and add to Zotero", "save paper to Zotero", "put this paper in my library", or any phrase that combines paper download/fetch with Zotero/library management.
---

# Paper-to-Zotero — Alias

> ⚠️ **本 skill 已并入 `skills/paper-to-zotero`(双模式)。请阅读那份文档的「两种运行环境」节再执行。**
> 以下只保留最常用的容器 canonical,便于历史引用。

## 模式 A · myopenclaw/hermes 容器(爱码士)

```bash
docker compose exec hermes-coder /opt/hermes/scripts/run-paper-pipeline.sh "<DOI_OR_TITLE>"
```

单条命令完成 4 步:paper-fetch 下载 → rclone 上传 → paper-to-zotero 元数据 + `linked_file` → 清理。
DO NOT 手动下载(curl/wget/python fetch)、手动 rclone、手动建 Zotero 条目或附件。
若命令失败:报告错误即可,不要手动绕行。

## 模式 B · 裸 host / 本仓库直跑

```bash
uv run python scripts/download_paper.py --setup-check            # 新机器一次
uv run python scripts/download_paper.py --arxiv <id> --sync      # arXiv
uv run python scripts/download_paper.py --doi <doi> --sync       # 期刊 DOI
```

（完整说明、arXiv 幂等与 post-sync 核验见 `skills/paper-to-zotero`。）
