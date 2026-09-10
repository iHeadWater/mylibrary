"""Build knowledge graph from graphify extraction chunks.

Three phases:
  1. PREPARE (prepare_graph): detect files → split into chunks → write manifests
  2. EXTRACTION (manual subagents): Claude Code runs /graphify on each chunk
  3. BUILD (build_graph): merge chunks → build graph → cluster → report → export → save

Usage:
  uv run hydrolitagent graph papers/remote-sensing-hydro  # single command after extraction
"""

from __future__ import annotations

import json
import glob
import shutil
from pathlib import Path


def prepare_graph(
    papers_dir: str,
    working_dir: str = "graphify-out",
    chunk_size: int = 20,
) -> tuple[Path, list[Path]]:
    """Detect files and split into chunks. Writes manifests to working_dir.

    Returns (working_dir_path, list_of_manifest_paths).
    Does NOT run extraction — dispatch Claude Code subagents after this.
    """
    from graphify.detect import detect

    papers_path = Path(papers_dir).resolve()
    if not papers_path.is_dir():
        raise FileNotFoundError(f"Directory not found: {papers_path}")

    wd = Path(working_dir).resolve()
    wd.mkdir(parents=True, exist_ok=True)

    # Record root so graphify knows where to look
    (wd / ".graphify_root").write_text(str(papers_path), encoding="utf-8")

    result = detect(papers_path)
    (wd / ".graphify_detect.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Detected: {result['total_files']} files, {result['total_words']:,} words")

    files = sorted(papers_path.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"No .md files found in {papers_path}")

    chunks = [files[i : i + chunk_size] for i in range(0, len(files), chunk_size)]
    total = len(chunks)
    manifests: list[Path] = []

    for i, chunk in enumerate(chunks):
        manifest = {
            "files": [str(f) for f in chunk],
            "chunk": i + 1,
            "total_chunks": total,
        }
        mp = wd / f".graphify_chunk_{i + 1:02d}_manifest.json"
        mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        manifests.append(mp)

    print(f"Split into {total} chunks of ~{chunk_size} files each")
    return wd, manifests


def _merge_chunks(working_dir: Path) -> dict:
    """Merge all .graphify_chunk_NN.json files into one semantic dict."""
    chunks = sorted(
        c for c in glob.glob(str(working_dir / ".graphify_chunk_*.json"))
        if "manifest" not in c
    )
    if not chunks:
        raise FileNotFoundError(f"No chunk files found in {working_dir}")

    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    all_hyperedges: list[dict] = []

    for c in chunks:
        d = json.loads(Path(c).read_text(encoding="utf-8"))
        all_nodes += d.get("nodes", [])
        all_edges += d.get("edges", [])
        all_hyperedges += d.get("hyperedges", [])

    seen: set[str] = set()
    deduped: list[dict] = []
    for n in all_nodes:
        if n["id"] not in seen:
            seen.add(n["id"])
            deduped.append(n)

    # Normalize confidence_score to float (subagents sometimes emit strings or wrong field values)
    for e in all_edges:
        cs = e.get("confidence_score")
        if isinstance(cs, str):
            try:
                e["confidence_score"] = float(cs)
            except (ValueError, TypeError):
                # Edge has confidence level string (e.g. "EXTRACTED") in score field
                c = e.get("confidence", "")
                e["confidence_score"] = 1.0 if c == "EXTRACTED" else 0.75 if c == "INFERRED" else 0.3
    for h in all_hyperedges:
        cs = h.get("confidence_score")
        if isinstance(cs, str):
            try:
                h["confidence_score"] = float(cs)
            except (ValueError, TypeError):
                c = h.get("confidence", "")
                h["confidence_score"] = 1.0 if c == "EXTRACTED" else 0.75 if c == "INFERRED" else 0.3

    merged = {"nodes": deduped, "edges": all_edges, "hyperedges": all_hyperedges}
    out_path = working_dir / ".graphify_semantic.json"
    out_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Merged {len(chunks)} chunks: {len(deduped)} nodes, {len(all_edges)} edges")
    return merged


def _build_graph(semantic: dict) -> "tuple[object, dict, dict]":
    from graphify.build import build as gf_build
    from graphify.cluster import cluster, score_all

    ast = {"nodes": [], "edges": [], "hyperedges": []}
    G = gf_build([ast, semantic], dedup=True)
    print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # graphify >=0.8: cluster() returns dict[int, list[str]] directly
    communities = cluster(G)
    communities = {int(k): v for k, v in communities.items()}

    scores = score_all(G, communities)
    for cid, nids in communities.items():
        for nid in nids:
            if nid in G.nodes:
                G.nodes[nid]["community"] = cid

    print(f"Communities: {len(communities)}")
    return G, communities, scores


def _build_community_labels(G: object, communities: dict) -> dict[int, str]:
    labels: dict[int, str] = {}
    for cid in communities:
        label_nodes = communities[cid][:3]
        parts = []
        for nid in label_nodes:
            if nid in G.nodes:
                parts.append(G.nodes[nid].get("label", nid)[:60])
        labels[cid] = " | ".join(parts) if parts else f"Community {cid}"
    return labels


def _generate_report(
    G: object,
    communities: dict,
    scores: dict,
    community_labels: dict,
    working_dir: Path,
    papers_dir: str,
) -> str:
    from graphify.analyze import god_nodes, surprising_connections
    from graphify.report import generate

    gods = god_nodes(G, top_n=10)
    surprises = surprising_connections(G, communities, top_n=5)

    detect_path = working_dir / ".graphify_detect.json"
    detection = {}
    if detect_path.exists():
        detection = json.loads(detect_path.read_text(encoding="utf-8"))

    token_cost = {"input_tokens": 0, "output_tokens": 0}
    report_text = generate(
        G, communities, scores, community_labels, gods, surprises,
        detection, token_cost, papers_dir,
    )
    (working_dir / "GRAPH_REPORT.md").write_text(report_text, encoding="utf-8")
    print("GRAPH_REPORT.md written")
    return report_text


def _export_outputs(
    G: object, communities: dict, scores: dict,
    community_labels: dict, working_dir: Path, semantic: dict,
) -> None:
    from graphify.export import to_html, to_obsidian

    graph_data = {
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
                "label": community_labels[cid],
                "nodes": nodes,
                "cohesion": scores.get(cid, 0),
            }
            for cid, nodes in communities.items()
        ],
        "hyperedges": semantic.get("hyperedges", []),
    }
    (working_dir / "graph.json").write_text(
        json.dumps(graph_data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print("graph.json written")

    to_html(G, communities, str(working_dir / "graph.html"), community_labels=community_labels)
    print("graph.html written")

    try:
        from hydrolitagent.graph.merge import _prepare_hierarchical_data, _write_hierarchical_html
        hier_data = _prepare_hierarchical_data(G, communities, community_labels, scores)
        _write_hierarchical_html(hier_data, working_dir / "graph_hierarchical.html")
        print("graph_hierarchical.html written")
    except Exception as exc:
        print(f"Hierarchical HTML skipped: {exc}")

    to_obsidian(
        G, communities, str(working_dir / "obsidian"),
        community_labels=community_labels, cohesion=scores,
    )
    print("Obsidian vault written")


def _save_outputs(working_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ["graph.json", "graph.html", "graph_hierarchical.html", "GRAPH_REPORT.md"]:
        src = working_dir / name
        if src.exists():
            shutil.copy2(src, output_dir / name)

    obsidian_src = working_dir / "obsidian"
    obsidian_dst = output_dir / "obsidian"
    if obsidian_src.is_dir():
        if obsidian_dst.exists():
            shutil.rmtree(obsidian_dst)
        try:
            shutil.copytree(obsidian_src, obsidian_dst)
        except (OSError, shutil.Error):
            print("Obsidian vault copy skipped (long paths on Windows)")
    print(f"Outputs saved to {output_dir}")


def extract_chunks(
    papers_dir: str,
    working_dir: str = "graphify-out",
    backend: str = "deepseek",
    max_concurrency: int = 4,
    token_budget: int | None = 60_000,
) -> dict:
    """Run semantic extraction on all chunks using a direct LLM backend.

    Reads manifests from working_dir, extracts each chunk via graphify's
    llm.extract_corpus_parallel, and writes results as .graphify_chunk_NN.json.

    Set DEEPSEEK_API_KEY (or the equivalent for your backend) before running.
    Returns the merged extraction result dict.
    """
    import json
    import glob as glob_mod
    from pathlib import Path

    from graphify.llm import extract_corpus_parallel, detect_backend

    wd = Path(working_dir).resolve()
    if not wd.is_dir():
        raise FileNotFoundError(f"Working directory not found: {wd}")

    manifests = sorted(glob_mod.glob(str(wd / ".graphify_chunk_*_manifest.json")))
    if not manifests:
        raise FileNotFoundError(f"No chunk manifests found in {wd}. Run 'prepare' first.")

    resolved_backend = backend if backend else detect_backend() or "deepseek"
    print(f"Backend: {resolved_backend}")

    all_files: list[Path] = []
    for mp in manifests:
        m = json.loads(Path(mp).read_text(encoding="utf-8"))
        all_files.extend(Path(f) for f in m["files"] if Path(f).exists())

    if not all_files:
        raise FileNotFoundError("No source files found from manifests.")

    print(f"Extracting {len(all_files)} files across {len(manifests)} chunks...")

    def on_chunk_done(idx: int, total: int, result: dict) -> None:
        chunk_num = idx + 1
        out_path = wd / f".graphify_chunk_{chunk_num:02d}.json"
        # Remove internal accumulator keys before writing
        clean = {k: v for k, v in result.items() if k not in ("failed_chunks", "elapsed_seconds")}
        out_path.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
        nodes = len(clean.get("nodes", []))
        edges = len(clean.get("edges", []))
        elapsed = result.get("elapsed_seconds", 0)
        print(f"  chunk {chunk_num:02d}/{total}: {nodes} nodes, {edges} edges ({elapsed:.0f}s)")

    merged = extract_corpus_parallel(
        all_files,
        backend=resolved_backend,
        root=Path(papers_dir).resolve(),
        on_chunk_done=on_chunk_done,
        token_budget=token_budget,
        max_concurrency=max_concurrency,
    )

    total_nodes = len(merged.get("nodes", []))
    total_edges = len(merged.get("edges", []))
    total_in = merged.get("input_tokens", 0)
    total_out = merged.get("output_tokens", 0)
    print(f"Extraction done: {total_nodes} nodes, {total_edges} edges ({total_in:,} in / {total_out:,} out tokens)")
    return merged


def build_graph(
    papers_dir: str,
    output_dir: str = "outputs/graph",
    incremental: bool = False,
    prompt_config: str = "configs/graph_prompts.toml",
) -> None:
    """Run the full graphify build pipeline.

    Expects graphify-out/.graphify_chunk_NN.json from extraction phase.
    Steps: merge → build → cluster → report → export → save
    """
    papers_path = Path(papers_dir).resolve()
    output_path = Path(output_dir).resolve()
    working_dir = Path("graphify-out").resolve()

    if not working_dir.is_dir():
        raise FileNotFoundError(
            "graphify-out/ not found. Run extraction first (/graphify in Claude Code)."
        )

    # 1. Merge
    semantic_path = working_dir / ".graphify_semantic.json"
    if semantic_path.exists():
        semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
        print(f"Using existing semantic: {len(semantic.get('nodes',[]))} nodes, {len(semantic.get('edges',[]))} edges")
    else:
        semantic = _merge_chunks(working_dir)

    if not semantic.get("nodes"):
        raise ValueError("No nodes in semantic extraction. Run extraction first.")

    # 2. Build + cluster
    G, communities, scores = _build_graph(semantic)
    community_labels = _build_community_labels(G, communities)

    # 3. Report
    _generate_report(G, communities, scores, community_labels, working_dir, str(papers_path))

    # 4. Export
    _export_outputs(G, communities, scores, community_labels, working_dir, semantic)

    # 5. Save directly to output directory
    _save_outputs(working_dir, output_path)

    print(f"\n=== Done: {papers_path.name} ===")
