"""B 站教学视频 → 中文笔记 + 精确配图。

八步流水线，一步一个模块：

① ``download``   yt-dlp 取元信息、官方章节、下载媒体
② ``asr``        faster-whisper 转写（本地 small，CPU int8）
③ ``proofread``  分块校对逐字稿，合并成带时间戳的段落
④ ``outline``    通读全部逐字稿切章节，校验 100% 覆盖
⑤ ``bodies``     逐节写正文，只依据本节素材；再写「全文整理」
⑥ ``frames``     全片每 4 秒抽一帧，逐张看图写画面描述
⑦ ``layout``     用真实画面清单匹配段落，决定插图位置
⑧ ``assemble``   拼装 Markdown / HTML

顺序不是排着玩的：⑤ 依赖 ④（写作要按章节切），⑥⑦ 依赖 ⑤（配图要匹配
**已经写好的**段落）。⑦ 的做法是「先看画面有什么，再决定它属于哪一段」，
而不是「先猜这段该有什么画面，再去截图」—— 后者是这条路走通之前的样子。

用法::

    uv run --extra video-notes python -m hydrolitagent.literature.video_notes setup
    uv run --extra video-notes python -m hydrolitagent.literature.video_notes run BV1REx46NEc4
    uv run --extra video-notes python -m hydrolitagent.literature.video_notes import BV1REx46NEc4 --into-vault

产物落 ``<literature_root>/video-notes/<BV号>/``。**生成不等于入库**：看过之后
再用 ``import --into-vault`` 送进 vault 的 ``sources/videos/``。
"""

from __future__ import annotations

__all__ = ["fmt"]


def fmt(sec: float) -> str:
    """秒 → ``mm:ss``。

    逐字稿、章节提示、进度日志共用这一个格式，注释里出现的时间戳才对得上。
    """
    return f"{int(sec) // 60:02d}:{int(sec) % 60:02d}"
