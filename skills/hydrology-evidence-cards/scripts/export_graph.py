#!/usr/bin/env python3
"""Export Source-Claim-Decision relations from v1.2 Markdown cards to JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_card import blank, json_blocks, parse_frontmatter


def add_node(nodes: dict[str, dict], node_id: str, data: dict, path: Path) -> None:
    if node_id in nodes:
        raise ValueError(f"duplicate node id {node_id}: {nodes[node_id]['path']} and {path}")
    nodes[node_id] = {**data, "path": str(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(args.root)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    unresolved: list[dict] = []

    for path in root.rglob("*.md"):
        text = path.read_text(encoding="utf-8-sig")
        meta = parse_frontmatter(text)
        if meta.get("card_schema") != "evidence-card-v1.2":
            continue
        if meta.get("card_type") == "source_evidence":
            source_id = str(meta.get("source_manifestation_id", ""))
            if not blank(source_id):
                add_node(nodes, source_id, {
                    "kind": "source",
                    "work_id": meta.get("source_work_id"),
                    "artifact_type": meta.get("artifact_type"),
                    "version": meta.get("source_version"),
                    "card_id": meta.get("card_id"),
                }, path)
            claims, _ = json_blocks(text, "claim-json")
            for claim in claims:
                claim_id = str(claim.get("claim_id", ""))
                if blank(claim_id):
                    continue
                add_node(nodes, claim_id, {
                    "kind": "claim",
                    "statement": claim.get("statement"),
                    "support_status": claim.get("support_status"),
                    "verification_status": claim.get("verification_status"),
                }, path)
                edges.append({"from": claim_id, "to": source_id, "type": "derived_from"})
                relations = claim.get("relations", {})
                if isinstance(relations, dict):
                    for relation, targets in relations.items():
                        if isinstance(targets, list):
                            edges.extend({"from": claim_id, "to": str(target), "type": relation} for target in targets)
        elif meta.get("card_type") == "decision_synthesis":
            decisions, _ = json_blocks(text, "decision-json")
            for decision in decisions:
                decision_id = str(decision.get("decision_id", ""))
                if blank(decision_id):
                    continue
                add_node(nodes, decision_id, {
                    "kind": "decision",
                    "conclusion": decision.get("current_conclusion"),
                    "decision_effect": decision.get("decision_effect"),
                    "card_id": meta.get("card_id"),
                }, path)
                for claim_id in decision.get("included_claims", []):
                    edges.append({"from": decision_id, "to": str(claim_id), "type": "uses"})
                for claim_id in decision.get("excluded_claims", []):
                    edges.append({"from": decision_id, "to": str(claim_id), "type": "excludes"})

    for edge in edges:
        if edge["from"] not in nodes or edge["to"] not in nodes:
            unresolved.append(edge)

    result = {
        "schema": "evidence-graph-v1.2",
        "root": str(root.resolve()),
        "nodes": list(nodes.values()),
        "edges": edges,
        "unresolved_edges": unresolved,
        "counts": {
            "sources": sum(n["kind"] == "source" for n in nodes.values()),
            "claims": sum(n["kind"] == "claim" for n in nodes.values()),
            "decisions": sum(n["kind"] == "decision" for n in nodes.values()),
            "edges": len(edges),
            "unresolved_edges": len(unresolved),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()

