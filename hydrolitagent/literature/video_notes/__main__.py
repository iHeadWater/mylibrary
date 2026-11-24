"""命令行入口：``run`` / ``setup`` / ``import``。

``run`` 收两种素材：B 站 BV 号，或任意本地音视频文件。两者只是入口不同，转写之后
的链路完全一样 —— 这也是为什么加它只需要动入口，不必碰后半段。

    uv run --extra video-notes python -m hydrolitagent.literature.video_notes setup
    uv run --extra video-notes python -m hydrolitagent.literature.video_notes run BV1REx46NEc4
    uv run --extra video-notes python -m hydrolitagent.literature.video_notes run ~/周会.mp4
    uv run --extra video-notes python -m hydrolitagent.literature.video_notes import BV1REx46NEc4 --into-vault

``run`` 只负责生成，产物在 ``<literature_root>/video-notes/<名字>/``。**看过之后**
再 ``import --into-vault`` 才会写进 vault 的 ``sources/videos/``，这道人工门与主题的
「人工筛选门」是同一个道理：生成不等于入库。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from pathlib import Path

from hydrolitagent._config import PROJECT_ROOT
from hydrolitagent.literature._paths import resolve_literature_root

from . import (
    asr,
    assemble,
    bodies as bodies_mod,
    download,
    frames,
    layout,
    local,
    outline,
    proofread,
    subs as subs_mod,
)
from .client import DeepSeek
from .naming import folder_name

MODELS_DIR = PROJECT_ROOT / "models"
VAULT_SOURCES = Path("sources") / "videos"
VAULT_MEDIA = Path("media") / "videos"
BV_PATTERN = re.compile(r"^BV[0-9A-Za-z]{10}$")


def video_notes_root() -> Path:
    return resolve_literature_root() / "video-notes"


def read_meta(work: Path) -> dict:
    return json.loads((work / "meta.json").read_text(encoding="utf-8"))


def existing_work(key: str) -> Path | None:
    """按素材 id 在 ``video-notes/`` 下找已有目录。

    目录名现在是标题拼出来的，算不回去，只能反过来扫一遍 ``meta.json``。顺带的
    好处是以前用 BV 号命名、现在还没迁移的旧目录照样找得到。
    """
    root = video_notes_root()
    if not root.is_dir():
        return None
    for d in sorted(root.iterdir()):
        meta_path = d / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if meta.get("id") == key:
            return d
    return None


def work_for_run(bv: str, override: str | None) -> tuple[Path, dict | None]:
    """定下这次跑哪个目录。已有就复用，没有就按标题新建。"""
    if override:
        path = Path(override).expanduser()
        meta_path = path / "meta.json"
        return path, (read_meta(path) if meta_path.is_file() else None)
    existing = existing_work(bv)
    if existing is not None:
        return existing, read_meta(existing)
    meta = download.fetch_meta(bv)
    return video_notes_root() / folder_name(meta), meta


def resolve_target(target: str) -> tuple[str, Path | None]:
    """``BV1xxxxxxxxx`` 还是本地文件。

    存在的文件优先当文件 —— BV 号不可能是一个存在的路径，反过来「路径没写错但
    恰好长得像 BV 号」的概率可以忽略。
    """
    path = Path(target).expanduser()
    if path.is_file():
        return "file", path
    if BV_PATTERN.match(target):
        return "bilibili", None
    raise SystemExit(f"既不是 BV 号也不是可读文件：{target}")


def guard_work(work: Path, key: str) -> None:
    """目录已被别的素材占用就停下。

    不然 ``prepare()`` 会读到别人的 ``meta.json`` 并一路用下去 —— 静默产出一条
    讲错视频的笔记，比对不上名字难查得多。
    """
    meta_path = work / "meta.json"
    if not meta_path.is_file():
        return
    try:
        other = json.loads(meta_path.read_text(encoding="utf-8")).get("id")
    except (OSError, ValueError):
        return
    if other and other != key:
        raise SystemExit(
            f"{work} 里已有另一条素材（id={other}），换 --title 或 --work-dir"
        )


def subs_for(target: Path, args) -> Path | None:
    """这次用哪份字幕：显式指定 → 同级同名 → 没有。"""
    if args.no_subs:
        return None
    if args.subs:
        path = Path(args.subs).expanduser()
        if not path.is_file():
            raise SystemExit(f"字幕文件不存在：{path}")
        return path
    return subs_mod.find_sibling(target)


def prepare_run(target: str, args, log) -> tuple[Path, dict, Path, Path | None]:
    """把「要跑什么」翻译成「产物目录 + meta + 媒体路径 + 字幕」。

    BV 与本地文件只在这一处分岔，往后完全同一条链路。
    """
    kind, path = resolve_target(target)

    if kind == "bilibili":
        work, meta = work_for_run(target, args.work_dir)
        log(f"[0] 产物目录：{work}")
        meta = download.prepare(work, target, meta=meta, log=log)
        return work, meta, work / "media.mp4", None

    assert path is not None
    info = local.probe(path)
    if not info["has_video"]:
        raise SystemExit(
            f"{path} 里没有视频轨。纯音频的笔记形态（说话人分离、无配图排版）"
            "等 #90，这次先只收带画面的文件。"
        )
    meta = local.meta_for(path, title=args.title, info=info)
    work = (
        Path(args.work_dir).expanduser()
        if args.work_dir
        else existing_work(meta["id"]) or video_notes_root() / folder_name(meta)
    )
    guard_work(work, meta["id"])
    log(f"[0] 产物目录：{work}")
    meta = local.prepare(work, meta, log=log)
    return work, meta, local.media_path(meta), subs_for(path, args)


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
    work, meta, video, subs = prepare_run(args.target, args, log)
    for sub in ("frames", "images"):
        (work / sub).mkdir(parents=True, exist_ok=True)

    segs = asr.ensure_transcript(work, video, MODELS_DIR, subs=subs, log=log)
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
        if video.parent == work:
            video.unlink(missing_ok=True)
            log("[1] 已删除 media.mp4（--clean-media）")
        else:
            log("[1] 本地素材留在库里，--clean-media 只清 B 站下的缓存")
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
def append_log(vault: Path, entry: str, *, key: str) -> tuple[Path, bool]:
    """往 ``log.md`` 追加一条，同一条笔记不重复记。

    ``key`` 是笔记的双链目标。重复导入（或者导入前跑过 ``migrate``）会把同一
    条笔记记两遍，翻日志时看着像导了两次 —— 已有就跳过。

    返回 ``(路径, 是否真的写了)``。
    """
    path = vault / "log.md"
    text = path.read_text(encoding="utf-8") if path.exists() else "# 变更日志\n"
    if f"[[{key}]]" in text:
        return path, False
    today = time.strftime("%Y-%m-%d")
    heading = f"## {today}"
    if heading in text:
        text = text.replace(heading, f"{heading}\n{entry}", 1)
    else:
        text = text.rstrip("\n") + f"\n\n{heading}\n{entry}\n"
    path.write_text(text, encoding="utf-8")
    return path, True


def cmd_import(args) -> int:
    log = make_log(args.quiet)
    work = Path(args.work_dir).expanduser() if args.work_dir else None
    if work is None:
        if not args.target:
            print("要么给 BV 号 / 文件，要么给 --work-dir", file=sys.stderr)
            return 2
        kind, path = resolve_target(args.target)
        key = args.target if kind == "bilibili" else local.fingerprint(path)
        work = existing_work(key)
    if work is None or not (work / "note.md").exists():
        where = work if work is not None else video_notes_root()
        print(f"{where} 下没有 note.md，先跑一次 run", file=sys.stderr)
        return 2

    meta = read_meta(work)
    name = folder_name(meta)
    vault = (
        Path(args.vault).expanduser() if args.vault else resolve_literature_root()
    )
    dest_note = vault / VAULT_SOURCES / f"{name}.md"
    media = vault / VAULT_MEDIA / name
    images = sorted((work / "images").glob("*.jpg"))

    if not args.into_vault:
        print(f"预演：会写入 {dest_note}")
        print(f"        和 {len(images)} 张图 → {media}/")
        print("        追加 log.md。确认无误后加 --into-vault 真正执行。")
        return 0
    if dest_note.exists() and not args.force:
        print(f"{dest_note} 已存在，加 --force 覆盖", file=sys.stderr)
        return 2

    text = assemble.to_vault_links(note_text(work), name)
    dest_note.parent.mkdir(parents=True, exist_ok=True)
    media.mkdir(parents=True, exist_ok=True)
    dest_note.write_text(text, encoding="utf-8")
    for f in images:
        shutil.copy2(f, media / f.name)

    entry = f"- 视频笔记「{meta['title']}」→ [[{name}]]（{len(images)} 图）"
    log_path, written = append_log(vault, entry, key=name)
    log(f"已写入 {dest_note}")
    log(f"     {len(images)} 张图 → {media}/")
    log(f"     {log_path}" + ("" if written else "（已有该条记录，未重复追加）"))
    return 0


def note_text(work: Path) -> str:
    return (work / "note.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- migrate
def cmd_migrate(args) -> int:
    """把已生成的笔记从 BV 号命名改成「标题（BV号）」。默认只预演。

    要同时动三处：草稿目录、vault 里的笔记与图片目录、log.md 里的双链。
    任何一处目标已存在就整条跳过，不做部分迁移 —— 半迁状态比没迁更难收拾。
    """
    log = make_log(args.quiet)
    root = video_notes_root()
    vault = Path(args.vault).expanduser() if args.vault else resolve_literature_root()
    if not root.is_dir():
        print(f"{root} 不存在，没有可迁移的产物", file=sys.stderr)
        return 2

    plan: list[tuple[Path, Path, str]] = []
    for d in sorted(root.iterdir()):
        if not (d / "meta.json").is_file():
            continue
        name = folder_name(read_meta(d))
        if name != d.name:
            plan.append((d, d.with_name(name), name))

    if not plan:
        log("所有产物已经是标题命名，无需迁移。")
        return 0

    renamed: list[tuple[str, str]] = []
    for old_dir, new_dir, name in plan:
        note_old = vault / VAULT_SOURCES / f"{old_dir.name}.md"
        note_new = vault / VAULT_SOURCES / f"{name}.md"
        media_old = vault / VAULT_MEDIA / old_dir.name
        media_new = vault / VAULT_MEDIA / name
        log(f"  {old_dir.name}\n    → {name}")
        clash = next(
            (p for p in (new_dir, note_new, media_new) if p.exists()), None
        )
        if clash is not None:
            log(f"    跳过：{clash} 已存在")
            continue
        if not args.apply:
            continue

        old_dir.rename(new_dir)
        if media_old.is_dir():
            media_old.rename(media_new)
        if note_old.is_file():
            text = note_old.read_text(encoding="utf-8")
            text = text.replace(f"media/videos/{old_dir.name}/", f"media/videos/{name}/")
            note_old.rename(note_new)
            note_new.write_text(text, encoding="utf-8")
        renamed.append((old_dir.name, name))

    if not args.apply:
        log("\n以上是预演。确认无误后加 --apply 真正改名。")
        return 0

    log_path = vault / "log.md"
    if renamed and log_path.is_file():
        text = log_path.read_text(encoding="utf-8")
        for old, new in renamed:
            text = text.replace(f"[[{old}]]", f"[[{new}]]")
        log_path.write_text(text, encoding="utf-8")
        log(f"\n已迁移 {len(renamed)} 条，log.md 的双链一并更新。")
    return 0


# ---------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m hydrolitagent.literature.video_notes",
        description="B 站视频或本地音视频文件 → 中文笔记 + 精确配图",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="从 BV 号或本地文件跑到一份带配图的笔记")
    run.add_argument("target", help="BV 号，或本地音视频文件路径")
    run.add_argument("--title", help="本地文件的标题，默认取文件名")
    run.add_argument("--subs", help="用这份字幕文件代替转写（.srt / .vtt）")
    run.add_argument("--no-subs", action="store_true", help="忽略同级字幕，强制转写")
    run.add_argument(
        "--work-dir", help="产物目录，默认 <literature_root>/video-notes/<名字>"
    )
    run.add_argument("--clean-media", action="store_true", help="跑完删掉 media.mp4")
    run.add_argument("--quiet", action="store_true", help="只打最后一行摘要")
    run.set_defaults(func=cmd_run)

    setup = sub.add_parser("setup", help="检查依赖、ffmpeg、密钥与模型目录")
    setup.add_argument("--fetch-model", action="store_true", help="顺便下载 whisper small")
    setup.add_argument("--no-api-check", action="store_true", help="跳过接口连通性检查")
    setup.set_defaults(func=cmd_setup)

    imp = sub.add_parser("import", help="把生成的笔记导入 vault（人工确认之后）")
    imp.add_argument("target", nargs="?", help="BV 号或本地文件；给了 --work-dir 可省略")
    imp.add_argument("--into-vault", action="store_true", help="真正写入；不加只预演")
    imp.add_argument("--vault", help="vault 根，默认 literature_root")
    imp.add_argument("--work-dir", help="产物目录，默认按素材 id 自动找到")
    imp.add_argument("--force", action="store_true", help="覆盖 vault 里已有的同名笔记")
    imp.add_argument("--quiet", action="store_true")
    imp.set_defaults(func=cmd_import)

    migrate = sub.add_parser(
        "migrate", help="把已生成的笔记从 BV 号命名改成标题命名（默认只预演）"
    )
    migrate.add_argument("--apply", action="store_true", help="真正改名；不加只预演")
    migrate.add_argument("--vault", help="vault 根，默认 literature_root")
    migrate.add_argument("--quiet", action="store_true")
    migrate.set_defaults(func=cmd_migrate)
    return p


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
