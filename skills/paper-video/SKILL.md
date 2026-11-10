---
name: paper-video
description: Turn one Zotero paper or local PDF into a Chinese animated explainer with narration, using the project's paper2video workflow. Use for 论文动画课, 论文讲解视频, or requests to resume an existing paper-video run.
---

# Paper Video

Run commands from the mylibrary root. See [the project guide](../../docs/user-guide/paper-video.md) for setup and troubleshooting.

1. For Zotero, use `uv run hydrolitagent cards paper-input --user-library --query "<title or DOI>" --json`, then resolve the selected key with `uv run python scripts/paper_input.py --user-library --item-key <key> --output <unique-ignored-json-path>`. Continue automatically for one exact match. Ask the user to choose when the match is ambiguous. For an inaccessible attachment, explain the reported cause and use a readable local PDF when supplied. Use the group-library option when the user names a group.
2. If the project has no validated installation, run `uv run --locked --extra paper-video python scripts/paper_video.py setup`. Run it again for an explicit update. This contacts GitHub, package registries and the free Edge speech service, using a short synthetic text for the setup check.
3. Run `uv run --locked --extra paper-video python scripts/paper_video.py prepare --paper-input <json>` or `uv run --locked --extra paper-video python scripts/paper_video.py prepare --pdf <path>`. Use the printed directory for all production work. For a resume request, use the existing run with its own upstream snapshot. Keep the prepared toolchain and composition ID `VIDEO-ZH`.
4. Read that run's `upstream-skill/SKILL.md` and its relevant references. Follow its story, claims, figure extraction, script, scene and review workflow in the active agent. The workshop already contains the upstream template and scripts. Create `notes/claims.md`, write `scenes.json`, and build the scenes against the copied PDF. Default to a single 1080p Chinese horizontal cut, one teachable mechanism, and at least one result grounded in the paper. Mark schematics separately from paper data. Use the free Edge backend and keep the work local. Narration sends the written narration text to Edge.
5. Run `uv run --locked --extra paper-video python scripts/paper_video.py finish "<run directory>"`. It builds or reuses the narration and renders against its measured timings, exports SRT and verifies the video. If it fails, fix the reported stage and rerun the same command. Keep existing media when sharing an incomplete preview and identify it as such. The verification script checks technical properties without speech recognition. Spot-check the resulting scenes and pronunciation before reporting.
6. Return links to the verified MP4, SRT, editable run directory and claims ledger. Mention any checks that could not be performed.
