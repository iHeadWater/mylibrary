"""① 下载：yt-dlp 取元信息、官方章节、媒体文件。

为什么必须落到本地，三条约束绕不过去：

1. B 站视频流 URL 有时效，且带防盗链（要 Referer），放一会儿就失效；
2. 抽帧要随机跳转 —— 第 9 节要 30:24 那一帧，靠 ``ffmpeg -ss`` 直接定位。
   在远端流上做，每次跳转都要重新协商，几十次之后极慢且易失败；
3. 转写要完整音轨，faster-whisper 读的就是本地文件。

视频自带的官方章节（``chapters``）只当骨架提示交给 ④ 参考，不直接当章节切分
—— 实测作者的粗划分往往一大段里含好几个独立话题。
"""

from __future__ import annotations

import json
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from . import fmt

VIDEO_URL = "https://www.bilibili.com/video/{bv}/"
MAX_HEIGHT = 720


def _ytdlp() -> list[str]:
    """用当前解释器跑 ``python -m yt_dlp``，不依赖 PATH 里有没有 console script。"""
    if find_spec("yt_dlp") is None:
        raise RuntimeError(
            "缺少 yt-dlp：用 `uv run --extra video-notes python -m "
            "hydrolitagent.literature.video_notes ...` 运行"
        )
    return [sys.executable, "-m", "yt_dlp"]


def video_url(bv: str) -> str:
    return VIDEO_URL.format(bv=bv)


def fetch_meta(bv: str) -> dict:
    """取元信息 + 官方章节。``chapters`` 可能为空（多数 UP 主不划）。"""
    out = subprocess.run(
        [*_ytdlp(), "--no-warnings", "-J", video_url(bv)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    m = json.loads(out)
    return {
        "id": bv,
        "title": m["title"],
        "duration": m["duration"],
        "uploader": m.get("uploader"),
        "webpage_url": m.get("webpage_url"),
        "chapters": [
            {"start": round(c["start_time"], 1), "title": c.get("title") or ""}
            for c in (m.get("chapters") or [])
        ],
        "description": (m.get("description") or "")[:500],
    }


def download_media(bv: str, dest: Path, *, max_height: int = MAX_HEIGHT) -> Path:
    """下视频轨 + 音频轨再合成 mp4。限高 720：抽帧只用来当配图，更高分辨率纯属浪费。"""
    subprocess.run(
        [
            *_ytdlp(),
            "--no-warnings",
            "-f",
            f"bv*[height<={max_height}]+ba/b[height<={max_height}]",
            "--merge-output-format",
            "mp4",
            "-o",
            str(dest),
            video_url(bv),
        ],
        check=True,
    )
    return dest


def write_meta(work: Path, meta: dict) -> dict:
    """把 meta 落到 ``meta.json``；已有文件就原样返回那份 —— 重跑以文件为准。"""
    path = work / "meta.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta


def prepare(work: Path, bv: str, *, meta: dict | None = None, log=print) -> dict:
    """确保 ``work`` 下有 ``meta.json`` 与 ``media.mp4``，已有就跳过。

    ``meta`` 允许由调用方先取好 —— 目录名要用标题算，所以 ``run`` 一定在
    建目录之前就拿到了元信息，这里不必再打一次网络。

    媒体默认**保留**：换章节切法、换抽帧步长都不必重新下载。清理交给
    ``--clean-media`` 由用户自己决定时机。
    """
    meta_path = work / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("id") not in (None, bv):
            raise RuntimeError(
                f"{work} 里是另一条素材（id={meta.get('id')}），请换 --work-dir"
            )
    else:
        meta = write_meta(work, meta or fetch_meta(bv))
    log(f"[0] {meta['title']}  {fmt(meta['duration'])}")

    video = work / "media.mp4"
    if not video.exists():
        log("[1] 下载…")
        download_media(bv, video)
    log(f"[1] 视频 {video.stat().st_size / 1e6:.1f} MB")
    return meta
