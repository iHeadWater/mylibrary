"""字幕文件 → 与 ``transcript.json`` 同构的分段。

本地视频常常自带字幕：有的话就不必再跑一遍 whisper —— 省几十分钟，而且人工校对
过的字幕通常比 small 模型更准。

编码是实打实的坑：中文字幕 GBK / GB18030 很常见，UTF-8 BOM 也不少见，所以按
``utf-8-sig`` → ``gb18030`` 的顺序试。``.ass`` 暂时不认：样式标签和浮动定位太多，
解析出来的时间轴未必对得上画面，宁可用 ASR。
"""

from __future__ import annotations

import re
from pathlib import Path

_TIMESTAMP = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
_TIME_LINE = re.compile(rf"{_TIMESTAMP}\s*-->\s*{_TIMESTAMP}")
# ``<i>`` 之类的富文本标签，以及 B 站字幕里的 ``{\an8}`` 定位指令
_MARKUP = re.compile(r"<[^>]+>|\{[^}]*\}")

SUFFIXES = (".srt", ".vtt")
_ALIASES = ("", ".zh", ".chs", ".zh-CN", ".zh-Hans")

Seg = dict[str, float | str]


def _seconds(hours: str, minutes: str, seconds: str, fraction: str) -> float:
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(fraction.ljust(3, "0")[:3]) / 1000
    )


def _block_to_seg(block: list[str]) -> Seg | None:
    """一个空行分隔的块 → 一段。块里找得到时间行就算数（VTT 的 cue 名同理跳过）。"""
    hit = next((i for i, line in enumerate(block) if _TIME_LINE.search(line)), None)
    if hit is None:
        return None
    match = _TIME_LINE.search(block[hit])
    body = " ".join(
        _MARKUP.sub("", line).strip() for line in block[hit + 1 :] if line.strip()
    ).strip()
    if not body:
        return None
    return {
        "start": round(_seconds(*match.group(1, 2, 3, 4)), 2),
        "end": round(_seconds(*match.group(5, 6, 7, 8)), 2),
        "text": body,
    }


def _parse_blocks(text: str) -> list[Seg]:
    segs: list[Seg] = []
    block: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip():
            block.append(line)
            continue
        seg = _block_to_seg(block)
        if seg is not None:
            segs.append(seg)
        block = []
    seg = _block_to_seg(block)
    if seg is not None:
        segs.append(seg)
    return segs


def parse_srt(text: str) -> list[Seg]:
    """SRT：空行分块，块内「序号 / 时间行 / 若干文本行」。"""
    return _parse_blocks(text)


def parse_vtt(text: str) -> list[Seg]:
    """VTT：把 ``WEBVTT`` 头与 ``NOTE`` 块切掉，其余与 SRT 同一套解析。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i, line in enumerate(lines):
        if _TIME_LINE.search(line):
            return _parse_blocks("\n".join(lines[i:]))
    return []


def decode(raw: bytes) -> str:
    """``utf-8-sig`` → ``gb18030``；都不行就认输。"""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("字幕编码认不出来（试过 utf-8 与 gb18030）")


def load(path: Path) -> list[Seg]:
    """读一个字幕文件 → 分段列表。"""
    text = decode(path.read_bytes())
    segs = parse_vtt(text) if path.suffix.lower() == ".vtt" else parse_srt(text)
    if not segs:
        raise ValueError(f"{path} 里没解出任何字幕段")
    return segs


def find_sibling(video: Path) -> Path | None:
    """视频旁边的同名字幕。``.zh`` / ``.chs`` 这类语言后缀也认。"""
    for alias in _ALIASES:
        for suffix in SUFFIXES:
            candidate = video.with_name(f"{video.stem}{alias}{suffix}")
            if candidate.is_file():
                return candidate
    return None
