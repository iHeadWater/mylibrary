"""命令行入口：``run`` / ``setup`` / ``import``。

    uv run --extra video-notes python -m hydrolitagent.literature.video_notes setup
    uv run --extra video-notes python -m hydrolitagent.literature.video_notes run BV1REx46NEc4
    uv run --extra video-notes python -m hydrolitagent.literature.video_notes import BV1REx46NEc4 --into-vault

``run`` 只负责生成，产物在 ``<literature_root>/video-notes/<BV号>/``。**看过之后**
再 ``import --into-vault`` 才会写进 vault 的 ``sources/videos/``，这道人工门与主题的
「人工筛选门」是同一个道理：生成不等于入库。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from pathlib import Path

from hydrolitagent._config import PROJECT_ROOT
from hydrolitagent.literature._paths import resolve_literature_root

from . import asr, assemble, bodies as bodies_mod, download, frames, layout, outline, proofread
from .client import DeepSeek

MODELS_DIR = PROJECT_ROOT / "models"
VAULT_SOURCES = Path("sources") / "videos"
VAULT_MEDIA = Path("media") / "videos"


def work_dir(bv: str, override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    return resolve_literature_root() / "video-notes" / bv


def make_log(quiet: bool):
    def noop(_msg: str) -> None:
        return None

    def emit(msg: str) -> None:
        print(msg, flush=True)

    return noop if quiet else emit


# ---------------------------------------------------------------- run
def cmd_run(args) -> int:
    log = make_log(args.quiet)
    client = DeepSeek()
    bv = args.bv
    work = work_dir(bv, args.work_dir)
    for sub in ("frames", "images"):
        (work / sub).mkdir(parents=True, exist_ok=True)

    meta = download.prepare(work, bv, log=log)
    video = work / "media.mp4"
    segs = asr.ensure_transcript(work, video, MODELS_DIR, log=log)
    polished = proofread.ensure_polished(work, segs, client, log=log)
    blocks = proofread.merge_blocks(polished)
    log(f"[3] 合并成 {len(blocks)} 段讲解")

    sections = outline.ensure_outline(work, blocks, meta, client, log=log)
    written, full_parts = bodies_mod.ensure_bodies(
        work, sections, blocks, meta, client, log=log
    )
    shots = frames.ensure_shots(work, video, meta, client, log=log)
    arranged = layout.ensure_layout(
        work, sections, written, blocks, shots, client, log=log
    )
    summary = assemble.write_note(
        work,
        meta,
        sections,
        written,
        arranged,
        full_parts,
        usage=client.summary(),
        shots=shots,
        blocks=len(blocks),
        log=log,
    )
    print(json.dumps(summary, ensure_ascii=False))

    if args.clean_media:
        video.unlink(missing_ok=True)
        log("[1] 已删除 media.mp4（--clean-media）")
    return 0


# ---------------------------------------------------------------- setup
def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return ""


def cmd_setup(args) -> int:
    rows: list[tuple[bool, str]] = []

    rows.append(
        (
            find_spec("yt_dlp") is not None,
            f"yt-dlp {_pkg_version('yt-dlp') or '（未安装）'} —— 下载与取章节",
        )
    )
    rows.append(
        (
            find_spec("faster_whisper") is not None,
            f"faster-whisper {_pkg_version('faster-whisper') or '（未安装）'} —— 转写",
        )
    )
    try:
        ff = frames.ffmpeg_bin()
        rows.append((True, f"{ff} —— 抽帧"))
    except RuntimeError:
        rows.append((False, "ffmpeg 不在 PATH —— 抽帧"))

    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    rows.append((bool(key), "DEEPSEEK_API_KEY —— 校对 / 切章 / 写正文 / 看图"))
    if key and not args.no_api_check:
        try:
            DeepSeek().ask("回复一个字：好", max_tokens=4, temperature=0)
            rows.append((True, "DeepSeek 接口连通"))
        except Exception as exc:  # noqa: BLE001
            rows.append((False, f"DeepSeek 接口不通：{exc!r}"))

    for ok, text in rows:
        print(f"{'OK  ' if ok else 'FAIL'} {text}")
    print(f"\nwhisper 模型目录：{MODELS_DIR}")
    print("首次转写会把 small（约 500MB）下到这里，之后复用。")
    if args.fetch_model:
        print("正在准备 whisper 模型…")
        asr.load_model(MODELS_DIR)
        print("模型就绪。")
    return 0 if all(ok for ok, _ in rows) else 1


# ---------------------------------------------------------------- import
def append_log(vault: Path, entry: str) -> Path:
    path = vault / "log.md"
    text = path.read_text(encoding="utf-8") if path.exists() else "# 变更日志\n"
    today = time.strftime("%Y-%m-%d")
    heading = f"## {today}"
    if heading in text:
        text = text.replace(heading, f"{heading}\n{entry}", 1)
    else:
        text = text.rstrip("\n") + f"\n\n{heading}\n{entry}\n"
    path.write_text(text, encoding="utf-8")
    return path


def cmd_import(args) -> int:
    log = make_log(args.quiet)
    bv = args.bv
    work = work_dir(bv, args.work_dir)
    note = work / "note.md"
    if not note.exists():
        print(f"{note} 不存在，先跑 run {bv}", file=sys.stderr)
        return 2

    vault = (
        Path(args.vault).expanduser() if args.vault else resolve_literature_root()
    )
    dest_note = vault / VAULT_SOURCES / f"{bv}.md"
    media = vault / VAULT_MEDIA / bv
    images = sorted((work / "images").glob("*.jpg"))

    if not args.into_vault:
        print(f"预演：会写入 {dest_note}")
        print(f"        和 {len(images)} 张图 → {media}/")
        print("        追加 log.md。确认无误后加 --into-vault 真正执行。")
        return 0
    if dest_note.exists() and not args.force:
        print(f"{dest_note} 已存在，加 --force 覆盖", file=sys.stderr)
        return 2

    text = assemble.to_vault_links(note.read_text(encoding="utf-8"), bv)
    dest_note.parent.mkdir(parents=True, exist_ok=True)
    media.mkdir(parents=True, exist_ok=True)
    dest_note.write_text(text, encoding="utf-8")
    for f in images:
        shutil.copy2(f, media / f.name)

    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
    entry = f"- 视频笔记「{meta['title']}」→ [[{bv}]]（{len(images)} 图）"
    log_path = append_log(vault, entry)
    log(f"已写入 {dest_note}")
    log(f"     {len(images)} 张图 → {media}/")
    log(f"     {log_path}")
    return 0


# ---------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m hydrolitagent.literature.video_notes",
        description="B 站教学视频 → 中文笔记 + 精确配图",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="从 BV 号跑到一份带配图的笔记")
    run.add_argument("bv")
    run.add_argument("--work-dir", help="产物目录，默认 <literature_root>/video-notes/<BV号>")
    run.add_argument("--clean-media", action="store_true", help="跑完删掉 media.mp4")
    run.add_argument("--quiet", action="store_true", help="只打最后一行摘要")
    run.set_defaults(func=cmd_run)

    setup = sub.add_parser("setup", help="检查依赖、ffmpeg、密钥与模型目录")
    setup.add_argument("--fetch-model", action="store_true", help="顺便下载 whisper small")
    setup.add_argument("--no-api-check", action="store_true", help="跳过接口连通性检查")
    setup.set_defaults(func=cmd_setup)

    imp = sub.add_parser("import", help="把生成的笔记导入 vault（人工确认之后）")
    imp.add_argument("bv")
    imp.add_argument("--into-vault", action="store_true", help="真正写入；不加只预演")
    imp.add_argument("--vault", help="vault 根，默认 literature_root")
    imp.add_argument("--work-dir", help="产物目录，默认 <literature_root>/video-notes/<BV号>")
    imp.add_argument("--force", action="store_true", help="覆盖 vault 里已有的同名笔记")
    imp.add_argument("--quiet", action="store_true")
    imp.set_defaults(func=cmd_import)
    return p


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
