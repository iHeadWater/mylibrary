"""本地音视频文件：指纹、探测、入库。

B 站视频有 BV 号当稳定身份，本地文件没有。拿文件名当身份有两个毛病：改个名就
裂成两条笔记；两条不同的「会议记录.mp4」还会撞进同一个工作目录 —— 而
``prepare()`` 见到 ``meta.json`` 就跳过，等于静默产出另一条素材的笔记。

所以身份用内容指纹（大小 + 首尾各 4 MB 的 sha1）：3 GB 的会议录像也只读 8 MB，
秒级返回；改名不影响，内容变了自然换 id。

时长与「有没有视频流」用 PyAV 探测 —— faster-whisper 本来就依赖它，机器上没有
ffprobe 也不缺这一环。

原始件复制进仓库根的 ``media-library/``（vault 外、已 gitignore）。B 站下的视频是
本工具自己的缓存，跟着工作目录走，``--clean-media`` 能删；这里放的是你自己的素材，
两者性质不同，不混在一起。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from hydrolitagent._config import PROJECT_ROOT

from . import fmt
from .naming import folder_name

# 首尾各读这么多就够认人；整文件哈希在 3 GB 的会议录像上要十几秒，不值。
CHUNK = 4 * 1024 * 1024


def library_root() -> Path:
    """原始件仓库：仓库根 ``media-library/``。"""
    return PROJECT_ROOT / "media-library"


def fingerprint(path: Path) -> str:
    """``local-<10 位十六进制>``；只看大小与首尾各 4 MB。"""
    size = path.stat().st_size
    digest = hashlib.sha1()
    digest.update(str(size).encode("ascii"))
    with path.open("rb") as handle:
        digest.update(handle.read(CHUNK))
        if size > CHUNK * 2:
            handle.seek(-CHUNK, os.SEEK_END)
            digest.update(handle.read(CHUNK))
    return f"local-{digest.hexdigest()[:10]}"


def probe(path: Path) -> dict:
    """时长与流类型。打不开就抛 ``ValueError``，不用让上层的 ffmpeg 报错顶上来。"""
    try:
        import av
    except ImportError as exc:  # pragma: no cover - faster-whisper 必然带 av
        raise RuntimeError(
            "缺少 PyAV：它随 faster-whisper 一起装，请用 "
            "`uv run --extra video-notes` 运行"
        ) from exc

    try:
        with av.open(str(path)) as container:
            duration = float(container.duration or 0) / 1_000_000
            kinds = {stream.type for stream in container.streams}
    except Exception as exc:  # noqa: BLE001 - PyAV 的异常类型不统一
        raise ValueError(f"{path} 读不出音视频轨：{exc}") from exc
    return {
        "duration": round(duration, 1),
        "has_video": "video" in kinds,
        "has_audio": "audio" in kinds,
    }


def note_date(path: Path) -> str:
    """文件修改时间 → ``YYYY-MM-DD``。录音录像的 mtime 通常就是录制/落盘那天。"""
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def meta_for(path: Path, *, title: str | None = None, info: dict | None = None) -> dict:
    """本地文件 → 与 B 站同构的 ``meta.json``。``info`` 可传入以免重复探测。"""
    info = info or probe(path)
    return {
        "id": fingerprint(path),
        "source": "file",
        "title": (title or path.stem).strip(),
        "date": note_date(path),
        "duration": info["duration"],
        "uploader": None,
        "webpage_url": None,
        "chapters": [],
        "source_path": None,  # 入库之后才知道
        "original_path": str(path.resolve()),
    }


def rel_to_project(path: Path) -> str:
    """能相对仓库根表示就相对表示，meta.json 换台机器也还能读。"""
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def collect(src: Path, name: str) -> Path:
    """把原文件复制进库，返回库内路径。库里已有同名同大小的就复用。"""
    root = library_root()
    dest = root / f"{name}{src.suffix.lower()}"
    if dest.exists() and dest.resolve() == src.resolve():
        return dest
    if dest.exists():
        if dest.stat().st_size == src.stat().st_size:
            return dest
        raise FileExistsError(f"库里已有 {dest.name} 但大小不同；换 --title 区分")
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def media_path(meta: dict) -> Path:
    """``meta.json`` → 可读的媒体路径。找不回来说清楚，别让 ffmpeg 去报。"""
    raw = str(meta.get("source_path") or "")
    if not raw:
        raise ValueError("meta.json 里没有 source_path")
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"原始件已不在库里：{path}")
    return path


def prepare(work: Path, meta: dict, *, log=print) -> dict:
    """确保 ``work`` 下有 ``meta.json``、原始件在库里。返回最终生效的 meta。"""
    path = work / "meta.json"
    if path.is_file():
        meta = json.loads(path.read_text(encoding="utf-8"))
    else:
        work.mkdir(parents=True, exist_ok=True)
        stored = collect(Path(meta["original_path"]), folder_name(meta))
        meta["source_path"] = rel_to_project(stored)
        path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    log(f"[0] {meta['title']}  {fmt(meta['duration'])}")
    media = media_path(meta)
    log(f"[1] 媒体 {media}  {media.stat().st_size / 1e6:.1f} MB")
    return meta
