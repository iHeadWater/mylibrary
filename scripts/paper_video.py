"""Set up and run the mechanical stages of the paper-video project skill."""

import argparse
import hashlib
from importlib.util import find_spec
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".tmp" / "paper2video"
OUTPUT = ROOT / "outputs" / "paper2video"
UPSTREAM = "https://github.com/Lunamos/paper2video.git"
VOICE = "zh-CN-YunxiNeural"
AGENT_ROUTE = "For single-paper animated explainers, read [the paper-video skill](skills/paper-video/SKILL.md)."
FONT_FALLBACK = {
    "Inter": ("inter", "Arial"),
    "Caveat": ("caveat", "Segoe Print"),
    "JetBrainsMono": ("mono", "Consolas"),
    "SourceSerif4": ("serif", "Georgia"),
}


def write_json(path, data):
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run(directory, *command, capture=False):
    executable = shutil.which(str(command[0]))
    if not executable:
        raise ValueError(f"缺少命令 {command[0]}，请安装后重试")
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PAPER_VIDEO_ROOT": str(directory),
        "UV_CACHE_DIR": str(CACHE / "uv"),
        "UV_HTTP_TIMEOUT": "90",
        "UV_CONCURRENT_DOWNLOADS": "4",
        "npm_config_cache": str(CACHE / "npm"),
        "npm_config_fetch_retries": "3",
    }
    result = subprocess.run(
        [executable, *map(str, command[1:])],
        cwd=directory, env=env, check=True, text=True,
        encoding="utf-8", errors="replace", stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else None


def remotion(directory, *args):
    run(directory, remotion_launcher(directory), *args)


def remotion_launcher(directory):
    launcher = "remotion.cmd" if os.name == "nt" else "remotion"
    return directory / "node_modules" / ".bin" / launcher


def local_fonts(theme):
    """Replace the template's remote Latin font loaders with local CSS families."""
    source = theme.read_text(encoding="utf-8")
    for family, (variable, fallback) in FONT_FALLBACK.items():
        match = re.search(
            rf'import \{{ loadFont as (\w+) \}} from "@remotion/google-fonts/{family}";',
            source,
        )
        if match:
            source = source.replace(match[0], "")
            loader = match[1]
            source, replaced = re.subn(
                rf"const {variable} = {loader}\([^;]*\);",
                f"const {variable} = {{ fontFamily: {json.dumps(fallback)} }};",
                source,
            )
            if not replaced:
                raise ValueError(f"上游字体模板已变更：{family}")
            source = re.sub(rf"^{loader}\([^;]*\);\n?", "", source, flags=re.M)
    theme.write_text(source, encoding="utf-8")


def setup():
    CACHE.mkdir(parents=True, exist_ok=True)
    version = Path(tempfile.mkdtemp(prefix="install-", dir=CACHE))
    upstream = version / "upstream"
    run(version, "git", "clone", "--depth", "1", UPSTREAM, upstream)
    commit = run(upstream, "git", "rev-parse", "HEAD", capture=True)
    workshop = version / "workshop"
    skill = upstream / "skills" / "paper2video"
    shutil.copytree(skill / "template", workshop)
    shutil.copytree(skill / "scripts", workshop / "scripts")
    additions = read_json(workshop / "package.additions.json")
    dependencies = additions["dependencies"]
    remotion_version = dependencies["@remotion/media"]
    package = {
        "name": "mylibrary-paper-video",
        "private": True,
        "scripts": {"dev": "remotion studio"},
        "dependencies": {
            **dependencies, "remotion": remotion_version,
            "@remotion/cli": remotion_version, "react": "^19", "react-dom": "^19",
        },
        "devDependencies": {
            **additions.get("devDependencies", {}), "typescript": "^5.9",
            "@types/react": "^19", "@types/react-dom": "^19", "@types/node": "^22",
        },
    }
    write_json(workshop / "package.json", package)
    local_fonts(workshop / "src" / "theme" / "index.ts")
    run(workshop, "ffmpeg", "-version", capture=True)
    run(workshop, "ffprobe", "-version", capture=True)
    run(workshop, "npm", "install", "--no-audit", "--no-fund")
    write_json(workshop / "scenes.json", {
        "version": 2, "fps": 30,
        "voices": {"zh": {"backend": "edge", "voice": VOICE}},
        "scenes": [{"id": "s_example", "zh": {"lines": [
            {"id": "a", "text": "中文旁白和动画渲染检查"}
        ]}}],
    })
    run(workshop, sys.executable, "scripts/vo.py", "build", "--lang", "zh", "--backend", "edge")
    check_voice(workshop)
    run(workshop, sys.executable, "scripts/zh_breaks.py")
    remotion(workshop, "still", "VIDEO-ZH", "smoke.png", "--frame=15", "--log=error")
    instructions = ROOT / "AGENTS.md"
    existing = instructions.read_text(encoding="utf-8-sig") if instructions.exists() else ""
    if AGENT_ROUTE not in existing:
        with instructions.open("a", encoding="utf-8") as handle:
            handle.write(("\n\n" if existing else "") + AGENT_ROUTE + "\n")
    # Publish the selection only after both checks pass. Existing runs retain their version.
    write_json(CACHE / "active.json", {"directory": version.name, "commit": commit})
    print(f"paper2video 已就绪：{commit}")


def check_voice(directory):
    timeline = read_json(directory / "public/data/vo.zh.json")
    expected = [s["id"] for s in read_json(directory / "scenes.json")["scenes"] if "zh" in s]
    scenes = timeline["scenes"]
    if not expected or expected != [scene["id"] for scene in scenes]:
        raise ValueError("中文旁白时间轴与分镜不一致")
    for scene in scenes:
        audio = directory / "public" / scene.get("audio", "")
        if not scene.get("audio") or not audio.is_file() or not audio.stat().st_size:
            raise ValueError(f"缺少旁白：{scene['id']}")


def prepare(pdf, paper_input):
    source = {}
    if paper_input:
        source = read_json(paper_input)
        if source.get("status") != "READY":
            raise ValueError(source.get("message") or "Zotero PDF 尚未就绪")
        pdf = Path(source["pdf"]["local_path"])
    with pdf.open("rb") as handle:
        if b"%PDF-" not in handle.read(1024):
            raise ValueError(f"文件不是 PDF：{pdf}")
        handle.seek(0)
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if paper_input and digest != source["pdf"]["sha256"]:
        raise ValueError("PDF 已变化，请重新获取 Zotero 输入记录")

    if not (CACHE / "active.json").is_file():
        raise ValueError("请先运行 uv run --locked --extra paper-video python scripts/paper_video.py setup")
    install = read_json(CACHE / "active.json")
    version = CACHE / install["directory"]
    paper_root = OUTPUT / digest[:16]
    paper_root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="run-", dir=paper_root))
    shutil.copytree(
        version / "workshop", directory, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("node_modules", "audio_cache", "notes", "smoke.png", "scenes.json"),
    )
    shutil.copytree(version / "upstream/skills/paper2video", directory / "upstream-skill")
    shutil.copyfile(directory / "scenes.example.json", directory / "scenes.json")
    for relative in ("input", "notes", "out", "review"):
        (directory / relative).mkdir(exist_ok=True)
    staged = directory / "input/paper.pdf"
    shutil.copyfile(pdf, staged)
    with staged.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
            raise ValueError("复制期间 PDF 已变化，请重新准备运行")
    (directory / "public/data/vo.zh.json").unlink(missing_ok=True)
    for audio in (directory / "public/audio/zh").glob("s_example.*"):
        audio.unlink()
    write_json(directory / "run.json", {
        "source": source or {"path": str(pdf.resolve())},
        "pdf_sha256": digest, "upstream_commit": install["commit"], "stage": "prepared",
    })
    print(directory)


def finish(directory):
    manifest = directory / "run.json"
    state = read_json(manifest)
    if state["stage"] == "complete":
        print(directory / "out" / "paper_zh.mp4")
        return
    if not (directory / "notes/claims.md").is_file():
        raise ValueError("请先按上游工作流生成分镜、动画和 notes/claims.md")
    if not remotion_launcher(directory).is_file():
        run(directory, "npm", "ci", "--no-audit", "--no-fund")
    run(directory, sys.executable, "scripts/vo.py", "build", "--lang", "zh", "--backend", "edge")
    check_voice(directory)
    state["stage"] = "voiced"
    write_json(manifest, state)
    run(directory, sys.executable, "scripts/zh_breaks.py")
    run(directory, sys.executable, "scripts/srt.py", "zh", "--out", "out/paper_zh.srt")
    remotion(directory, "render", "VIDEO-ZH", "review/voice_raw.mp4", "--concurrency=4", "--log=error")
    run(directory, "ffmpeg", "-y", "-v", "error", "-i", "review/voice_raw.mp4",
        "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af",
        "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-ar", "48000",
        "-movflags", "+faststart", "review/verified.mp4")
    run(directory, sys.executable, "scripts/verify.py", "review/verified.mp4", "--cut", "zh", "--asr", "none")
    warnings = read_json(directory / "notes/verify.verified.json")["warnings"]
    if warnings:
        raise ValueError("成片检查未通过：" + "；".join(warnings))
    (directory / "review/verified.mp4").replace(directory / "out/paper_zh.mp4")
    state["stage"] = "complete"
    write_json(manifest, state)
    print(directory / "out" / "paper_zh.mp4")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("setup")
    start = subcommands.add_parser("prepare")
    source = start.add_mutually_exclusive_group(required=True)
    source.add_argument("--pdf", type=Path)
    source.add_argument("--paper-input", type=Path)
    complete = subcommands.add_parser("finish")
    complete.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        if args.command in {"setup", "finish"}:
            missing = [name for name in ("edge_tts", "jieba", "numpy") if find_spec(name) is None]
            if missing:
                raise ValueError(
                    f"缺少论文动画课依赖：{', '.join(missing)}。"
                    "请用 uv run --locked --extra paper-video python scripts/paper_video.py 重试"
                )
        if args.command == "setup":
            setup()
        elif args.command == "prepare":
            prepare(args.pdf, args.paper_input)
        else:
            finish(args.directory.resolve())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"paper-video {args.command}: {exc}\n")


if __name__ == "__main__":
    main()
