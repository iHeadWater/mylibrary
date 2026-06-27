# Hydro AI Papers

Literature knowledge base for AI-driven hydrology and water resources research.

## Commands

- Build knowledge graph: `uv run hydrolitagent graph <papers_dir> [--update]`
- Merge topic graphs: `uv run hydrolitagent merge --graphs-dir <dir> [--output <dir>]`
- Query a graph: `uv run hydrolitagent query <graph.json> --search "<keyword>"`
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
└── query/           # Graph query interface

configs/             # Prompt and extraction configuration

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
