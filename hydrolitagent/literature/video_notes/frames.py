"""⑥ 抽帧 + 看图：全片每 4 秒一帧，逐张让视觉模型说明「画面里到底是什么」。

帧与时间一一对应，与章节怎么切**无关** —— 以后改章节切法不用重新看图。
这是踩过坑换来的：早期按节切分命名 ``s{节}_{秒}.jpg``，一改章节全部作废。

三秒内的相邻帧视为同一画面，直接沿用图注，省掉大量重复调用。
图注按批次增量落盘：50 分钟片子要看不见 1200 张，中途崩一次不能把前面的白干。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .client import data_uri

FRAME_STEP = 4
CAPTION_BATCH = 5
NEIGHBOUR = 3
# 这些描述说明画面没有信息量，配图阶段不必再考虑
LOGO_WORDS = ("片头", "标题画面", "纯黑", "台标")

CAPTION_PROMPT = (
    "上面是同一段中文教学视频的截图，按时间顺序。逐张说明画面里到底是什么：\n"
    "desc —— 不超过 18 字，只描述眼睛看得见的东西。是图表就写清图表讲什么"
    "（例如「成本函数曲线与C(w)公式」），是公式就写出公式，是界面就写界面元素。\n"
    "usable —— true 表示这张能当配图（画面里有具体的图表/公式/示意图/文字板/界面）；"
    "false 表示只是主讲人露脸、片头 logo、纯黑、纯字幕条。\n"
    '只输出 JSON 对象 {"items":[{"t":秒,"desc":"...","usable":true}]}，顺序对应。'
)


def frame_paths(work: Path, t: int) -> Path:
    return work / "frames" / f"f{t:04d}.jpg"


def ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError(
            "PATH 里找不到 ffmpeg：装好后重试（macOS 可下载静态构建放进 ~/.local/bin）"
        )
    return exe


def frame_times(duration: float, *, step: int = FRAME_STEP) -> list[int]:
    """全片固定网格。掐掉首尾各 2 秒，避开片头片尾的黑场。"""
    return list(range(2, int(duration) - 2, step))


def extract(video: Path, t: int, dest: Path) -> Path:
    """``-ss`` 放在 ``-i`` 前面：关键帧定位，跳转比解码到 t 秒快一个量级。"""
    subprocess.run(
        [
            ffmpeg_bin(),
            "-ss",
            str(t),
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "scale=1280:-2",
            "-q:v",
            "3",
            str(dest),
            "-y",
        ],
        check=True,
        capture_output=True,
    )
    return dest


def load_done(work: Path) -> dict[int, dict]:
    """读已有图注，顺带把旧的 ``s{节}_{秒}.jpg`` 命名改回按时间命名。"""
    path = work / "shots.json"
    if not path.exists():
        return {}
    done: dict[int, dict] = {}
    try:
        for s in json.loads(path.read_text(encoding="utf-8")):
            t = int(s["t"])
            old = work / "frames" / f"s{s.get('section', 0)}_{t:04d}.jpg"
            new = frame_paths(work, t)
            if old.exists() and not new.exists():
                old.rename(new)
            done[t] = {"t": t, "desc": str(s.get("desc") or ""),
                       "usable": bool(s.get("usable"))}
    except Exception:  # noqa: BLE001
        return {}
    return done


def ensure_shots(
    work: Path,
    video: Path,
    meta: dict,
    client,
    *,
    step: int = FRAME_STEP,
    log=print,
) -> list[dict]:
    path = work / "shots.json"
    done = load_done(work)

    todo: list[int] = []
    for t in frame_times(meta["duration"], step=step):
        if t in done:
            continue
        near = min(done, key=lambda x: abs(x - t)) if done else None
        if near is not None and abs(near - t) <= NEIGHBOUR and frame_paths(work, near).exists():
            shutil.copy2(frame_paths(work, near), frame_paths(work, t))
            done[t] = {**done[near], "t": t}  # 三秒内视为同一画面，沿用图注
        else:
            todo.append(t)
    all_times = frame_times(meta["duration"], step=step)
    log(f"[6] 共需 {len(all_times)} 帧，已有图注 {len(done)} 帧，待看 {len(todo)} 帧")

    for i in range(0, len(todo), CAPTION_BATCH):
        chunk = todo[i : i + CAPTION_BATCH]
        for t in chunk:
            dst = frame_paths(work, t)
            if not dst.exists():
                extract(video, t, dst)
        parts: list[dict] = []
        for t in chunk:
            parts.append({"type": "text", "text": f"第 {t} 秒："})
            parts.append(
                {"type": "image_url", "image_url": {"url": data_uri(frame_paths(work, t))}}
            )
        parts.append({"type": "text", "text": CAPTION_PROMPT})
        raw = client.ask_vision(parts, max_tokens=1800)
        try:
            got = json.loads(raw)
            items = got["items"] if isinstance(got, dict) and "items" in got else got
        except Exception:  # noqa: BLE001
            log(f"  图注解析失败：{raw[:100]}")
            items = []
        by_t = {round(float(x.get("t", -1))): x for x in items if isinstance(x, dict)}
        for t in chunk:
            x = by_t.get(t) or {}
            done[t] = {
                "t": t,
                "desc": str(x.get("desc") or "").strip()[:40],
                "usable": bool(x.get("usable")),
            }
        path.write_text(
            json.dumps([done[t] for t in sorted(done)], ensure_ascii=False, indent=1)
            + "\n",
            encoding="utf-8",
        )
        log(f"  看图 {min(i + CAPTION_BATCH, len(todo))}/{len(todo)}")

    shots = [done[t] for t in sorted(done)]
    log(f"[6] {len(shots)} 帧，其中可当配图 {sum(1 for s in shots if s['usable'])} 帧")
    return shots
