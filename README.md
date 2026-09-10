# Hydro AI Papers (mylibrary)

[中文](README-zh.md)

AI-driven hydrology and water resources research — the **deep-processing layer** of a literature pipeline: close reading, topic organization, WeChat articles, podcasts, and a knowledge graph, rooted in your **Zotero library**.

## What this repo is

mylibrary owns everything **after intelligence collection**:

- **Zotero is the starting point** of the literature pipeline — deep processing typically begins by reading from your Zotero library through the MCP server.
- **Ingestion into Zotero is also part of this repo** — the DOI / arXiv / title → PDF → Zotero-entry pipeline (`run_paper_pipeline.sh`) lives here.
- Upstream, a sibling collector repo (dailyinfo) handles **pre-Zotero intelligence gathering** (news feeds, raw downloads); mylibrary does not read its outputs.

The result accumulates into a **literature knowledge base**: `papers/` organized by hydrology topic (10 topics, 6,000+ papers), plus deep-reading analysis cards, WeChat articles, and podcasts under `outputs/`.

## Capabilities

| Capability | Command | Docs |
|---|---|---|
| **Zotero library query** — 12-tool MCP server (streamable HTTP, port 8002, endpoint `/mcp`): search, browse, read full text, attachments, annotations | `uv run python -m hydrolitagent.zotero.server` | [MCP tools](docs/user-guide/mcp-tools.md) |
| **Paper ingestion** — DOI / arXiv ID / title → PDF → Zotero entry + `linked_file` attachment | `bash scripts/run_paper_pipeline.sh "<DOI|arXiv|title>"` | [paper pipeline](docs/user-guide/paper-pipeline.md) |
| **Paper PDF download** — institutional-access download (DUT SSO) via Claude Code + Playwright | `uv run python -m hydrolitagent.literature.download_pdf doi <doi>` | [download PDF](docs/user-guide/download-pdf.md) |
| **Zotero linked_file sync** — sync a downloaded PDF into Zotero as a `linked_file` (zero cloud quota) | `uv run python -m hydrolitagent.literature.zotero_sync <pdf> <doi>` | [Zotero sync](docs/user-guide/zotero-sync.md) |
| **Zotero → NotebookLM** — turn newly added papers into a Chinese briefing / audio / video overview | `uv run python -m hydrolitagent.literature.zotero_notebooklm --collection <name> --artifact audio` | [NotebookLM](docs/user-guide/zotero-notebooklm.md) |
| **Deep literature processing** — Literature CLI: weekly review, WeChat publish / polish / figures, Bilibili upload | `uv run python -m hydrolitagent.literature.wechat.push <md>` | [literature](docs/user-guide/literature.md) |
| **Knowledge graph** — build a structured, queryable knowledge base via [graphify](https://github.com/graphify) (entity extraction, community detection, Obsidian export) | `uv run hydrolitagent graph papers/your-topic/` | [architecture](docs/development/architecture.md) |
| **Paper reproduction** — reproduce key papers in AI-driven hydrology | — | `equation_from_data/`, `google_floodhub/` |
| **Research knowledge platform** — the *long-term knowledge asset* branch of consumption: detect new papers in a shared Zotero group → full-text gate → per-paper evidence packs → evolving theme pool → daily report. Unattended, deterministic, no hand-editing. **Windows-only runtime.** | `uv run hydro-platform run-once --json` | [platform docs](docs/hydro-platform/index.md) |

## Quick Start

```bash
# Clone and install
git clone git@github.com:iHeadWater/mylibrary.git
cd mylibrary
uv sync --all-packages   # installs BOTH packages in this uv workspace into the shared root .venv

# Configure
cp .env.example .env   # add DEEPSEEK_API_KEY; set HYDROLITAGENT_OUTPUT, ZOTERO_API_KEY, ZOTERO_LIBRARY_ID
```

> This repo is a **uv workspace** with two members: `hydrolitagent` (root) and `hydro-platform`. They share one `.venv` and one `uv.lock`. Use `uv sync --all-packages` — a plain `uv sync` installs only the root package's dependencies, so `uv run hydro-platform …` would not be available.

For the full reference (Zotero Desktop / Linked Attachment Base Directory setup, env vars, TOML config), see the [installation guide](docs/getting-started/installation.md).

## Common Commands

### Zotero tools

```bash
# Start the 12-tool MCP server (port 8002)
uv run python -m hydrolitagent.zotero.server

# Add a paper to Zotero by DOI (metadata only)
uv run python -m hydrolitagent.zotero.paper_to_zotero --metadata-only "10.1038/s41586-024-07145-1"

# One-shot pipeline: download PDF + create Zotero entry + linked_file
bash scripts/run_paper_pipeline.sh "10.1038/s41586-024-07145-1"

# Link an existing GDrive PDF as a Zotero linked_file
uv run python -m hydrolitagent.zotero.zot_link_gdrive <ZOTERO_KEY> <filename>
```

### Literature CLI (post-ingestion deep processing)

```bash
# One-command download + Zotero sync (stealth Chrome; auto publisher routing)
uv run python scripts/download_paper.py --doi <doi> --sync
uv run python scripts/download_paper.py --arxiv <id> --sync

# Institutional-access PDF download
uv run python -m hydrolitagent.literature.download_pdf doi <doi>

# Sync a downloaded PDF into Zotero as linked_file
uv run python -m hydrolitagent.literature.zotero_sync <pdf_path> <doi> --json

# Zotero → NotebookLM briefing / audio / video (requires the [notebooklm] extra)
uv run --extra notebooklm python -m hydrolitagent.literature.zotero_notebooklm --collection <name> --artifact audio

# WeChat public-account workflow
uv run python -m hydrolitagent.literature.wechat.polish <draft.md>
uv run python -m hydrolitagent.literature.wechat.figure <article.md>
uv run python -m hydrolitagent.literature.wechat.push <polished.md> [--thumb <media_id>]

# Upload podcast audio to Bilibili
uv run python -m hydrolitagent.literature.bilibili_upload <audio.mp3> --title "标题" --tags "AI,水文,科研" [--dry-run]
```

### Knowledge graph

```bash
# 3-step pipeline on a directory of markdown papers
uv run hydrolitagent prepare papers/your-topic/    # step 1: detect + split
uv run hydrolitagent extract papers/your-topic/     # step 2: LLM extraction
uv run hydrolitagent graph papers/your-topic/       # step 3: build + cluster + export

# Merge multiple topic graphs into a unified graph
uv run hydrolitagent merge --graphs-dir outputs/graph/ --output outputs/graph/unified/

# Query the graph (deterministic, no LLM)
uv run hydrolitagent query outputs/graph/graph.json --search "LSTM"
```

Each graph build writes `graph.json`, `graph.html` (D3.js), `GRAPH_REPORT.md`, and `obsidian/` (Obsidian vault with `[[wikilinks]]`) to `HYDROLITAGENT_OUTPUT` or `--output`.

### Research knowledge platform (`hydro-platform`)

**Ingestion is only two things — download a PDF, and create the Zotero entry.** Everything else in this repo is *consumption*: reading the library, close analysis, topics, knowledge graph, articles, podcasts. This platform is a distinct branch of that consumption side — where the rest produces per-issue content, it produces **long-lived, traceable knowledge assets**: it turns papers already in a **shared Zotero group** into **evidence packs** and an evolving **theme pool**. Run it from the repo root.

> Note the two sides are not the same as the two packages: `hydrolitagent` spans **both** (its download/ingest commands, plus most of the consumption side), while `hydro-platform` is purely consumption.

```bash
# One full unattended pass: detect → gate → card → themes → ledger → daily report
uv run hydro-platform run-once --json

# Preview local tasks only — does NOT scan Zotero and does NOT call a model
uv run hydro-platform run-once --dry-run --json

# Theme pool only; --dry-run previews without calling a model
uv run hydro-platform themes-run --json
uv run hydro-platform themes-run --dry-run --json

# Health check (config, dependencies, login, Zotero) — no model calls
uv run hydro-platform doctor --json
```

- It **never downloads PDFs** — it only reads files already attached in the Zotero group. Downloading and ingestion belong to `paper-to-zotero` / `download-pdf`.
- **Windows-only runtime** for scheduling, Poppler setup, and the PDF sandbox probe. The orchestration logic itself is OS-neutral but is only validated on Windows.
- Generated output (evidence packs, theme pool, reports, ledger) is **not committed** — it is written at runtime and shared out of band. Only code, templates, prompts and schemas live in git.
- Full command list: `uv run hydro-platform --help` (29 subcommands).

## Agent Skills

| Skill | Purpose |
|---|---|
| `zotero-query` | Query the Zotero library via MCP tools |
| `paper-to-zotero` | Download a paper and add it to Zotero (DOI / arXiv / title) |
| `run-paper-to-zotero` | One-command paper-fetch → GDrive → Zotero linked_file pipeline |
| `download-pdf` | Institutional-access PDF download via Playwright (+ `scripts/download_paper.py` stealth one-command mode) |
| `zotero-notebooklm` | Zotero papers → NotebookLM Chinese briefing / audio / video |
| `weekly-review` | Weekly literature review: deep-read → analysis cards → WeChat article → NotebookLM podcast |
| `weekly-report-skill` | NotebookLM output → WeChat weekly-report MD |
| `figure-skill-v2` | Per-paper figures + issue cover (extract from PDF, else ZhipuAI CogView) |
| `bilibili-upload` | Podcast audio → MP4 → Bilibili upload |
| `hydro-platform` | Entry point to the research knowledge platform CLI (shared Zotero group → evidence packs → theme pool). Windows-only runtime. |

## Project Structure

```
hydrolitagent/
├── cli.py               # CLI entry: prepare, extract, graph, merge, query
├── zotero/              # Zotero integration
│   ├── server.py         # 12-tool MCP Server (FastMCP, port 8002)
│   ├── paper_to_zotero.py # DOI/arXiv/title → Zotero entry (Crossref/arXiv metadata)
│   └── zot_link_gdrive.py # Google Drive → linked_file attachment
├── literature/          # Literature CLI (post-ingestion deep processing)
│   ├── download_pdf.py      # Institutional-access PDF download
│   ├── zotero_sync.py       # PDF → Zotero linked_file
│   ├── zotero_notebooklm.py # Zotero → NotebookLM briefing/audio/video
│   ├── bilibili_upload.py   # Podcast → MP4 → Bilibili
│   └── wechat/              # figure.py, polish.py, push.py
├── graph/               # Knowledge graph build + merge (graphify)
│   ├── build.py          # prepare / extract / graph
│   └── merge.py          # multi-topic merge + D3.js HTML viz
└── query/               # Deterministic graph queries (no LLM)
    └── search.py

configs/                 # Prompt / extraction configuration
scripts/                 # run_paper_pipeline.sh, download_paper.py (stealth one-command PDF downloader), chunk_fulltext.py
skills/                  # 10 agent skills
docs/                    # Documentation site (mkdocs-material)
outputs/                 # Deep-reading artifacts: outputs/weekly-review/{date}/{cards,article,podcast}
papers/                  # Topic-organized literature knowledge base (10 topics)

hydro-platform/          # Research knowledge platform (uv workspace member)
├── automation/          #   Python: detection → PDF gate → task state machine → carding → themes
├── templates/           #   Reusable assets: 8 evidence-card templates, theme prompts, JSON schemas
├── config/              #   Non-secret config + full example
└── pyproject.toml       #   Entry point: `uv run hydro-platform`
                         #   Generated output (evidence-packs/, themes/, reports/, activity/,
                         #   members/) is NOT tracked — it is created at runtime.

equation_from_data/      # Paper reproduction: equation discovery from data
google_floodhub/         # Paper reproduction: Google flood forecasting
definitions.py           # Shared definitions/constants
```

## Documentation

The documentation site is built with [mkdocs-material](https://squidfunk.github.io/mkdocs-material/). Sources live in [`docs/`](docs/):

```bash
uv run mkdocs serve    # http://127.0.0.1:8000
uv run mkdocs build --strict
```

Platform documentation lives under [`docs/hydro-platform/`](docs/hydro-platform/index.md) — start there, and see its [operations guide](docs/hydro-platform/platform-operations-guide.md) for the complete handover. The decision to keep two separate Zotero clients is recorded in [ADR-0002](docs/adr/0002-zotero-two-clients-boundary.md).

## Contributing

We welcome contributions:

1. Fork and create a new branch
2. Add papers, code, or docs to the appropriate section
3. Ensure rights to share and compatibility with the [MIT License](LICENSE)
4. Submit a PR with a clear description

## License

MIT License. See [LICENSE](LICENSE).
