"""③ 校对：分块修错字，再把碎句合并成「段讲解」。

ASR 出来的是断断续续的一两句话一条，直接喂给 ④ 会让模型看到上百条碎片。
这里按**时间空隙**和**字数**合成块：讲到一处停顿超过 2.5 秒，或者一块已经
攒了 320 字，就切下一块。

注意合并给的是 20 来块（50 分钟片子），④ 拿到的段号就按这个粒度算 ——
早期有人误判「规划只覆盖 4.6%」，是把这里的块数当成了 ASR 条数。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import fmt

GROUP = 12
GAP = 2.5
MAX_CHARS = 320

PROMPT = (
    "你是视频逐字稿校对器。修正明显的语音识别错误（错别字、同音字、专有名词），"
    "删除不影响原意的口头填充和重复，修复断句与标点，使文字自然书面化。"
    "不得概括、扩写、翻译、增删实质内容，保持简体中文。"
    "输入是 JSON 数组，每项 {id, text}；输出 JSON 对象 "
    '{"segments":[{"id":同数字,"text":"校对后的文本"}]}，id 必须与输入一一对应。\n\n'
)


def proofread(client, segs: list[dict], *, group: int = GROUP, log=print) -> list[dict]:
    """逐块校对。任一块解析失败就保留该块原文 —— 宁可留着错字，不要丢内容。"""
    out: list[dict] = []
    for i in range(0, len(segs), group):
        chunk = segs[i : i + group]
        payload = json.dumps(
            [{"id": j, "text": s["text"]} for j, s in enumerate(chunk)],
            ensure_ascii=False,
        )
        raw = client.ask(
            PROMPT + payload, max_tokens=6000, temperature=0, json_mode=True
        )
        try:
            by_id = {
                int(x["id"]): str(x["text"]).strip()
                for x in json.loads(raw)["segments"]
            }
        except Exception as exc:  # noqa: BLE001
            log(f"  校对解析失败，保留原文：{exc}")
            by_id = {}
        for j, s in enumerate(chunk):
            out.append({**s, "text": by_id.get(j) or s["text"]})
        log(f"  {i + len(chunk)}/{len(segs)}")
    return out


def merge_blocks(
    segs: list[dict], *, gap: float = GAP, max_chars: int = MAX_CHARS
) -> list[dict]:
    """碎句 → 段落块。纯函数，④ 的段号就是这个列表的下标 +1。"""
    if not segs:
        return []
    blocks: list[dict] = []
    cur = {"start": segs[0]["start"], "end": segs[0]["end"], "text": segs[0]["text"]}
    for s in segs[1:]:
        if s["start"] - cur["end"] > gap or len(cur["text"]) > max_chars:
            blocks.append(cur)
            cur = {"start": s["start"], "end": s["end"], "text": s["text"]}
        else:
            cur["end"] = s["end"]
            # 上一句以句末标点结尾就直接接上，否则补空格分开
            cur["text"] += s["text"] if cur["text"][-1:] in "。！？；" else " " + s["text"]
    blocks.append(cur)
    return blocks


def render(blocks: list[dict]) -> str:
    """段落块 → ``[段号] 时间｜正文`` 的多行文本，喂给 ④⑤ 的素材格式。"""
    return "\n".join(
        f"[{i}] {fmt(b['start'])}｜{b['text']}" for i, b in enumerate(blocks, 1)
    )


def ensure_polished(work: Path, segs: list[dict], client, *, log=print) -> list[dict]:
    path = work / "polished.json"
    if not path.exists():
        log("[3] 校对…")
        polished = proofread(client, segs, log=log)
        path.write_text(
            json.dumps(polished, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def strip_heading(text: str) -> str:
    """模型偶尔自作主张加 ``## 标题``，正文里不需要。"""
    return re.sub(r"^##\s.*\n+", "", text).strip()
