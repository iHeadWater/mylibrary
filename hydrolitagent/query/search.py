"""Deterministic graph queries over graph.json — no LLM required."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any


def load_graph(path: str | Path) -> dict[str, Any]:
    """Load a graph.json file and return the full data dict."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _build_indexes(graph: dict) -> tuple[dict, dict, dict]:
    """Build lookup indexes for nodes, edges, communities."""
    node_index: dict[str, dict] = {n["id"]: n for n in graph.get("nodes", [])}
    community_index: dict[int, dict] = {
        c["id"]: c for c in graph.get("communities", [])
    }
    adj: dict[str, list[str]] = {}
    for e in graph.get("edges", []):
        adj.setdefault(e["source"], []).append(e["target"])
        adj.setdefault(e["target"], []).append(e["source"])
    return node_index, community_index, adj


def search_nodes(
    graph: dict,
    query: str,
    *,
    field: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search nodes by label, id, or attributes.

    Args:
        graph: Loaded graph dict.
        query: Case-insensitive search string.
        field: Restrict search to a specific field (label, id, authors, etc.).
        limit: Maximum results.

    Returns:
        List of matching node dicts (with community label appended).
    """
    q = query.lower()
    node_index, community_index, _ = _build_indexes(graph)
    results: list[dict] = []

    for node in node_index.values():
        if field:
            if field == "community":
                cid = node.get("community")
                if cid is not None and cid in community_index:
                    if q in community_index[cid]["label"].lower():
                        results.append(node)
            elif field in node:
                if q in str(node[field]).lower():
                    results.append(node)
            elif field in node.get("attributes", {}):
                if q in str(node["attributes"][field]).lower():
                    results.append(node)
        else:
            text = json.dumps(node, ensure_ascii=False).lower()
            if q in text:
                results.append(node)

        if len(results) >= limit:
            break

    for r in results:
        cid = r.get("community")
        if cid is not None and cid in community_index:
            r["_community_label"] = community_index[cid]["label"]

    return results


def get_neighbors(
    graph: dict,
    node_id: str,
    depth: int = 1,
) -> dict[str, Any]:
    """Get a node and its neighbors up to a given depth.

    Returns a dict with the center node, neighbor lists per depth, and edge details.
    """
    node_index, community_index, adj = _build_indexes(graph)

    if node_id not in node_index:
        return {"error": f"Node '{node_id}' not found", "neighbors": []}

    visited: set[str] = {node_id}
    layers: list[list[dict]] = []
    frontier = [node_id]

    for _ in range(depth):
        next_frontier: list[str] = []
        layer_nodes: list[dict] = []
        for nid in frontier:
            for neighbor_id in adj.get(nid, []):
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    next_frontier.append(neighbor_id)
                    nb = dict(node_index.get(neighbor_id, {"id": neighbor_id}))
                    cid = nb.get("community")
                    if cid is not None and cid in community_index:
                        nb["_community_label"] = community_index[cid]["label"]
                    layer_nodes.append(nb)
        if layer_nodes:
            layers.append(layer_nodes)
        frontier = next_frontier

    center = dict(node_index[node_id])
    cid = center.get("community")
    if cid is not None and cid in community_index:
        center["_community_label"] = community_index[cid]["label"]

    return {
        "node": center,
        "neighbors": layers,
        "depth": len(layers),
        "total_neighbors": sum(len(l) for l in layers),
    }


def find_path(graph: dict, source: str, target: str) -> dict[str, Any]:
    """Find the shortest path between two nodes via BFS.

    Returns the path as a list of node dicts with edge types between hops.
    """
    node_index, community_index, adj = _build_indexes(graph)
    edges_index: dict[tuple[str, str], dict] = {}
    for e in graph.get("edges", []):
        u, v = e["source"], e["target"]
        edges_index[(u, v)] = e
        edges_index[(v, u)] = e

    if source not in node_index:
        return {"error": f"Source node '{source}' not found", "path": []}
    if target not in node_index:
        return {"error": f"Target node '{target}' not found", "path": []}

    queue: deque[tuple[str, list[str]]] = deque([(source, [source])])
    visited = {source}

    while queue:
        current, path = queue.popleft()
        if current == target:
            detailed: list[dict] = []
            for i, nid in enumerate(path):
                entry: dict = {"id": nid, "label": node_index[nid].get("label", nid)}
                if i > 0:
                    prev = path[i - 1]
                    edge = edges_index.get((prev, nid), {})
                    entry["_edge_type"] = edge.get("type", "unknown")
                    entry["_confidence"] = edge.get("confidence", 0)
                detailed.append(entry)
            return {"path": detailed, "length": len(detailed) - 1}

        for neighbor in adj.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))

    return {"error": f"No path found between '{source}' and '{target}'", "path": []}


def get_community(graph: dict, community_id: int) -> dict[str, Any]:
    """Get all nodes and edges within a community."""
    node_index, community_index, adj = _build_indexes(graph)

    if community_id not in community_index:
        return {"error": f"Community {community_id} not found"}

    com = community_index[community_id]
    member_ids = set(com.get("nodes", []))

    nodes = [node_index[nid] for nid in member_ids if nid in node_index]
    edges = [
        e for e in graph.get("edges", [])
        if e["source"] in member_ids and e["target"] in member_ids
    ]

    return {
        "community": com,
        "nodes": nodes,
        "edges": edges,
    }
