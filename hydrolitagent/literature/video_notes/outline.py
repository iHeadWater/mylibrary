"""④ 切章节：通读全部逐字稿，按**内容**切，不设节数上下限。

只切章节，不预设「这里该是什么画面」—— 配图交给 ⑥⑦ 自己看画面决定。
早期版本在这一步让模型猜每节该配什么图，再按猜的时间去截图，效果远不如
后来的「先看每张画面是什么，再决定它属于哪一段」。

三道保险：模型可能只覆盖一部分段号，所以带一次重试；仍不覆盖就按字数等分兜底。
100% 覆盖是硬约束 —— 漏掉的段等于影片里有一段没进笔记。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import fmt
from .proofread import render

MAX_TITLE = 40
FALLBACK_SECTIONS = 8


def split_by_chars(items: list[dict], k: int) -> list[tuple[int, int]]:
    """按字数把 items 均分成 k 段，返回 1 基的 (起, 止) 段号。

    纯代码兜底，保证 100% 覆盖 —— 模型给不出合法规划时，至少不会丢内容。
    """
    total = sum(len(x["text"]) for x in items) or 1
    out: list[tuple[int, int]] = []
    start, acc = 1, 0
    for i, x in enumerate(items, 1):
        acc += len(x["text"])
        if acc * k >= total * (len(out) + 1) and len(out) < k - 1:
            out.append((start, i))
            start = i + 1
    out.append((start, len(items)))
    return out


def tidy_sections(raw_secs: list, n_blocks: int) -> list[dict]:
    """丢掉段号非法/越界的条目，按起始段号排序。"""
    out: list[dict] = []
    for s in raw_secs:
        try:
            a, b = int(s.get("from")), int(s.get("to"))
        except (TypeError, ValueError):
            continue
        if 1 <= a <= b <= n_blocks:
            out.append(
                {
                    "title": str(s.get("title") or "").strip()[:MAX_TITLE],
                    "from": a,
                    "to": b,
                }
            )
    out.sort(key=lambda s: s["from"])
    return out


def covers_all(secs: list[dict], n_blocks: int) -> bool:
    """首节从 1 起、末节到 n 止、相邻严丝合缝。任何一条不满足都算规划失败。"""
    if not secs:
        return False
    if secs[0]["from"] != 1 or secs[-1]["to"] != n_blocks:
        return False
    return all(y["from"] == x["to"] + 1 for x, y in zip(secs, secs[1:]))


def build_prompt(blocks: list[dict], meta: dict) -> str:
    n = len(blocks)
    chap = meta.get("chapters") or []
    chap_hint = ""
    if chap:
        chap_hint = (
            "\n作者自己在视频里划了这几个大段，可以作为骨架参考，"
            "但每一大段内部往往还有好几个独立话题，该拆就接着拆：\n"
            + "\n".join(f"  {fmt(c['start'])} {c['title']}" for c in chap)
            + "\n"
        )
    return f"""下面是一期教学视频校对后的分段讲解。请按**内容**把它切成若干节。
{chap_hint}
切的原则：一节只讲一个独立话题。换话题就切开，同一个话题不要拆成两节。
节数由内容决定，不要为了凑成某个固定数量把几个话题硬合并——视频越长，节数自然越多。

每节给一个有信息量的小标题，并且用 from / to 指出它覆盖哪几段（段号从 1 开始）。
禁止「视频内容」「总结」「第一部分」这类空标题。

分段讲解（[段号] 时间 正文）：
{render(blocks)}

输出 JSON 对象：
{{"sections":[{{"title":"小标题","from":起始段号,"to":结束段号}}]}}

硬性要求：首节 from=1，末节 to={n}；相邻两节满足 后一节 from == 前一节 to + 1；
不得重叠、不得留空、不得只写前几段。只输出 JSON。"""


def fallback(blocks: list[dict], k: int = FALLBACK_SECTIONS) -> list[dict]:
    """模型两次都没覆盖全 → 按字数等分。标题沿用模型给过的，剩下的编号补。"""
    return [
        {"title": f"第 {i + 1} 部分", "from": a, "to": b}
        for i, (a, b) in enumerate(split_by_chars(blocks, k))
    ]


def plan(client, blocks: list[dict], meta: dict, *, log=print) -> list[dict]:
    n = len(blocks)
    base = build_prompt(blocks, meta)
    sections: list[dict] = []
    for attempt in (1, 2):
        prompt = (
            base
            if attempt == 1
            else base + f"\n\n【上次的规划只覆盖了部分段号，这次必须从 1 连续覆盖到 {n}】"
        )
        raw = client.ask(prompt, max_tokens=1500, temperature=0.2, json_mode=True)
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            sections = tidy_sections(
                json.loads(m.group(0) if m else raw)["sections"], n
            )
        except Exception as exc:  # noqa: BLE001
            log(f"  规划解析失败：{exc}")
            sections = []
        if covers_all(sections, n):
            break
        cov = f"{sections[0]['from']}–{sections[-1]['to']}" if sections else "无"
        log(f"  第 {attempt} 次只覆盖 {cov}，重试")

    if not covers_all(sections, n):
        # 保留模型给过的标题，剩下的编号补齐：等分切法丢掉标题太可惜
        titles = [s["title"] for s in sections][:FALLBACK_SECTIONS]
        sections = [
            {
                "title": (titles[i] if i < len(titles) else "") or f"第 {i + 1} 部分",
                "from": a,
                "to": b,
            }
            for i, (a, b) in enumerate(split_by_chars(blocks, FALLBACK_SECTIONS))
        ]
        log(f"  改用等分兜底：{len(sections)} 节")
    return sections


def ensure_outline(
    work: Path, blocks: list[dict], meta: dict, client, *, log=print
) -> list[dict]:
    path = work / "outline.json"
    if not path.exists():
        log("[4] 通读逐字稿，按内容切章节…")
        sections = plan(client, blocks, meta, log=log)
        path.write_text(
            json.dumps({"sections": sections}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    sections = json.loads(path.read_text(encoding="utf-8"))["sections"]
    assert covers_all(sections, len(blocks)), "规划没有覆盖全部逐字稿"
    log(f"[4] {len(sections)} 节：" + " / ".join(s["title"] for s in sections))
    return sections
