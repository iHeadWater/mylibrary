# Product Brainstorm: Hydro AI Papers → Agent Literature Intelligence Platform

**Date**: 2026-08-01
**Context**: Initial product discovery — evolving from a standalone knowledge graph CLI into an agent-facing literature management + knowledge base platform.

---

## 1. Current State Assessment

### What exists today (mylibrary)

| Component | Capability | Maturity |
|-----------|-----------|----------|
| `hydrolitagent graph` | Build knowledge graph from Markdown papers via LLM extraction | Working |
| `hydrolitagent merge` | Merge multiple topic graphs + D3.js visualization | Working |
| `hydrolitagent query` | Search, neighbors, shortest path, community browsing | Working |
| `configs/graph_prompts.toml` | Domain-specific entity/relation types | Configurable |
| `hydrolitagent extract` | Direct LLM backend (DeepSeek, Gemini, Claude, etc.) | Working |
| Paper reproductions | Equation discovery, Google flood forecasting | Early |

### What exists in myopenclaw (the consumer)

| Component | Capability | Maturity |
|-----------|-----------|----------|
| `zotero-cli-cc` | Zotero CLI for agents (SQLite read + Web API write) | Production |
| `paper-to-zotero` skill | DOI → download → Google Drive → Zotero entry | Production |
| `run-paper-pipeline.sh` | One-shot paper ingestion pipeline | Production |
| `zotero-mcp-server.py` (feat/issue-29) | Zotero Web API as MCP server for Claude Code | In development |
| rclone Google Drive | PDF storage backend | Production |

### The gap

mylibrary today works with **local Markdown files** — it has no connection to the user's actual Zotero library. myopenclaw has the Zotero connection but only for individual paper operations (search, add, download). The bridge — converting a curated Zotero library into a layered knowledge base — doesn't exist yet.

---

## 2. Ideation: Three Perspectives

### Product Manager (Market Fit & Value)

**PM-1: Agent-First Research Operating System**
Position mylibrary as the "literature OS" that agents use to manage, explore, and synthesize research. The pipeline isn't graph→export, it's: Zotero Library → Agent-Driven Exploration → Layered Knowledge → Research Outputs. The moat is that it's purpose-built for *agent orchestration*, not just human browsing.

**PM-2: Knowledge Maturity Ladder**
Introduce a tiered knowledge model:

```
L0: Raw papers (Zotero items + PDFs)
L1: Extracted claims (individual facts, methods, results from each paper)
L2: Connected concepts (graph edges between claims across papers)
L3: Synthesized insights (agent-generated summaries, contradictions, research gaps)
L4: Actionable agenda (what to read next, what to build, what to write)
```

Each layer has a different confidence model and different human review requirements. This is the "knowledge layering" the user wants.

**PM-3: Research Team Memory**
Multiple agents (Hermes, CC飞总, 虾酱) share the same knowledge base. Hermes might add papers and do initial extraction; Claude Code might do deep analysis and write syntheses; 虾酱 might handle notifications and reminders. The shared memory creates compounding value — each agent's work enriches the researchbase for all others.

**PM-4: Human-in-the-Loop Quality Gates**
Explicit review checkpoints where agents surface proposals and humans approve/reject/refine. Not just "build a graph automatically" but "agent proposes 50 extracted claims, human reviews 5 controversial ones, graph updates with human-verified edges." The human's decisions become training signal.

**PM-5: Open-Ended Research Exploration**
Instead of a fixed pipeline, agents use the knowledge base as a launchpad for open-ended exploration — "find papers that contradict this claim," "what methods are trending in this subfield," "who is working on X but not citing Y." The knowledge base enables questions the user didn't know they had.

### Product Designer (UX & Interaction)

**D-1: Conversation as Primary Interface**
The knowledge base isn't navigated through a web UI — it's accessed through agent conversations. "Summarize the state of physics-informed ML in hydrology" triggers a chain of: graph query → paper retrieval → synthesis → follow-up questions. The interface is natural language.

**D-2: Progressive Knowledge Building**
When a new paper enters the library, the agent doesn't try to extract everything at once. It starts with L1 (basic metadata + key claims), then progressively enriches based on what the human is actually working on. Knowledge depth follows research attention.

**D-3: Visual Research Topography**
Interactive knowledge maps that show not just "what's connected" but "where are the gaps," "what's controversial," "what's emerging." Not a generic graph visualization but a research-specific view with temporal trends, citation influence, and community structure.

**D-4: Source-to-Insight Provenance**
Every synthesized claim traces back to its source papers with specific passages. When an agent says "LSTM outperforms XGBoost for streamflow prediction," the user can click through to see exactly which papers, which experiments, and which metrics support that claim. Trust through transparency.

**D-5: Curated Research Paths**
Rather than dumping a graph, agents propose "trails" through the literature: "Start with this foundational paper → then this improvement → then this recent survey." Learning paths that guide understanding, not just reference lists.

### Software Engineer (Technical Innovation)

**E-1: Zotero Integration Layer (zotlib)**
A clean Python library wrapping Zotero Web API + Local API:

```python
# Read
library = ZoteroLibrary(api_key="...", library_id="...")
papers = library.search("flood forecasting", limit=50)
pdf_content = library.get_pdf("ITEM_KEY")

# Write
library.add_paper(doi="10.1038/...", collection="floods")
library.upload_pdf("ITEM_KEY", "/path/to/paper.pdf")
library.update_metadata("ITEM_KEY", {"tags": ["important", "pinn"]})

# Bulk
library.sync_collection("floods")  # pull all items → local cache
```

This replaces/augments the current `zotero-cli-cc` in myopenclaw. Designed as a Python library + CLI, not just a CLI. The worktree code (`zotero-mcp-server.py`) becomes the MCP server layer on top.

**E-2: Multi-Layer Knowledge Pipeline**

```text
Zotero Library
   │
   ├─→ L0: Paper index (metadata, PDFs, collections) — automated, fast
   ├─→ L1: Structured extraction (claims, methods, datasets, results) — LLM, chunked
   ├─→ L2: Cross-paper graph (relations, contradictions, communities) — graph algorithms
   ├─→ L3: Synthesis (summaries, trends, gaps) — LLM with graph context
   └─→ L4: Research agenda (reading list, experiment ideas) — LLM + human curation
```

Each step is a discrete pipeline stage with configurable LLM backends, review gates, and incremental update support.

**E-3: Agent Skill SDK**
Standardized format for packaging mylibrary capabilities as agent-consumable skills:

```text
skills/
├── zotero-sync/        # Sync with Zotero library
├── paper-search/       # Semantic + keyword search across library
├── knowledge-graph/    # Build, query, explore knowledge graph
├── literature-review/  # Generate structured literature reviews
├── research-gaps/      # Identify research gaps and contradictions
└── reading-list/       # Curate and prioritize reading lists
```

Each skill has: a `SKILL.md` (instructions for the agent), a `tools/` directory (Python scripts), and a `config.yaml` (parameters). Skills are designed for both Hermes (cron + interactive) and OpenClaw (Discord bot) consumption.

**E-4: Hybrid Vector + Graph Store**
Two complementary indices:

- **Vector store** (sqlite-vec or LanceDB): Semantic search over paper embeddings, claims, and notes. "Find papers similar to this idea" or "what papers discuss X in the context of Y."
- **Graph store** (current NetworkX + SQLite backend): Structural queries over the knowledge graph. "Trace the lineage of this method" or "find the shortest path between two concepts."

Both backed by the same source of truth (Zotero library). Both incrementally updatable.

**E-5: Codex-Style Agent Tooling**
Rather than a monolithic pipeline, provide a toolkit that agents can compose:

- Small, focused tools (not one big `build_graph` command)
- Each tool is self-documenting (agents can `--help` or read docstrings)
- Agents can chain tools in novel ways ("first search for papers about X, then extract methods from the top 10, then compare with what we already know about Y")
- The same tools work for both automated cron jobs and interactive exploration

This follows the Codex pattern: give agents a well-documented toolkit and let them figure out the workflow.

---

## 3. Top 5 Prioritized Ideas

### Priority 1: Zotero Integration Layer (`zotlib`)

**Category**: Engineer (E-1)
**Why first**: This is the foundation. Without Zotero access, none of the knowledge base features can reach real papers. The myopenclaw worktree code (`zotero-mcp-server.py`) is already building toward this — porting it to mylibrary gives it a proper home and a cleaner Python library interface.

**Core features**:
- Read: search, get item metadata, download PDFs, list collections
- Write: add items by DOI/ISBN/URL, upload PDFs, update metadata/tags, organize into collections
- Bulk: sync entire collections to local cache
- MCP server layer on top for Claude Code consumption
- CLI for Hermes/terminal use

**Key assumption to test**: Is the Zotero Web API + Local API sufficient, or do we need the desktop client running?

---

### Priority 2: Knowledge Maturity Ladder (L0→L4)

**Category**: PM (PM-2) + Engineer (E-2)
**Why second**: This is the core differentiation. Everyone builds flat knowledge graphs. The layered approach — with explicit confidence, review status, and progressive enrichment — creates a product that gets more valuable with human interaction.

**Core features**:
- L0: Automated paper index (runs on sync, no human needed)
- L1: LLM extraction with configurable schemas (from `graph_prompts.toml`)
- L2: Cross-paper graph construction with community detection
- L3: Agent-generated synthesis with mandatory human review flags
- L4: Research agenda derived from gaps in L2+L3
- Each layer has `status: draft | needs_review | verified | superseded`

**Key assumption to test**: Will users actually do the human review steps, or will the pipeline need to work well enough without them?

---

### Priority 3: Agent Skill SDK + Skill Pack

**Category**: Engineer (E-3) + Designer (D-1)
**Why third**: The delivery mechanism. mylibrary's capabilities need to be consumable by Hermes, Claude Code, and OpenClaw. A standardized skill format ensures that building once works everywhere. This directly addresses the user's request: "能力通过skill等形式给到myopenclaw."

**Core features**:
- `SKILL.md` template with standard sections: overview, prerequisites, tools, workflows, examples
- `tools/` directory with self-documenting CLI scripts
- Each tool has `--help`, structured JSON output, and error codes
- Skills are versioned and tested independently
- Installation is a single script: `./install-skill.sh zotero-sync` → copies to `~/.hermes/skills/`

**Key assumption to test**: Do Hermes's built-in tool calling and Claude Code's subagent spawning work well enough with skill-based tools, or do we need MCP for richer integration?

---

### Priority 4: Human-in-the-Loop Review Workflow

**Category**: PM (PM-4) + Designer (D-4)
**Why fourth**: This turns the pipeline from "automatic but untrusted" into "reviewed and reliable." The human's judgment is the moat — no fully automated system can match it. The key design challenge is making review lightweight and high-signal.

**Core features**:
- Agent proposes extractions/syntheses as "drafts"
- Review queue surfaces high-impact, low-confidence items first
- Human actions: ✓ confirm, ✗ reject (with reason), ✎ edit
- Rejected/edited items are recorded — they become negative examples for future extractions
- Review doesn't block the pipeline; it enriches it asynchronously

**Key assumption to test**: Can review be made lightweight enough (under 5 min per session) that users actually do it regularly?

---

### Priority 5: Cross-Agent Shared Research Memory

**Category**: PM (PM-3)
**Why fifth**: The compounding value engine. Once the knowledge base exists, multiple agents should benefit from it. This creates network effects within a single user's agent ecosystem — every agent action enriches the shared research memory.

**Core features**:
- Hermes: cron-driven paper discovery + ingestion + L1 extraction
- Claude Code / CC飞总: on-demand deep analysis, L2-L3 synthesis, interactive exploration
- 虾酱 (OpenClaw): notifications, quick lookups, status queries
- Shared read/write access with agent identity recorded on each contribution
- Conflict resolution: last-write-wins for metadata, explicit merge for claims

**Key assumption to test**: Does the shared memory model actually create compounding value, or do different agents produce incompatible artifacts?

---

## 4. Product Architecture Vision

```text
┌─────────────────────────────────────────────────────────────┐
│                    myopenclaw (Consumer)                     │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │  Hermes  │  │  Claude Code  │  │  OpenClaw (虾酱)      │ │
│  │  cron +  │  │  interactive  │  │  Discord bot          │ │
│  │  skills  │  │  MCP tools    │  │  plugins              │ │
│  └────┬─────┘  └──────┬───────┘  └───────────┬───────────┘ │
│       │               │                      │             │
│       └───────────────┼──────────────────────┘             │
│                       │ Skills / MCP / CLI                  │
└───────────────────────┼─────────────────────────────────────┘
                        │
┌───────────────────────┼─────────────────────────────────────┐
│              mylibrary (Capability Provider)                 │
│                       │                                     │
│  ┌────────────────────┼──────────────────────────────────┐  │
│  │              Agent Skill SDK                           │  │
│  │  SKILL.md format  │  Tool registry  │  MCP adapters   │  │
│  └────────┬───────────┬──────────┬──────────────────────┘  │
│           │           │          │                          │
│  ┌────────▼───┐ ┌─────▼────┐ ┌──▼──────────────┐          │
│  │  zotlib     │ │ Knowledge│ │ Research        │          │
│  │  Zotero API │ │ Pipeline │ │ Memory Store    │          │
│  │  read/write │ │ L0→L4    │ │ vector + graph  │          │
│  └──────┬──────┘ └─────┬────┘ └─────────────────┘          │
│         │              │                                    │
│  ┌──────▼──────────────▼─────┐                             │
│  │     Zotero Library        │                             │
│  │  (local SQLite + Web API) │                             │
│  └───────────────────────────┘                             │
└─────────────────────────────────────────────────────────────┘
```

## 5. Immediate Next Actions

1. **Port `zotero-mcp-server.py`** from myopenclaw worktree → mylibrary as `hydrolitagent/zotero/` — this is the first concrete code migration
2. **Design the `zotlib` API** — what does a clean Python Zotero client look like for agent consumption?
3. **Define the L0→L4 knowledge model** — schema, state machine, confidence scoring
4. **Create the first skill: `zotero-sync`** — a SKILL.md + tools that Hermes can use to sync the library
5. **Build a prototype review interface** — even a CLI `review` command that surfaces drafts for human approval

---

## 6. Key Risks & Open Questions

- **Knowledge freshness**: How to handle incremental updates when new papers are added or old extractions become stale? The current `graphify` pipeline is full-rebuild; incremental is essential for a living library.
- **LLM quality at scale**: Extraction quality varies by paper and model. A 500-paper library will have extraction errors. How to detect and surface low-confidence extractions?
- **Zotero as source of truth**: Should mylibrary ever modify Zotero metadata, or is Zotero the single source of truth that mylibrary reads from? The answer shapes the entire data model.
- **Skill vs MCP tradeoff**: Skills (SKILL.md + tools) are simpler and more portable. MCP servers are richer (structured tool definitions, streaming). Which is the primary delivery mechanism?

---

*Generated with Claude Code PM Product Discovery — Brainstorm Ideas (New Product)*
