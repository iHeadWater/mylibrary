"""② 转写：faster-whisper 本地跑。

选 ``small`` + CPU int8 是权衡后的结果：``medium`` 在 CPU 上跑 50 分钟片子要
大半小时，而校对那一步（③）本来就会修掉识别错字，转写不必追求极致准确。

模型权重约 500MB，放仓库内 ``models/``（已 gitignore），首跑自动下载。

音频**自己用 ffmpeg 解**，不走 faster-whisper 内部的 PyAV：PyAV 14 之后去掉了
``av.open`` 的 ``metadata_errors`` 参数，而 PyPI 上 faster-whisper 1.2.1 的
``decode_audio`` 还在传它，装到新版 PyAV 上就是一句 ``TypeError`` 直接崩在转写
开头。ffmpeg 本来就是这条流水线的硬依赖（抽帧），借它解一次 16k 单声道就够了。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

MODEL_NAME = "small"
SAMPLE_RATE = 16000


def load_model(
    models_dir: Path,
    *,
    name: str = MODEL_NAME,
    device: str = "cpu",
    compute_type: str = "int8",
):
    try:
        from faster_whisper import WhisperModel
    except ModuleNotFoundError as exc:  # pragma: no cover - 缺可选依赖时的提示
        raise RuntimeError(
            "缺少 faster-whisper：用 `uv run --extra video-notes python -m "
            "hydrolitagent.literature.video_notes ...` 运行"
        ) from exc
    models_dir.mkdir(parents=True, exist_ok=True)
    return WhisperModel(
        name, device=device, compute_type=compute_type, download_root=str(models_dir)
    )


def decode_audio(video: Path, *, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """整轨 → 16k 单声道 float32。50 分钟约 190MB，一次进内存比切块省事。"""
    from .frames import ffmpeg_bin

    raw = subprocess.run(
        [
            ffmpeg_bin(),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(video),
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32)


def transcribe(
    video: Path,
    models_dir: Path,
    *,
    language: str = "zh",
    beam_size: int = 5,
    log=print,
) -> list[dict]:
    model = load_model(models_dir)
    segments, _info = model.transcribe(
        decode_audio(video),
        language=language,
        vad_filter=True,
        beam_size=beam_size,
        condition_on_previous_text=False,
    )
    return [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in segments
        if s.text.strip()
    ]


def ensure_transcript(
    work: Path, video: Path, models_dir: Path, *, log=print
) -> list[dict]:
    """``transcript.json`` 是逐字稿唯一事实源，已有就不再转。"""
    path = work / "transcript.json"
    if not path.exists():
        log("[2] 转写…")
        segs = transcribe(video, models_dir)
        path.write_text(
            json.dumps(segs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    segs = json.loads(path.read_text(encoding="utf-8"))
    log(f"[2] {len(segs)} 段，{sum(len(s['text']) for s in segs)} 字")
    return segs
