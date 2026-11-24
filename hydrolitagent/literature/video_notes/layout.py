"""⑦ 配图编排：拿**真实画面清单** + **已写好的段落**，让模型把图对到段上。

关键点：先看每张画面是什么，再决定它属于哪一段；而不是先猜「这段该有什么画面」
再回去截图。后者是这条路走通之前的样子，图文对不上是常态。

数量不设限 —— 有几段说得清就配几张，宁可少，不要凑。代码这边只保留两条硬约束：
1. **顺序**：段落往后走，画面时间只能往后走；
2. **去重**：同一张不重复用，内容几乎相同的也只留一张。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .frames import LOGO_WORDS

TOLERANCE = 2  # 模型给的秒数允许 ±2 秒偏差，就近吸附到真实帧
HEAD = 8  # 判重时比较描述的前 8 个非空白字符
PROMPT = """下面是一节视频笔记的正文段落，和这一节时间范围内的真实画面清单。

请从画面清单里挑图，插到段落之间当配图。唯一的标准是：
**这张图上画的东西，正好是它旁边那段文字在讲的东西。** 能解释清楚就选，解释不清楚就不选。
数量不设限——有 5 段都值得配图就配 5 张；只有 1 段配得上就配 1 张；宁可少，不要凑。

段落（按顺序）：
{paras}

画面清单（秒数｜画面内容）：
{shots}

补充要求：
- 用清单里已有的秒数，不要编秒数，同一张不要用两次。
- `para` 表示插在第几段之后（1 起）。
- 段落越往后，挑的画面秒数应当越大，不要出现后面的段配了更早的画面。
- 内容重复的画面只留一张；片头、纯字幕、没有信息量的画面不要选。

输出 JSON 对象：
{{"items":[{{"para":段号,"t":秒数,"why":"这一张为什么能解释这一段，12 字以内"}}]}}"""


def split_paras(body: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]


def candidates(
    shots: list[dict], t0: float, t1: float, *, logo_words=LOGO_WORDS
) -> list[dict]:
    """本节时间范围内、能当配图、且不是片头台标的帧。"""
    return [
        s
        for s in shots
        if t0 <= s["t"] <= t1
        and s["usable"]
        and s["desc"]
        and not any(w in s["desc"] for w in logo_words)
    ]


def accept_items(items: list, n_paras: int, cands: list[dict]) -> list[dict]:
    """校验模型挑的图：段落合法、秒数吸附到真实帧、时间与段落单调、内容去重。

    纯函数 —— 这里是配图质量的最后一道硬约束，单独可测。
    """
    valid: list[dict] = []
    seen_t: set[int] = set()
    picked: list[str] = []
    last_t, last_p = -1, 0
    for it in items:
        try:
            p, t = int(it.get("para")), int(it.get("t"))
        except (TypeError, ValueError):
            continue
        if not 1 <= p <= n_paras or t in seen_t:
            continue
        hit = next((c for c in cands if abs(c["t"] - t) <= TOLERANCE), None)
        if not hit or hit["t"] <= last_t or p < last_p:  # 段落与画面必须同向推进
            continue
        head = re.sub(r"\W", "", hit["desc"])[:HEAD]
        if any(re.sub(r"\W", "", q)[:HEAD] == head for q in picked):  # 内容重复只留一张
            continue
        seen_t.add(t)
        picked.append(hit["desc"])
        last_t, last_p = hit["t"], p
        valid.append({"para": p, "t": hit["t"], "desc": hit["desc"]})
    return valid


def arrange(
    client,
    sections: list[dict],
    bodies: list[str],
    blocks: list[dict],
    shots: list[dict],
    *,
    log=print,
) -> list[dict]:
    layout: list[dict] = []
    for si, (sec, body) in enumerate(zip(sections, bodies)):
        paras = split_paras(body)
        t0 = blocks[sec["from"] - 1]["start"]
        t1 = blocks[sec["to"] - 1]["end"]
        cands = candidates(shots, t0, t1)
        if not cands or not paras:
            layout.append({"section": si + 1, "items": []})
            log(f"  第 {si + 1} 节 → 无可用画面")
            continue
        raw = client.ask(
            PROMPT.format(
                paras="\n".join(f"段{j + 1}：{p}" for j, p in enumerate(paras)),
                shots="\n".join(f"{c['t']}s｜{c['desc']}" for c in cands),
            ),
            max_tokens=1200,
            temperature=0.2,
            json_mode=True,
        )
        try:
            items = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))["items"]
        except Exception:  # noqa: BLE001
            items = []
        valid = accept_items(items, len(paras), cands)
        layout.append({"section": si + 1, "items": valid})
        log(
            f"  第 {si + 1} 节 → {len(valid)} 张："
            + "，".join(f"段{v['para']}@{v['t']}s {v['desc']}" for v in valid)
        )
    return layout


def ensure_layout(
    work: Path,
    sections: list[dict],
    bodies: list[str],
    blocks: list[dict],
    shots: list[dict],
    client,
    *,
    log=print,
) -> list[dict]:
    path = work / "layout.json"
    if not path.exists():
        log("[7] 配图编排…")
        layout = arrange(client, sections, bodies, blocks, shots, log=log)
        path.write_text(
            json.dumps(layout, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    return json.loads(path.read_text(encoding="utf-8"))
