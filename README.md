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
| **Zotero library query** — 12-tool MCP server (FastMCP SSE, port 8002): search, browse, read full text, attachments, annotations | `uv run python -m hydrolitagent.zotero.server` | [MCP tools](docs/user-guide/mcp-tools.md) |
| **Paper ingestion** — DOI / arXiv ID / title → PDF → Zotero entry + `linked_file` attachment | `bash scripts/run_paper_pipeline.sh "<DOI|arXiv|title>"` | [paper pipeline](docs/user-guide/paper-pipeline.md) |
| **Paper PDF download** — institutional-access download (DUT SSO) via Claude Code + Playwright | `uv run python -m hydrolitagent.literature.download_pdf doi <doi>` | [download PDF](docs/user-guide/download-pdf.md) |
| **Zotero linked_file sync** — sync a downloaded PDF into Zotero as a `linked_file` (zero cloud quota) | `uv run python -m hydrolitagent.literature.zotero_sync <pdf> <doi>` | [Zotero sync](docs/user-guide/zotero-sync.md) |
| **Zotero → NotebookLM** — turn newly added papers into a Chinese briefing / audio / video overview | `uv run python -m hydrolitagent.literature.zotero_notebooklm --collection <name> --artifact audio` | [NotebookLM](docs/user-guide/zotero-notebooklm.md) |
| **Deep literature processing** — Literature CLI: weekly review, WeChat publish / polish / figures, Bilibili upload | `uv run python -m hydrolitagent.literature.wechat.push <md>` | [literature](docs/user-guide/literature.md) |
| **Knowledge graph** — build a structured, queryable knowledge base via [graphify](https://github.com/graphify) (entity extraction, community detection, Obsidian export) | `uv run hydrolitagent graph papers/your-topic/` | [architecture](docs/development/architecture.md) |
| **Paper reproduction** — reproduce key papers in AI-driven hydrology | — | `equation_from_data/`, `google_floodhub/` |

## Quick Start

```bash
# Clone and install
git clone git@github.com:OuyangWenyu/mylibrary.git
cd mylibrary
uv pip install -e .

# Configure
cp .env.example .env   # add DEEPSEEK_API_KEY; set HYDROLITAGENT_OUTPUT, ZOTERO_API_KEY, ZOTERO_LIBRARY_ID
```

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

## Agent Skills

| Skill | Purpose |
|---|---|
| `zotero-query` | Query the Zotero library via MCP tools |
| `paper-to-zotero` | Download a paper and add it to Zotero (DOI / arXiv / title) |
| `run-paper-to-zotero` | One-command paper-fetch → GDrive → Zotero linked_file pipeline |
| `download-pdf` | Institutional-access PDF download via Playwright |
| `zotero-notebooklm` | Zotero papers → NotebookLM Chinese briefing / audio / video |
| `weekly-review` | Weekly literature review: deep-read → analysis cards → WeChat article → NotebookLM podcast |
| `weekly-report-skill` | NotebookLM output → WeChat weekly-report MD |
| `figure-skill-v2` | Per-paper figures + issue cover (extract from PDF, else ZhipuAI CogView) |
| `bilibili-upload` | Podcast audio → MP4 → Bilibili upload |

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
scripts/                 # run_paper_pipeline.sh, chunk_fulltext.py
skills/                  # 9 agent skills
docs/                    # Documentation site (mkdocs-material)
outputs/                 # Deep-reading artifacts: outputs/weekly-review/{date}/{cards,article,podcast}
papers/                  # Topic-organized literature knowledge base (10 topics)

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

## Contributing

We welcome contributions:

1. Fork and create a new branch
2. Add papers, code, or docs to the appropriate section
3. Ensure rights to share and compatibility with the [MIT License](LICENSE)
4. Submit a PR with a clear description

## License

MIT License. See [LICENSE](LICENSE).
