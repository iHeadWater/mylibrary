# Hydro AI Papers

Literature knowledge base for AI-driven hydrology and water resources research.

## Commands

### Knowledge Graph
- Build knowledge graph: `uv run hydrolitagent graph <papers_dir> [--update]`
- Merge topic graphs: `uv run hydrolitagent merge --graphs-dir <dir> [--output <dir>]`
- Query a graph: `uv run hydrolitagent query <graph.json> --search "<keyword>"`

### Zotero
- Start MCP Server: `uv run python -m hydrolitagent.zotero.server` (port 8002, 12 tools)
- Add paper by DOI: `uv run python -m hydrolitagent.zotero.paper_to_zotero --metadata-only "<DOI>"`
- Paper pipeline: `bash scripts/run_paper_pipeline.sh "<DOI|arXiv|title>"`
- Link GDrive PDF: `uv run python -m hydrolitagent.zotero.zot_link_gdrive <ZOTERO_KEY> <filename>`

### Docs
- Serve docs: `uv run mkdocs serve`
- Build docs: `uv run mkdocs build --strict`

### General
- Run tests: `uv run pytest`
- Install CLI: `uv pip install -e .`

## Project Structure

```
hydrolitagent/       # Knowledge graph toolkit (graphify integration)
├── cli.py           # CLI entry point (argparse subcommands)
├── _config.py       # Shared TOML loader
├── graph/           # Knowledge graph construction + merging
│   ├── build.py     # Single-topic graph build pipeline
│   └── merge.py     # Multi-topic merge + D3.js HTML viz
├── query/           # Graph query interface
└── zotero/          # Zotero integration
    ├── server.py     # 12-tool MCP Server (FastMCP, port 8002)
    ├── paper_to_zotero.py # DOI → Zotero (Crossref/arXiv/S2 metadata)
    └── zot_link_gdrive.py # Google Drive → linked_file attachment

configs/             # Prompt and extraction configuration
scripts/             # run_paper_pipeline.sh — one-shot paper ingestion
skills/              # Agent skills (zotero-query, paper-to-zotero)
docs/                # Documentation site (mkdocs-material)
tests/               # pytest (test_zotero_server.py, test_paper_to_zotero.py)

equation_from_data/  # Paper reproduction: equation discovery from data
google_floodhub/     # Paper reproduction: Google flood forecasting
definitions.py       # Shared definitions/constants
```

## Setup

```bash
# Copy and configure
cp .env.example .env   # Add your DEEPSEEK_API_KEY, set HYDROLITAGENT_OUTPUT

# Install
uv pip install -e .

# Build a knowledge graph from markdown papers
uv run hydrolitagent graph papers/your-topic/
```
