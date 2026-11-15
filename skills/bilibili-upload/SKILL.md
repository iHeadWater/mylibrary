---
name: bilibili-upload
description: Upload weekly podcast audio to Bilibili. Converts audio + auto-generated cover to MP4 via ffmpeg, then uploads via biliup CLI. Triggers: "上传到B站", "B站投稿", "上传音频", "bilibili upload", "发布周报音频".
---

# Bilibili Audio Upload

Upload a podcast/audio file to Bilibili as a video (audio + cover image → MP4 via ffmpeg → biliup upload).

## Prerequisites (one-time)

Two external binaries on `PATH`, then one login. Neither is a Python dependency —
the script finds `biliup` with `shutil.which` and calls `ffmpeg` by name.

**1. `ffmpeg`** (audio + cover → MP4)

| Platform | Install |
|----------|---------|
| Windows | `winget install ffmpeg` |
| macOS | `brew install ffmpeg` — or drop a static build in `~/.local/bin` |
| Linux | `apt install ffmpeg` |

**2. `biliup`** (upload + credential storage)

| Platform | Install |
|----------|---------|
| Windows | `winget install --id=ForgQi.biliup-rs -e` |
| macOS | grab `biliupR-<ver>-aarch64-macos.tar.xz` from [biliup-rs releases](https://github.com/biliup/biliup-rs/releases), untar, put the binary in `~/.local/bin` |
| Linux | same releases page, pick the matching `-linux` archive |

**3. Log in once** (credential lasts ~2 years)

```bash
biliup -u ~/.bilibili/cookies.json login
```

It opens a menu (账号密码 / 短信 / 扫码 / 浏览器 / 网页Cookie). Pick 扫码登录 to scan
with the Bilibili app, or 浏览器登录 to get a `passport.bilibili.com/...` URL instead.
Credentials land in `~/.bilibili/cookies.json`.

> Run this in a **real terminal**. It needs a TTY; a pipe or background job fails with
> `Error: IO error: not a terminal`.

Afterwards, `biliup -u ~/.bilibili/cookies.json list` is a cheap read-only way to
confirm the login still works.

## Workflow

### Step 1: Locate the audio file

Ask the user which audio to upload. Common locations:

- `outputs/weekly-review/{date}/podcast/audio_hydrology.mp3`
- `outputs/weekly-review/{date}/podcast/audio_overview.mp3`
- User may provide a custom path

If the user says "this week's podcast" without a path, list available audio files under `outputs/weekly-review/` and ask which one.

### Step 2: Confirm metadata

Confirm with the user:
- **Title** (required, max 80 chars): e.g. "水文AI周报 2026-W26"
- **Tags** (comma-separated): e.g. "AI,水文,科研,周报"
- **Partition** (tid): default 171 (科技·人工智能)
- **Description** (optional): video description
- **Cover** (optional): custom cover image; auto-generated if omitted

### Step 3: Run the CLI

```bash
uv run python -m hydrolitagent.literature.bilibili_upload "<audio_path>" \
  --title "<title>" \
  --tags "<tags>" \
  --tid 171
```

Add `--dry-run` to preview without uploading (generates cover + MP4 locally).

Add `--cover <path>` to use a custom cover image.

### Step 4: Report the result

On success, the script outputs the video path. The Bilibili URL format:
`https://www.bilibili.com/video/BV{...}` — the user can find it in their Bilibili创作中心.

## Notes

- Audio is converted to MP4 with a static cover image (Bilibili requires video format)
- Cover is auto-generated with Pillow (1920×1080, gradient background + title + date).
  Chinese needs a CJK font; if none is found the script logs an explicit warning
  instead of quietly producing a cover full of tofu boxes.
- The MP4 must be `yuv420p`. Without `-pix_fmt yuv420p` libx264 picks `yuv444p`
  (High 4:4:4), which Bilibili and most players will not render. The script sets it.
- biliup cookie at `~/.bilibili/cookies.json` is valid for ~2 years
- If upload fails with code 601, wait a few minutes and retry (rate limit)
- Upload first tries biliup's default `client` submit interface, which normally falls
  back to the APP interface on its own. If you see
  `ResponseData { code: 42002, message: "返回状态错误（非常规捕捉）" }`, that fallback did
  not trigger — retry with `biliup upload --submit app ...` directly.
- New uploads stay invisible for a few minutes while under review: the public
  `view?bvid=` API returns `-404`, and the creator centre reports `state: -30 审核中`.
  Neither means the upload failed.
