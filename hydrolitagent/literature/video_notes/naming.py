"""视频笔记叫什么叫这个文件说了算：草稿目录、vault 里的文件名、图片目录都用同一个名字。

为什么不能直接拿标题当文件名：

- 文件系统禁 `\\ / : * ? " < > |`，标题里全角标点、emoji、换行都可能出现；
- Obsidian 的双链里 `[ ] # ^ |` 会截断 `[[...]]` 语法，名字带这些字符链接就点不动；
- macOS 单个文件名按字节算 255，中文一字 3 字节，长标题（50 分钟的教程很常见）
  光标题就能撑爆，加上 `（BV号）` 和 `media/videos/` 前缀就更悬；
- 标题会被 UP 主改，BV 号永远不变 —— 所以名字里始终留一个 BV 号当锚。

因此统一格式：``清洗后的标题（BV号）``。可读、天然唯一（同一标题不同视频不会撞），
换了标题也是新目录，不会把旧产物的缓存搅在一起。
"""

from __future__ import annotations

import re

# 60 个字：中文按 3 字节算约 180 字节，加后缀还在 macOS 单文件 255 字节以内；
# Windows 的 MAX_PATH 按字符计，60 也留足了余量。
MAX_TITLE = 60

# 文件系统非法字符 + 会破坏 Obsidian 双链的字符
_ILLEGAL = re.compile(r"""[/\\:*?"<>|\[\]#^]""")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")
# 截断后不该留在末尾的标点
_TRAILING = " 　.．。、，,·-—"


def sanitize(title: str, *, max_len: int = MAX_TITLE) -> str:
    """标题 → 能安全当文件名的字符串。可能返回空串（标题全是非法字符时）。"""
    text = _CONTROL.sub(" ", title or "")
    text = _ILLEGAL.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    # 结尾的点在 Windows 上会静默丢字符，先自己去掉
    text = text.strip(" .．。")
    if len(text) > max_len:
        text = text[:max_len].rstrip(_TRAILING)
    return text


def folder_name(meta: dict) -> str:
    """``meta.json`` → ``标题（BV号）``；标题清洗后为空就只剩 BV 号。"""
    bv = str(meta.get("id") or "").strip()
    title = sanitize(str(meta.get("title") or ""))
    if not bv:
        raise ValueError("meta.json 里没有 id，无法起名")
    return f"{title}（{bv}）" if title else bv
