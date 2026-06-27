# Hydro AI Papers

AI-driven hydrology and water resources research — **paper collection, code reproduction, and knowledge graph construction**.

This repository serves a dual purpose:

1. **Knowledge Graph** — Build a structured, queryable knowledge base from hydrology literature using [graphify](https://github.com/graphify), with entity extraction, community detection, and Obsidian-compatible export.
2. **Paper Archive** — Curate and reproduce key papers in AI-driven hydrology, with accompanying code and data.

## Quick Start

```bash
# Clone and install
git clone git@github.com:OuyangWenyu/hydro_ai_papers.git
cd hydro_ai_papers
uv pip install -e .

# Configure
cp .env.example .env   # Add your DEEPSEEK_API_KEY, set HYDROLITAGENT_OUTPUT
```

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
└── query/search.py      # Deterministic graph queries (no LLM)

configs/                 # LLM prompt templates for entity extraction

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
