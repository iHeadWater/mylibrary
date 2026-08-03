# Hydro AI Papers

AI-driven hydrology and water resources research — **Zotero literature tools, knowledge graph construction, and paper reproduction**.

This repository serves three purposes:

1. **Zotero Tools** — MCP Server with 12 tools for querying your Zotero library, plus a paper ingestion pipeline (DOI → PDF → Zotero entry). [📖 Docs](http://localhost:8000)
2. **Knowledge Graph** — Build a structured, queryable knowledge base from hydrology literature using [graphify](https://github.com/graphify), with entity extraction, community detection, and Obsidian-compatible export.
3. **Paper Archive** — Curate and reproduce key papers in AI-driven hydrology, with accompanying code and data.

## Quick Start

```bash
# Clone and install
git clone git@github.com:OuyangWenyu/hydro_ai_papers.git
cd hydro_ai_papers
uv pip install -e .

# Configure
cp .env.example .env   # Add your DEEPSEEK_API_KEY, set HYDROLITAGENT_OUTPUT
```

### Zotero Tools

```bash
# Start the Zotero MCP Server (12 tools on port 8002)
uv run python -m hydrolitagent.zotero.server

# Add a paper to Zotero by DOI
uv run python -m hydrolitagent.zotero.paper_to_zotero --metadata-only "10.1038/s41586-024-07145-1"

# Full pipeline: download PDF + add to Zotero
bash scripts/run_paper_pipeline.sh "10.1038/s41586-024-07145-1"

# Start docs
uv run mkdocs serve
```

See the [documentation site](http://localhost:8000) for the full MCP tools reference and paper pipeline guide.

### Build a Knowledge Graph

```bash
# Full pipeline on a directory of markdown papers
uv run hydrolitagent prepare papers/your-topic/          # Step 1: detect + split
uv run hydrolitagent extract papers/your-topic/           # Step 2: LLM extraction
uv run hydrolitagent graph papers/your-topic/             # Step 3: build + cluster + export

# Or merge multiple topic graphs into a unified graph
uv run hydrolitagent merge --graphs-dir outputs/graph/ --output outputs/graph/unified/

# Query the graph
uv run hydrolitagent query outputs/graph/graph.json --search "LSTM"
uv run hydrolitagent query outputs/graph/graph.json --neighbors <node_id> --depth 2
uv run hydrolitagent query outputs/graph/graph.json --path <node_a> <node_b>
```

### Outputs

Each build produces (written to `HYDROLITAGENT_OUTPUT` or `--output`):

| File | Description |
|------|-------------|
| `graph.json` | Full graph: nodes, edges, communities, hyperedges |
| `graph.html` | Interactive D3.js force-directed visualization |
| `graph_hierarchical.html` | Hierarchical topic/community drill-down view |
| `GRAPH_REPORT.md` | Narrative report: god nodes, surprising connections, stats |
| `obsidian/` | Obsidian vault with per-node `.md` pages and `[[wikilinks]]` |

## Project Structure

```
hydrolitagent/           # Knowledge graph toolkit
├── cli.py               # CLI: prepare, extract, graph, merge, query
├── graph/
│   ├── build.py         # Single-topic graph build pipeline
│   └── merge.py         # Multi-topic merge + D3.js HTML viz
├── query/search.py      # Deterministic graph queries (no LLM)
└── zotero/              # Zotero integration
    ├── server.py         # 12-tool MCP Server (FastMCP, port 8002)
    ├── paper_to_zotero.py # DOI → Zotero entry with Crossref/arXiv metadata
    └── zot_link_gdrive.py # Google Drive → linked_file attachment

configs/                 # LLM prompt templates for entity extraction
scripts/                 # run_paper_pipeline.sh — one-shot paper ingestion
skills/                  # Agent skills (zotero-query, paper-to-zotero)
docs/                    # Documentation site (mkdocs-material)

equation_from_data/      # Paper: equation discovery from data
google_floodhub/         # Paper: Google flood forecasting
definitions.py           # Shared constants
```

## Papers

Curated hydrology AI papers with reproduction code:

1. [Global prediction of extreme floods in ungauged watersheds | Nature](https://www.nature.com/articles/s41586-024-07145-1) ([code](./google_floodhub/))

More papers and code will be added continuously.

## Contributing

We welcome contributions:

1. Fork and create a new branch
2. Add papers or code to the appropriate section
3. Ensure rights to share and compatibility with the [MIT License](LICENSE)
4. Submit a PR with a clear description

## License

MIT License. See [LICENSE](LICENSE).
