"""⑧ 拼装：Markdown + HTML。

Markdown 走 Obsidian 的嵌入语法 ``![[images/f0004.jpg|说明]]``，图片下面再跟一行
同样的说明 —— Obsidian 不会把 ``|`` 后面那段渲染成图注，只有那行纯文本能让说明
真正显示出来。

HTML 是给「不开 Obsidian 也想看一眼」准备的：把嵌入改写成 ``<figure>``，顺手吃掉
重复的那行说明，否则每张图下面会有一条重复文字。
"""

from __future__ import annotations

import html as htmllib
import json
import re
import shutil
import time
from pathlib import Path

FULL_HEADING = "## 全文整理"
CAPTION_PREFIX = "图｜"
EMBED = re.compile(r"!\[\[([^\]|\n]+?)(?:\|([^\]\n]*))?\]\]")
# 新版：图片独占一行，下一行是斜体图注
CAPTION_LINE = re.compile(r"!\[\[([^\]|\n]+?)\]\]\s*\n\s*\*(?:图｜)?([^*\n]+)\*")
# 旧版（#88 之前）：``![[图|说明]]`` 后面再跟一行同样的说明
LEGACY_PAIR = re.compile(
    r"!\[\[([^\]|\n]+?)\|([^\]\n]+)\]\][ \t]*\n(?:\s*\n)?\2[ \t]*(?:\n|$)"
)

CSS = """
:root { --ink:#1b1b1f; --muted:#6b7280; --line:#e5e7eb; --brand:#1565c0; }
* { box-sizing: border-box; }
body { margin:0; background:#fbfbfc; color:var(--ink);
  font: 16px/1.75 -apple-system, "PingFang SC", "Hiragino Sans GB", sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 48px 20px 80px; background:#fff; }
h1 { font-size: 26px; line-height:1.35; margin: 0 0 8px; }
h2 { font-size: 20px; margin: 40px 0 12px; padding-left: 10px;
  border-left: 4px solid var(--brand); }
p { margin: 0 0 14px; }
figure { margin: 20px 0 24px; }
figure img { width: 100%; border: 1px solid var(--line); border-radius: 6px; display: block; }
figcaption { margin-top: 8px; color: var(--muted); font-size: 13px; text-align: center; }
strong { color: #0f172a; }
ol, ul { padding-left: 22px; }
li { margin: 4px 0; }
""".strip()


def cn_num(n: int) -> str:
    """1 → 一，10 → 十，12 → 十二，21 → 二十一。节数没有上下限，到 99 就够了。"""
    d = "零一二三四五六七八九"
    if n <= 10:
        return "十" if n == 10 else d[n]
    if n < 20:
        return "十" + d[n % 10]
    if n < 100:
        return d[n // 10] + "十" + (d[n % 10] if n % 10 else "")
    return str(n)


def caption_line(desc: str) -> str:
    """图注单独一行、斜体、带「图｜」前缀。

    三样都做，是因为只做斜体时，长图注在小屏幕上仍然容易和正文混在一起：
    - 「图｜」前缀告诉读者「这是图注」；
    - 斜体在 Obsidian 与导出的 HTML 里都稳定；
    - 单独成段（前后各一个空行）让它不粘在正文段落末尾。
    """
    return f"*{CAPTION_PREFIX}{desc}*"


def build_markdown(
    meta: dict,
    sections: list[dict],
    bodies: list[str],
    layout: list[dict],
    work: Path,
    *,
    image_dir: str = "images",
    url: str | None = None,
) -> tuple[str, int]:
    """返回 ``(markdown 文本, 图片数)``，顺带把用到的帧拷进 ``images/``。"""
    by_sec = {x["section"]: x["items"] for x in layout}
    (work / image_dir).mkdir(parents=True, exist_ok=True)
    n_img = 0
    parts_sec: list[str] = []
    for i, (sec, body) in enumerate(zip(sections, bodies)):
        paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        after: dict[int, list[dict]] = {}
        for it in by_sec.get(i + 1, []):
            after.setdefault(it["para"], []).append(it)
        parts: list[str] = []
        for j, p in enumerate(paras, 1):
            parts.append(p)
            for it in after.get(j, []):
                fname = f"f{it['t']:04d}.jpg"
                src = work / "frames" / fname
                if not src.exists():
                    continue
                shutil.copy2(src, work / image_dir / fname)
                parts.append(f"![[{image_dir}/{fname}]]\n{caption_line(it['desc'])}")
                n_img += 1
        parts_sec.append(
            f"## {cn_num(i + 1)}、{sec['title']}\n\n" + "\n\n".join(parts)
        )

    head = f"""---
title: {meta['title']}
author: {meta.get('uploader') or ''}
source: 视频笔记 - B站
url: {url or meta.get('webpage_url') or f"https://www.bilibili.com/video/{meta['id']}/"}
saved: {time.strftime('%Y-%m-%d %H:%M:%S')}
tags:
  - 视频笔记
---

作者：{meta.get('uploader') or ''}

"""
    return head + "\n\n".join(parts_sec) + "\n", n_img


def build_full(full_parts: list[str]) -> str:
    return f"\n\n{FULL_HEADING}\n\n" + "\n\n".join(full_parts) + "\n"


def to_vault_links(text: str, album: str, *, image_dir: str = "images") -> str:
    """入库时把 ``images/…`` 改写成 vault 内路径。

    写成 vault 相对的 ``media/videos/<BV>/…`` 而不是光秃秃的文件名：不同视频的帧
    都叫 ``f0004.jpg``，只写文件名会互相串。
    """
    return text.replace(f"![[{image_dir}/", f"![[media/videos/{album}/")


def _figure(path: str, caption: str) -> str:
    src = htmllib.escape(path, quote=True)
    alt = htmllib.escape(caption)
    figcaption = f"<figcaption>{alt}</figcaption>" if caption else ""
    return f'<figure><img src="{src}" alt="{alt}">{figcaption}</figure>'


def figures(text: str) -> str:
    """Obsidian 嵌入 → ``<figure>``。

    三种写法都要认：新版的「图片 + 下一行斜体图注」、旧版的「``|说明`` + 重复一行」、
    以及光秃秃的嵌入。旧版留着是因为 vault 里可能还有 #88 之前导入的笔记。
    """
    text = CAPTION_LINE.sub(lambda m: _figure(m.group(1), m.group(2)) + "\n", text)
    text = LEGACY_PAIR.sub(lambda m: _figure(m.group(1), m.group(2)) + "\n", text)
    return EMBED.sub(lambda m: _figure(m.group(1), m.group(2) or ""), text)


def render_html(text: str) -> str:
    """Markdown → 单文件 HTML。图片用相对路径 ``images/…``，与 note.md 同目录即可。"""
    import markdown

    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    title = ""
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip()
        text = text[m.end() :]
    title = title or "视频笔记"
    body = markdown.markdown(figures(text), extensions=["extra", "sane_lists"])
    return (
        "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{htmllib.escape(title)}</title>\n<style>\n{CSS}\n</style>\n"
        f"</head>\n<body>\n<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


def write_note(
    work: Path,
    meta: dict,
    sections: list[dict],
    bodies: list[str],
    layout: list[dict],
    full_parts: list[str],
    *,
    usage: dict | None = None,
    shots: list[dict] | None = None,
    blocks: int | None = None,
    log=print,
) -> dict:
    """落地 ``note.md`` / ``note.html`` / ``run.json``，返回摘要。"""
    text, n_img = build_markdown(meta, sections, bodies, layout, work)
    note = text + build_full(full_parts)
    (work / "note.md").write_text(note, encoding="utf-8")
    (work / "note.html").write_text(render_html(note), encoding="utf-8")

    chars_structured = len(note.split(FULL_HEADING)[0])
    summary = {
        "video": meta["title"],
        "duration": meta["duration"],
        "blocks": blocks,
        "sections": len(sections),
        "frames": len(shots or []),
        "usable": sum(1 for s in (shots or []) if s["usable"]),
        "images": n_img,
        "chars_total": len(note),
        "chars_structured": chars_structured,
        "chars_full": len(note) - chars_structured,
        **(usage or {}),
    }
    (work / "run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    log(
        f"[8] {len(sections)} 节 / {n_img} 图 / {len(note)} 字 → {work / 'note.md'}"
    )
    return summary
