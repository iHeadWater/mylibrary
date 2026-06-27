"""Merge multiple topic-level knowledge graphs into one unified graph."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def _safe_filename(label: str, limit: int = 200) -> str:
    """Replicate graphify's safe_name + _cap_filename for wikilink consistency."""
    cleaned = re.sub(
        r'[\\/*?:"<>|#^[\]]', "",
        label.replace("\r\n", " ").replace("\r", " ").replace("\n", " "),
    ).strip()
    cleaned = re.sub(r"\.(md|mdx|qmd|markdown)$", "", cleaned, flags=re.IGNORECASE)
    if not cleaned:
        cleaned = "unnamed"
    b = cleaned.encode("utf-8")
    if len(b) <= limit:
        return cleaned
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:8]  # nosec
    keep = limit - 9
    return f"{b[:keep].decode('utf-8', 'ignore')}_{digest}"


def _build_node_filenames(G) -> dict[str, str]:
    """Build node_id → safe filename (without .md) mapping, matching graphify."""
    node_fname: dict[str, str] = {}
    seen: dict[str, int] = {}
    for nid, data in G.nodes(data=True):
        base = _safe_filename(data.get("label", nid))
        if base in seen:
            seen[base] += 1
            node_fname[nid] = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
            node_fname[nid] = base
    return node_fname


def _write_topic_indexes(G, output_dir: Path) -> tuple[int, int]:
    """Generate _TOPIC_{name}.md and _CROSS_TOPIC_BRIDGES.md index pages.

    Returns (topic_count, bridge_count).
    """
    node_fname = _build_node_filenames(G)

    topic_nodes: dict[str, list[str]] = {}
    cross_nodes: list[str] = []

    for nid, data in G.nodes(data=True):
        topics = data.get("topics", [])
        if not topics:
            continue
        for t in topics:
            topic_nodes.setdefault(t, []).append(nid)
        if len(topics) >= 2:
            cross_nodes.append(nid)

    # Per-topic index pages
    for topic, nids in sorted(topic_nodes.items()):
        lines = [
            "---",
            "type: topic_index",
            f'topic: "{topic}"',
            f"node_count: {len(nids)}",
            "---",
            "",
            f"# Topic: {topic}",
            "",
            f"**{len(nids)}** concepts",
            "",
            "## Concepts",
            "",
        ]
        for nid in sorted(nids, key=lambda n: G.nodes[n].get("label", n)):
            label = G.nodes[nid].get("label", nid)
            fname = node_fname.get(nid, _safe_filename(label))
            lines.append(f"- [[{fname}]]")
        lines.append("")
        (output_dir / f"_TOPIC_{_safe_filename(topic)}.md").write_text(
            "\n".join(lines), encoding="utf-8",
        )

    # Cross-topic bridges
    if cross_nodes:
        lines = [
            "---",
            "type: cross_topic_index",
            f"node_count: {len(cross_nodes)}",
            "---",
            "",
            "# Cross-Topic Bridges",
            "",
            f"**{len(cross_nodes)}** concepts appear in 2+ topics.",
            "",
            "## Bridges by topic count",
            "",
        ]
        for nid in sorted(
            cross_nodes,
            key=lambda n: -len(G.nodes[n].get("topics", [])),
        ):
            data = G.nodes[nid]
            label = data.get("label", nid)
            topics = data.get("topics", [])
            fname = node_fname.get(nid, _safe_filename(label))
            lines.append(f"- [[{fname}]] — {' | '.join(topics)}")
        lines.append("")
        (output_dir / "_CROSS_TOPIC_BRIDGES.md").write_text(
            "\n".join(lines), encoding="utf-8",
        )

    return len(topic_nodes), len(cross_nodes)


def _prepare_hierarchical_data(
    G, communities: dict, labels: dict, scores: dict,
) -> dict:
    """Build topic-level and community-level data for hierarchical visualization."""
    # ── topic nodes ──
    topic_sizes: dict[str, int] = {}
    topic_community: dict[str, set] = {}  # topic → set of community ids
    for nid, data in G.nodes(data=True):
        cid = data.get("community")
        for t in data.get("topics", []):
            topic_sizes[t] = topic_sizes.get(t, 0) + 1
            if cid is not None:
                topic_community.setdefault(t, set()).add(cid)

    topic_nodes = [
        {
            "id": f"topic_{_safe_filename(t)}",
            "label": t,
            "size": topic_sizes.get(t, 0),
            "community_count": len(topic_community.get(t, set())),
        }
        for t in sorted(topic_sizes)
    ]

    # Cross-topic edges: shared concept count
    cross_topic_pairs: dict[tuple, int] = {}
    for nid in list(G.nodes()):
        tlist = list(G.nodes[nid].get("topics", []))
        for i in range(len(tlist)):
            for j in range(i + 1, len(tlist)):
                pair = (
                    f"topic_{_safe_filename(tlist[i])}",
                    f"topic_{_safe_filename(tlist[j])}",
                )
                cross_topic_pairs[pair] = cross_topic_pairs.get(pair, 0) + 1

    topic_edges = [
        {"source": s, "target": t, "weight": w}
        for (s, t), w in sorted(cross_topic_pairs.items(), key=lambda x: -x[1])
    ]

    # ── community nodes (filter loose ones) ──
    community_nodes = []
    for cid, members in communities.items():
        coh = scores.get(cid, 0)
        if coh < 0.1:
            continue
        member_topics: dict[str, int] = {}
        for nid in members:
            if nid in G:
                for t in G.nodes[nid].get("topics", []):
                    member_topics[t] = member_topics.get(t, 0) + 1
        primary_topic = max(member_topics, key=member_topics.get) if member_topics else ""
        community_nodes.append({
            "id": f"comm_{cid}",
            "label": labels.get(cid, f"Community {cid}"),
            "size": len(members),
            "cohesion": coh,
            "primary_topic": primary_topic,
            "topics": sorted(member_topics.keys()),
        })

    # Inter-community edges
    community_edges = []
    edge_count: dict[tuple, int] = {}
    for u, v in G.edges():
        cu = G.nodes[u].get("community")
        cv = G.nodes[v].get("community")
        if cu is not None and cv is not None and cu != cv:
            key = (f"comm_{min(cu, cv)}", f"comm_{max(cu, cv)}")
            edge_count[key] = edge_count.get(key, 0) + 1
    community_edges = [
        {"source": s, "target": t, "weight": w}
        for (s, t), w in sorted(edge_count.items(), key=lambda x: -x[1])
    ]

    return {
        "topics": topic_nodes,
        "topic_edges": topic_edges,
        "communities": community_nodes,
        "community_edges": community_edges,
    }


def _write_hierarchical_html(data: dict, output_path: Path) -> None:
    """Write a self-contained D3.js HTML with topic and community views."""
    html = _HIERARCHICAL_HTML_TEMPLATE
    html = html.replace("__TOPIC_NODES_JSON__", json.dumps(data["topics"], ensure_ascii=False))
    html = html.replace("__TOPIC_EDGES_JSON__", json.dumps(data["topic_edges"], ensure_ascii=False))
    html = html.replace("__COMMUNITY_NODES_JSON__", json.dumps(data["communities"], ensure_ascii=False))
    html = html.replace("__COMMUNITY_EDGES_JSON__", json.dumps(data["community_edges"], ensure_ascii=False))
    html = html.replace("__N_TOPICS__", str(len(data["topics"])))
    html = html.replace("__N_COMMUNITIES__", str(len(data["communities"])))
    output_path.write_text(html, encoding="utf-8")


_HIERARCHICAL_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Unified Knowledge Graph — Hierarchical View</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; overflow: hidden; }
#controls { position: absolute; top: 12px; left: 12px; z-index: 10; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
button { padding: 8px 18px; border: 1px solid #334155; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500; background: #1e293b; color: #e2e8f0; transition: all .15s; }
button:hover { background: #334155; }
button.active { background: #3b82f6; border-color: #3b82f6; color: #fff; }
#search { padding: 8px 14px; border: 1px solid #334155; border-radius: 6px; background: #1e293b; color: #e2e8f0; font-size: 14px; width: 220px; outline: none; }
#search:focus { border-color: #3b82f6; }
#info { position: absolute; top: 14px; right: 14px; z-index: 10; font-size: 13px; color: #94a3b8; pointer-events: none; }
#tooltip { position: absolute; pointer-events: none; background: #1e293b; border: 1px solid #475569; border-radius: 8px; padding: 12px 16px; font-size: 13px; line-height: 1.5; opacity: 0; transition: opacity .1s; max-width: 340px; z-index: 20; box-shadow: 0 4px 20px rgba(0,0,0,.5); }
#tooltip.visible { opacity: 1; }
#legend { position: absolute; bottom: 20px; left: 20px; z-index: 10; font-size: 12px; display: flex; flex-wrap: wrap; gap: 8px; max-width: 60vw; }
.legend-item { display: flex; align-items: center; gap: 5px; background: #1e293bcc; padding: 3px 8px; border-radius: 4px; }
.legend-swatch { width: 10px; height: 10px; border-radius: 50%; }
#zoom-hint { position: absolute; bottom: 20px; right: 20px; z-index: 10; font-size: 12px; color: #475569; }
svg { width: 100vw; height: 100vh; }
.link { stroke-opacity: 0.35; }
.link.dimmed { stroke-opacity: 0.05; }
.node { cursor: pointer; }
.node.dimmed { opacity: 0.1; }
.node text { fill: #e2e8f0; font-size: 11px; pointer-events: none; text-anchor: middle; }
</style>
</head>
<body>
<div id="controls">
  <button id="btn-topic" class="active">Topics</button>
  <button id="btn-community">All Communities</button>
  <input id="search" type="text" placeholder="Search nodes..." />
</div>
<div id="info"></div>
<div id="tooltip"></div>
<div id="legend"></div>
<div id="zoom-hint">Scroll to zoom | Drag to pan</div>
<svg id="graph"></svg>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
const topicNodes = __TOPIC_NODES_JSON__;
const topicEdges = __TOPIC_EDGES_JSON__;
const communityNodes = __COMMUNITY_NODES_JSON__;
const communityEdges = __COMMUNITY_EDGES_JSON__;

const TOPIC_COLORS = ["#3b82f6","#ef4444","#22c55e","#f59e0b","#8b5cf6","#ec4899","#14b8a6","#f97316","#06b6d4","#a855f7"];
const topicColor = d3.scaleOrdinal().domain(topicNodes.map(n => n.label)).range(TOPIC_COLORS);

const W = window.innerWidth, H = window.innerHeight;
const svg = d3.select("#graph"), g = svg.append("g");
const tooltip = d3.select("#tooltip"), info = d3.select("#info");
const legend = d3.select("#legend");

// Zoom behavior
const zoom = d3.zoom().scaleExtent([0.1, 8]).on("zoom", e => g.attr("transform", e.transform));
svg.call(zoom);
svg.on("dblclick.zoom", null);

let currentMode = "topic";
let simulation;

function buildLegend(mode) {
  legend.html("");
  if (mode === "topic") {
    topicNodes.forEach(n => {
      const item = legend.append("div").attr("class","legend-item");
      item.append("div").attr("class","legend-swatch").style("background", topicColor(n.label));
      item.append("span").text(`${n.label} (${n.size})`);
    });
  } else {
    const topTopics = [...new Set(communityNodes.map(n => n.primary_topic).filter(Boolean))].slice(0, 10);
    topTopics.forEach(t => {
      const item = legend.append("div").attr("class","legend-item");
      item.append("div").attr("class","legend-swatch").style("background", topicColor(t));
      item.append("span").text(t);
    });
  }
}

let selectedTopic = null;

// Pre-sort communities by size descending for efficient limiting
communityNodes.sort((a, b) => b.size - a.size);

// Build lookup maps for edge traversal
const commById = new Map(communityNodes.map(n => [n.id, n]));
const topicById = new Map(topicNodes.map(n => [n.label, n]));

function render(mode, filterTopic) {
  currentMode = mode;
  selectedTopic = filterTopic || null;
  g.selectAll("*").remove();
  d3.select("#btn-topic").classed("active", mode === "topic");
  d3.select("#btn-community").classed("active", mode === "community" && !filterTopic);
  buildLegend(mode);

  let nodes, edges, neighborIds, totalAvail;

  if (mode === "topic") {
    nodes = topicNodes;
    edges = topicEdges;
    info.text(`${nodes.length} topics | Click a topic to explore communities`);
  } else if (filterTopic) {
    // ── Topic drill-down: top 60 communities in this topic + neighbors ──
    const core = communityNodes.filter(n => (n.topics||[]).includes(filterTopic));
    totalAvail = core.length;
    // Take top 60 by size, plus all neighbors (up to 120 total)
    const topCore = core.slice(0, 60);
    const coreIds = new Set(topCore.map(n => n.id));
    neighborIds = new Set();
    communityEdges.forEach(e => {
      if (coreIds.has(e.source) && !coreIds.has(e.target)) neighborIds.add(e.target);
      if (coreIds.has(e.target) && !coreIds.has(e.source)) neighborIds.add(e.source);
    });
    const neighborArr = [...neighborIds].map(id => commById.get(id)).filter(Boolean);
    const topNeighbors = neighborArr.sort((a,b) => b.size - a.size).slice(0, 40);
    nodes = [...topCore, ...topNeighbors];
    const nodeIds = new Set(nodes.map(n => n.id));
    edges = communityEdges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
    neighborIds = new Set(topNeighbors.map(n => n.id));
    info.text(`${topCore.length}/${totalAvail} "${filterTopic}" communities + ${topNeighbors.length} connected`);
  } else {
    // ── All communities: top 100 by size ──
    totalAvail = communityNodes.length;
    nodes = communityNodes.slice(0, 100);
    const nodeIds = new Set(nodes.map(n => n.id));
    edges = communityEdges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
    neighborIds = new Set();
    info.text(`Top ${nodes.length} of ${totalAvail} communities | Scroll to zoom, drag to pan`);
  }

  const sizeScale = d3.scaleSqrt()
    .domain([1, d3.max(nodes, d => d.size) || 1])
    .range(mode === "topic" ? [18, 60] : [8, 40]);

  const link = g.append("g").selectAll("line").data(edges).join("line")
    .attr("class", "link")
    .attr("stroke", mode === "topic" ? "#64748b" : "#475569")
    .attr("stroke-width", d => Math.max(0.3, Math.sqrt(d.weight) * (mode === "topic" ? 1 : 0.5)));

  const node = g.append("g").selectAll("g").data(nodes).join("g")
    .attr("class", "node")
    .call(d3.drag()
      .on("start", (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on("end", (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }));

  node.append("circle")
    .attr("r", d => sizeScale(d.size))
    .attr("fill", d => {
      if (mode === "topic") return topicColor(d.label);
      return topicColor(d.primary_topic || "other");
    })
    .attr("opacity", d => (neighborIds && neighborIds.has(d.id)) ? 0.35 : 0.9)
    .attr("stroke", d => (neighborIds && neighborIds.has(d.id)) ? "#94a3b8" : "#1e293b")
    .attr("stroke-width", d => (neighborIds && neighborIds.has(d.id)) ? 1 : 1.5)
    .attr("stroke-dasharray", d => (neighborIds && neighborIds.has(d.id)) ? "4,2" : "none")
    .on("mouseover", (e, d) => {
      let html = `<b>${d.label}</b><br>`;
      if (mode === "topic") {
        html += `Concepts: ${d.size}<br>Communities: ${d.community_count}<br><i>Click to explore communities</i>`;
      } else {
        html += `Members: ${d.size}<br>Cohesion: ${d.cohesion.toFixed(2)}<br>Topics: ${(d.topics||[]).join(", ")}`;
        if (neighborIds && neighborIds.has(d.id)) html += `<br><i>(from other topics)</i>`;
      }
      tooltip.html(html).classed("visible", true);
    })
    .on("mousemove", e => tooltip.style("left",(e.pageX+14)+"px").style("top",(e.pageY-10)+"px"))
    .on("mouseout", () => tooltip.classed("visible", false))
    .on("click", (e, d) => {
      e.stopPropagation();
      if (mode === "topic") {
        simulation.stop();
        render("community", d.label);
      }
    });

  node.append("text")
    .text(d => d.label.length > 30 ? d.label.slice(0,28)+"…" : d.label)
    .attr("dy", d => sizeScale(d.size) + 13)
    .attr("font-size", mode === "topic" ? 12 : 10);

  simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(edges).id(d => d.id).distance(mode === "topic" ? 200 : 100))
    .force("charge", d3.forceManyBody().strength(mode === "topic" ? -500 : -250))
    .force("center", d3.forceCenter(W/2, H/2))
    .force("collision", d3.forceCollide(d => sizeScale(d.size) + 6))
    .on("tick", () => {
      link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
          .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
      node.attr("transform", d => `translate(${d.x},${d.y})`);
    });

  // Click empty space to go back (but only if click didn't hit a node)
  svg.on("click.background", () => {
    if (filterTopic) { simulation.stop(); render("topic"); }
    else if (mode === "community") { simulation.stop(); render("topic"); }
  });
}

// Search
d3.select("#search").on("input", function() {
  const q = this.value.toLowerCase();
  g.selectAll(".node").classed("dimmed", d => {
    if (!q) return false;
    return !d.label.toLowerCase().includes(q) && !(d.topics||[]).some(t => t.toLowerCase().includes(q));
  });
  g.selectAll(".link").classed("dimmed", !!q);
});

d3.select("#btn-topic").on("click", () => { if (simulation) simulation.stop(); render("topic"); });
d3.select("#btn-community").on("click", () => { if (simulation) simulation.stop(); render("community"); });

render("topic");
</script>
</body>
</html>"""


def merge_graphs(
    graph_paths: list[Path],
    output_dir: Path,
) -> dict:
    """Merge multiple graph.json files into one unified graph.

    Nodes are deduplicated by id; edges and hyperedges are concatenated.
    Communities are re-computed from the merged graph.
    """
    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    all_hyperedges: list[dict] = []

    for gp in graph_paths:
        if not gp.is_file():
            print(f"  SKIP: {gp} not found")
            continue
        data = json.loads(gp.read_text(encoding="utf-8"))
        topic = gp.parent.name
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        for n in nodes:
            n.setdefault("topics", []).append(topic)

        all_nodes.extend(nodes)
        all_edges.extend(edges)
        all_hyperedges.extend(data.get("hyperedges", []))

        print(f"  {topic}: {len(nodes)} nodes, {len(edges)} edges")

    # Deduplicate nodes by id, merging topic tags
    seen: dict[str, dict] = {}
    for n in all_nodes:
        nid = n["id"]
        if nid in seen:
            existing = set(seen[nid].get("topics", []))
            incoming = set(n.get("topics", []))
            seen[nid]["topics"] = sorted(existing | incoming)
        else:
            seen[nid] = n

    deduped_nodes = list(seen.values())
    dup_count = len(all_nodes) - len(deduped_nodes)

    merged = {
        "nodes": deduped_nodes,
        "edges": all_edges,
        "hyperedges": all_hyperedges,
    }

    # Rebuild graph and re-cluster across all topics
    from graphify.build import build as gf_build
    from graphify.cluster import cluster, score_all

    ast = {"nodes": [], "edges": [], "hyperedges": []}
    G = gf_build([ast, merged], dedup=True)
    communities = cluster(G)
    communities = {int(k): v for k, v in communities.items()}
    scores = score_all(G, communities)

    for cid, nids in communities.items():
        for nid in nids:
            if nid in G.nodes:
                G.nodes[nid]["community"] = cid

    # Build readable community labels from top-3 nodes
    labels: dict[int, str] = {}
    for cid in communities:
        parts = []
        for nid in communities[cid][:3]:
            if nid in G.nodes:
                parts.append(G.nodes[nid].get("label", nid)[:60])
        labels[cid] = " | ".join(parts) if parts else f"Community {cid}"

    # Export
    output_dir.mkdir(parents=True, exist_ok=True)
    output_data = {
        "nodes": [
            {"id": n, **{k: v for k, v in G.nodes[n].items() if k != "id"}}
            for n in G.nodes()
        ],
        "edges": [
            {"source": u, "target": v, **{k: v for k, v in G.edges[u, v].items()}}
            for u, v in G.edges()
        ],
        "communities": [
            {
                "id": cid,
                "label": labels[cid],
                "nodes": nodes,
                "cohesion": scores.get(cid, 0),
            }
            for cid, nodes in communities.items()
        ],
        "hyperedges": all_hyperedges,
    }
    (output_dir / "graph.json").write_text(
        json.dumps(output_data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    from graphify.export import to_html, to_obsidian

    try:
        to_html(G, communities, str(output_dir / "graph.html"), community_labels=labels)
        print("graph.html written")
    except ValueError:
        print("HTML skipped (graph too large)")

    try:
        hier_data = _prepare_hierarchical_data(G, communities, labels, scores)
        _write_hierarchical_html(hier_data, output_dir / "graph_hierarchical.html")
        print("graph_hierarchical.html written")
    except Exception as exc:
        print(f"Hierarchical HTML skipped: {exc}")

    try:
        to_obsidian(
            G, communities, str(output_dir / "obsidian"),
            community_labels=labels, cohesion=scores,
        )
        print("Obsidian vault written")
        n_topics, n_bridges = _write_topic_indexes(G, output_dir / "obsidian")
        print(f"Topic indexes: {n_topics} topics, {n_bridges} bridges")
    except Exception as exc:
        print(f"Obsidian vault skipped: {exc}")

    print(
        f"\nMerged: {len(deduped_nodes)} nodes ({dup_count} deduped), "
        f"{len(all_edges)} edges, {len(communities)} communities"
    )
    print(f"Output: {output_dir}")

    return output_data
