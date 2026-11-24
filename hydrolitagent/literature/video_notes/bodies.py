"""⑤ 写正文：逐节写，只依据本节素材；最后另写一份口语化「全文整理」。

温度 0.4 —— 这一步要的是「像人写的」，不是「可复现」。同一份逐字稿跑两遍
得到两份措辞不同的正文是正常现象，别拿两次产物做逐字节比对。

写作规则全部在 ``assets/style.md``，代码不藏风格。
"""

from __future__ import annotations

import json
from pathlib import Path

from . import fmt
from .proofread import strip_heading

STYLE_PATH = Path(__file__).with_name("assets") / "style.md"
HEADINGS = {"正文": "body", "全文整理": "spoken"}


def load_style(path: Path | None = None) -> dict[str, str]:
    """把 ``style.md`` 按 ``## `` 标题拆成 ``{"body":…, "spoken":…}``。"""
    text = (path or STYLE_PATH).read_text(encoding="utf-8")
    parts: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            parts[current] = []
        elif current is not None:
            parts[current].append(line)
    style = {
        key: "\n".join(parts.get(name, [])).strip()
        for name, key in HEADINGS.items()
    }
    missing = [name for name, key in HEADINGS.items() if not style[key]]
    if missing:
        raise RuntimeError(f"{STYLE_PATH} 缺少小节：{'、'.join(missing)}")
    return style


def write_body(client, sec: dict, blocks: list[dict], meta: dict, style: str) -> str:
    src = "\n".join(
        f"[{n}] {fmt(blocks[n - 1]['start'])} {blocks[n - 1]['text']}"
        for n in range(sec["from"], sec["to"] + 1)
    )
    body = client.ask(
        f"""你在写一篇中文笔记的其中一节。视频是 B 站教学视频《{meta['title']}》。

【这一节要写】
标题：{sec['title']}
对应素材（[段号] 时间 正文）：
{src}

【写作规则】
{style}

直接输出正文。""",
        max_tokens=2400,
        temperature=0.4,
    )
    return strip_heading(body)


def write_full(
    client, chunk: list[tuple[dict, str]], style: str, *, index: int
) -> str:
    src = "\n\n".join(f"《{s['title']}》\n{b}" for s, b in chunk)
    part = client.ask(
        f"""下面是一期教学视频某几节的成稿正文。请改写成口语化讲解，用于笔记末尾的「全文整理」。

【风格规则】
{style}

【要改写的正文】
{src}

直接输出。""",
        max_tokens=3000,
        temperature=0.6,
    )
    if not part.startswith("###"):
        part = f"### 第 {index} 部分\n\n" + part
    return part


def group_size(n_sections: int) -> int:
    """每份「全文整理」覆盖几节。节多时 5 节一组，避免单次输出被截断。"""
    n_group = 5 if n_sections >= 8 else 3
    return (n_sections + n_group - 1) // n_group


def ensure_bodies(
    work: Path,
    sections: list[dict],
    blocks: list[dict],
    meta: dict,
    client,
    *,
    style: dict[str, str] | None = None,
    log=print,
) -> tuple[list[str], list[str]]:
    """返回 ``(逐节正文, 全文整理分段)``。两份都各自缓存。"""
    style = style or load_style()

    bodies_path = work / "bodies.json"
    if not bodies_path.exists():
        bodies: list[str] = []
        for i, sec in enumerate(sections):
            body = write_body(client, sec, blocks, meta, style["body"])
            bodies.append(body)
            log(f"  [{i + 1}/{len(sections)}] {sec['title']} → {len(body)} 字")
        bodies_path.write_text(
            json.dumps(bodies, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    bodies = json.loads(bodies_path.read_text(encoding="utf-8"))
    assert len(bodies) == len(sections), "正文条数与章节数不一致"

    full_path = work / "full.json"
    if not full_path.exists():
        size = group_size(len(sections))
        full_parts: list[str] = []
        for gi in range(0, len(sections), size):
            chunk = list(zip(sections[gi : gi + size], bodies[gi : gi + size]))
            part = write_full(client, chunk, style["spoken"], index=gi // size + 1)
            full_parts.append(part)
            log(f"  全文整理 [{gi // size + 1}] → {len(part)} 字")
        full_path.write_text(
            json.dumps(full_parts, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
    return bodies, json.loads(full_path.read_text(encoding="utf-8"))
