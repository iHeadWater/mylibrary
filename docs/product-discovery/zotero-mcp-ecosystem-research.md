# Zotero MCP Ecosystem Deep Research

**Date**: 2026-08-01
**Context**: Understanding the competitive landscape of Zotero MCP tools, and where mylibrary fits.

---

## 1. The Ecosystem: Three Tiers

### Tier 1: Library Access Tools (most mature, most crowded)

These connect AI assistants to Zotero for basic operations: search, read metadata, get PDFs, add papers.

| Project | Stars | Lang | Architecture | Key Differentiator |
|---------|-------|------|-------------|-------------------|
| [54yyyu/zotero-mcp](https://github.com/54yyyu/zotero-mcp) | **4,500** | Python | Standalone server, dual local+web API | Semantic search (ChromaDB), 46 tools, most complete |
| [cookjohn/zotero-mcp](https://github.com/cookjohn/zotero-mcp) | **1,100** | TypeScript | Zotero plugin (.xpi) with integrated MCP | Runs inside Zotero, no separate process, 20 tools |
| [kujenga/zotero-mcp](https://github.com/kujenga/zotero-mcp) | **159** | Python | Standalone, local or web API | Minimalist: 3 tools, simple setup |
| [swairshah/zotero-mcp-server](https://github.com/swairshah/zotero-mcp-server) | **26** | Python | Standalone | 4 tools: search, details, notes, summaries |
| [Xevos117/mcp-zotero](https://github.com/Xevos117/mcp-zotero) | ~50 | Node.js | Standalone via Web API | 15 tools, docx citation injection, Unpaywall OA |

### Tier 2: Knowledge Graph Tools (emerging, small)

These go beyond library access to build graphs and analyze relationships.

| Project | Stars | Lang | Graph Type | Approach |
|---------|-------|------|-----------|----------|
| [alisoroushmd/zotero-mcp](https://github.com/alisoroushmd/zotero-mcp) | **3** | Python | Citation graph + entity graph | OpenAlex for citations, LLM-in-the-loop for entities, NetworkX+SQLite |
| [henrardo/llm-graph-builder-mcp](https://github.com/henrardo/llm-graph-builder-mcp) | ~50 | Python | Entity-relation graph | Neo4j backend, academic mode for citations/authors/concepts |

### Tier 3: Pipeline Tools (specialized)

These handle specific paper workflow tasks.

| Project | Focus |
|---------|-------|
| [Xevos117/mcp-zotero](https://github.com/Xevos117/mcp-zotero) | DOI → download → PDF import → docx citation |
| myopenclaw paper-pipeline | DOI → Crossref metadata → Google Drive → Zotero linked_file |

---

## 2. Deep Dive: The Three Key Players

### 2.1 54yyyu/zotero-mcp — The Gold Standard for Library Access

**Architecture**: Python standalone MCP server. Supports local API (Zotero 7+, read-only, no key), web API (cloud, read+write), and hybrid (local reads + web writes).

**46 tools** across these categories:
- Semantic search (ChromaDB, configurable embeddings)
- Keyword search, tag search, collection browsing
- Full-text access, metadata retrieval (Markdown, JSON, BibTeX)
- PDF annotation extraction with page numbers
- Write: add by DOI/URL/ISBN/BibTeX/CSL JSON, create collections, update metadata, batch tags
- Scite integration (retraction alerts, citation tallies)
- Related items, duplicate detection/merge
- CLI companion (`zotero-cli`) for terminal use

**Key strength**: It does *everything* at the library access level, and does it well. 294 unit tests. Docker support. Auto-setup wizard.

**Key limitation**: It's a Zotero access tool. It doesn't understand paper *content* beyond full-text search. It knows what papers you have, but not what claims they make or how methods relate across papers.

### 2.2 cookjohn/zotero-mcp — The Plugin Approach

**Architecture**: Zotero plugin (.xpi) containing an integrated MCP server over Streamable HTTP. The AI client connects to `http://127.0.0.1:23120/mcp`. No separate process.

**20 tools** across search, collections, semantic search (SQLite-vec), full-text, and write operations.

**Key strength**: Tightest Zotero integration. Lives inside Zotero, has direct access to the SQLite database. No API key needed for local use. Write operations with granular permission scopes.

**Key limitation**: Zotero 7+ only. Local only. No remote/group library support. Semantic search requires external embedding APIs.

### 2.3 alisoroushmd/zotero-mcp — The Closest to Our Vision

**Architecture**: Python MCP server. Web API for operations, optional local API for fast reads. External APIs for enrichment (OpenAlex, CrossRef, Semantic Scholar, PubMed).

**36 tools** including a notable knowledge graph subsystem:
- `build_index` — citation graph + fulltext index (SQLite + NetworkX)
- `query_knowledge_graph` — PageRank, clusters, bridge papers, shortest paths, timeline, topic evolution, citation velocity, trending
- `find_related_papers` — Semantic Scholar recommendations
- `query_authors` — ego networks, co-author lookup, author clusters
- `export_knowledge_graph` — D3.js HTML visualization
- Entity extraction: `get_unextracted_abstracts` → LLM extracts → `store_entities` → `search_entities`

**Key strength**: Only existing Zotero MCP that does both library access AND knowledge graph analysis. Has entity extraction with an explicit LLM-in-the-loop pattern.

**Key limitations** (these define our opportunity):
1. **Citation-based graph, not content-based**: The knowledge graph is built from OpenAlex citation data, not from extracting concepts from paper content. It tells you who cites whom, not what claims are made, what methods are compared, or what datasets are used.
2. **No knowledge layering**: Flat graph. No L0→L4 maturity model. No concept of review status, confidence, or progressive enrichment.
3. **No human-in-the-loop design**: Entity extraction passes through the LLM but there's no review queue, no approval workflow, no feedback loop.
4. **Single-agent, not multi-agent**: Built for one AI client interacting with one library. No concept of shared research memory across agents.
5. **Tiny community**: 3 stars. Very early stage. May not be maintained.

---

## 3. Competitive Positioning: Where We Fit

### The Strategic Landscape

```
                    Library Access Maturity
                    low ──────────────────── high
                         │
              ┌──────────┼──────────┐
              │  US      │          │
    Content   │          │ mylibrary│
    Analysis  │          │ (future) │
    Depth     │          │          │
              │          │          │
    high ─────┼──────────┼──────────┤
              │          │          │
              │alisoroush│ 54yyyu   │
              │md/zotero │ zotero   │
              │  -mcp    │  -mcp    │
              │          │          │
    low ──────┼──────────┼──────────┤
              │          │          │
              │ kujenga  │ cookjohn │
              │ zotero   │ zotero   │
              │  -mcp    │  -mcp    │
              └──────────┴──────────┘
```

- **X-axis** = Library Access Maturity: How well does it handle Zotero read/write/search?
- **Y-axis** = Content Analysis Depth: How deeply does it understand paper *content* vs just metadata/citations?

### Our Unique Position (Top-Right Quadrant)

**No existing tool occupies the top-right quadrant.** The 54yyyu/zotero-mcp is the gold standard for library access (right side) but has no content analysis (bottom-right). alisoroushmd/zotero-mcp has basic content analysis (entity extraction) but weak library access and a citation-based graph (top-left).

mylibrary's target position: **best-in-class library access + deepest content analysis**.

### What We Should Build vs What We Should Reuse

| Capability | Build or Reuse? | Rationale |
|-----------|----------------|-----------|
| Zotero API access (read/write/search) | **REUSE** 54yyyu/zotero-mcp | Mature, well-maintained, 4.5k stars, 46 tools, 294 tests. Don't rebuild this. |
| Semantic search over library | **REUSE** 54yyyu/zotero-mcp | ChromaDB-based, configurable embeddings. Already excellent. |
| PDF full-text extraction | **REUSE** 54yyyu/zotero-mcp | PyMuPDF-based, already handles annotations. |
| Content-based knowledge graph | **BUILD** — our core IP | No existing tool does this. Extract concepts, methods, datasets, claims from paper content. |
| Knowledge layering (L0→L4) | **BUILD** — our core IP | Unique. No existing tool has a maturity model for knowledge. |
| Human-in-the-loop review | **BUILD** — our core IP | No existing tool has review gates, approval workflows, or feedback loops. |
| Agent skill SDK | **BUILD** — delivery layer | Standard format for packaging our capabilities for Hermes/CC飞总/虾酱. |
| Cross-agent shared memory | **BUILD** — integration layer | Connects to myopenclaw's TDAI memory for multi-agent knowledge sharing. |
| Citation graph analysis | **REUSE** (maybe) alisoroushmd's approach | OpenAlex-based citation graph is a commodity. Could integrate as a supplementary feature. |
| D3.js graph visualization | **EXTEND** what we have | Our existing `graph_hierarchical.html` is already better (topic + community dual view). |
| Domain-specific extraction schemas | **BUILD** — we already have this | `configs/graph_prompts.toml` with hydrology-specific entities and relations. |

### The "Thin Wrapper" Strategy for zotlib

Our `zotlib` should NOT be a reimplementation of Zotero API access. Instead:

```
┌─────────────────────────────────────────────┐
│              mylibrary (our code)            │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │         Knowledge Pipeline            │  │
│  │  L0: Paper Index                      │  │
│  │  L1: Content Extraction (LLM)         │  │
│  │  L2: Cross-paper Graph                │  │
│  │  L3: Synthesis + Review               │  │
│  │  L4: Research Agenda                  │  │
│  └───────────────┬───────────────────────┘  │
│                  │                           │
│  ┌───────────────▼───────────────────────┐  │
│  │         zotlib (thin wrapper)         │  │
│  │  - Agent-friendly method names        │  │
│  │  - Bulk operations for pipelines      │  │
│  │  - Caching for repeated access        │  │
│  │  - Progress callbacks for agents      │  │
│  └───────────────┬───────────────────────┘  │
│                  │                           │
└──────────────────┼───────────────────────────┘
                   │
┌──────────────────▼───────────────────────────┐
│     54yyyu/zotero-mcp (upstream dep)          │
│     - Full Zotero API coverage (46 tools)     │
│     - Semantic search (ChromaDB)              │
│     - PDF extraction + annotations            │
│     - Write operations (DOI add, collections) │
│     - Battle-tested (294 tests, 4.5k stars)   │
└──────────────────────────────────────────────┘
```

zotlib adds agent-specific value:
- **Bulk sync**: "Give me all papers in collection X with their PDFs" — one call, not N
- **Progress reporting**: Agents can show "Synced 45/200 papers" instead of silence
- **Caching**: Don't re-download PDFs the agent already has
- **Error normalization**: Consistent error types across local API, web API, and offline modes
- **Agent-oriented defaults**: JSON output, structured logging, no interactive prompts

---

## 4. Our Differentiation: The Five Pillars

### Pillar 1: Content-Based Knowledge Graph (not citation-based)

Existing tools build graphs from **citation metadata** — who cites whom. We build graphs from **paper content** — what claims are made, what methods are used, what datasets are evaluated, what results contradict each other.

This is a fundamentally different data source. Citation graphs are easy (OpenAlex has the data) but shallow. Content graphs are hard (requires LLM extraction) but deep.

Our existing `graph_prompts.toml` already defines domain-specific entity and relation types — this is exactly the right approach, and no existing Zotero MCP has anything like it.

### Pillar 2: Knowledge Maturity Ladder (L0→L4)

No existing tool distinguishes between:
- Raw paper metadata (L0)
- Extracted claims (L1)
- Connected concepts (L2)
- Synthesized insights (L3)
- Actionable research directions (L4)

Every existing tool produces a flat graph. Our layered model means:
- Lower layers can be fully automated
- Higher layers require human review
- Each layer builds on the confidence of the layer below
- Agents can reason about *how reliable* a piece of knowledge is

### Pillar 3: Human-in-the-Loop by Design

Existing tools are either fully automated (extract everything, trust the LLM) or fully manual (the human does everything). We design for the middle: agents propose, humans decide.

This isn't a bug ("the AI isn't good enough to automate it") — it's a feature ("the human's judgment makes the knowledge base more reliable over time"). Every human decision (confirm/reject/edit) becomes a signal that improves future extractions.

### Pillar 4: Agent-First, Not Human-First

All existing Zotero MCP tools are designed for a **human using an AI assistant**. The human types a question, Claude queries Zotero, Claude answers.

Our tools are designed for **agents operating autonomously**. Hermes runs a cron job that syncs the library, extracts new papers, and surfaces drafts for review. CC飞总 does deep analysis on demand. 虾酱 sends notifications when review is needed.

This means our APIs need:
- Structured output (JSON, not conversational text)
- Idempotency (safe to re-run)
- Progress reporting (agents need to know what's happening)
- Error handling that agents can act on (retryable vs fatal)
- No interactive prompts (agents can't click "OK")

### Pillar 5: Domain-Configurable Extraction

Our `graph_prompts.toml` allows defining entity types and relations per research domain. Hydrology has different concepts than ML or biology. Existing tools have hardcoded schemas (or none at all). Ours is configurable — the same pipeline works for any domain with the right prompt config.

---

## 5. Strategic Recommendation

### What to build

1. **zotlib** — thin agent-friendly wrapper around 54yyyu/zotero-mcp (not a from-scratch Zotero client)
2. **Knowledge Pipeline** — L0→L4, content-based graph, review gates (our core)
3. **Agent Skill SDK** — standardized packaging for Hermes/CC飞总/虾酱 consumption
4. **Domain configs** — prompt templates per research area (we already started this)

### What to integrate, not rebuild

1. **Zotero API access** → depend on 54yyyu/zotero-mcp
2. **Semantic search** → depend on 54yyyu/zotero-mcp (ChromaDB)
3. **PDF extraction** → depend on 54yyyu/zotero-mcp (PyMuPDF)
4. **Citation graph** → optionally integrate OpenAlex (like alisoroushmd does) as L2 enrichment

### What to deprecate/evolve

1. **myopenclaw's `zotero-mcp-server.py`** (in worktree) — replace with mylibrary's zotlib + 54yyyu/zotero-mcp. The worktree's 6-tool server is a subset of what 54yyyu already provides.
2. **mylibrary's current Markdown-based graph build** — extend to consume Zotero items, not just local .md files. Keep the pipeline architecture but change the data source.

### The migration path

```
Current state:
  mylibrary: .md files → graphify extract → graph build → graph.json
  myopenclaw: zotero-cli-cc (CLI) + zotero-mcp-server.py (6 tools, in worktree)

Step 1: Add 54yyyu/zotero-mcp as mylibrary dependency
Step 2: Build zotlib as thin agent wrapper
Step 3: Extend knowledge pipeline to accept Zotero items as input
Step 4: Package capabilities as skills (SKILL.md + tools)
Step 5: Deploy to myopenclaw agents (replace worktree code)

Target state:
  mylibrary provides:
    - zotlib (agent-friendly Zotero access, backed by 54yyyu)
    - Knowledge pipeline (L0→L4, our core)
    - Skills for Hermes/CC飞总/虾酱
  myopenclaw consumes:
    - zotero-sync skill (Hermes cron)
    - knowledge-graph skill (CC飞总 deep analysis)
    - literature-review skill (any agent)
```

---

## 6. Open Questions for Discussion

1. **54yyyu/zotero-mcp as a dependency**: It's GPL-3.0 licensed. Does this work for our use case? Should we vendor it, wrap it, or just document it as a prerequisite?

2. **MCP vs direct library import**: Should zotlib call 54yyyu's Python API directly (same process) or go through its MCP interface (separate process)? Direct import is faster and simpler; MCP interface is more decoupled and matches the myopenclaw architecture pattern.

3. **Content graph vs citation graph**: Should we also build citation graphs (using OpenAlex like alisoroushmd) as a supplementary feature, or stay focused on content-based graphs only? Citation graphs are easier to build and provide different insights (influence, trending, bridge papers).

4. **Knowledge layering schema**: What exactly goes in each layer? The L0→L4 model needs a concrete schema before we can build it. This is the next design task.

---

*Generated with Claude Code — Deep Research on Zotero MCP Ecosystem*
