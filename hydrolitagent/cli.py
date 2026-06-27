from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env file from project root into os.environ."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def add_prepare_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "prepare",
        help="Detect files and split into extraction chunks (step 1 of 3)",
    )
    parser.add_argument(
        "papers_dir",
        help="Directory containing paper markdown files",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=20,
        help="Files per extraction chunk (default: 20)",
    )
    parser.add_argument(
        "--working-dir",
        default="graphify-out",
        help="Working directory for intermediate files (default: graphify-out)",
    )
    parser.set_defaults(cmd="prepare")


def add_extract_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "extract",
        help="Run LLM extraction on prepared chunks (step 2 of 3)",
    )
    parser.add_argument(
        "papers_dir",
        help="Directory containing paper markdown files",
    )
    parser.add_argument(
        "--working-dir",
        default="graphify-out",
        help="Working directory with chunk manifests (default: graphify-out)",
    )
    parser.add_argument(
        "--backend",
        default="deepseek",
        choices=["deepseek", "gemini", "kimi", "claude", "openai", "ollama"],
        help="LLM backend for extraction (default: deepseek)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max parallel API calls (default: 4)",
    )
    parser.set_defaults(cmd="extract")


def add_graph_subparser(subparsers: argparse._SubParsersAction) -> None:
    import os as _os
    parser = subparsers.add_parser(
        "graph",
        help="Build knowledge graph from existing extraction chunks (step 3 of 3)",
    )
    parser.add_argument(
        "papers_dir",
        help="Directory containing paper markdown files",
    )
    parser.add_argument(
        "--output",
        default=_os.environ.get("HYDROLITAGENT_OUTPUT", "outputs/graph"),
        help="Output directory for final products (default from HYDROLITAGENT_OUTPUT env or outputs/graph)",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Incremental update: only process new or changed files",
    )
    parser.add_argument(
        "--prompt",
        default="configs/graph_prompts.toml",
        help="Path to domain-specific prompt configuration",
    )
    parser.set_defaults(cmd="graph")


def add_merge_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "merge",
        help="Merge multiple topic graphs into one unified graph",
    )
    parser.add_argument(
        "--graphs-dir",
        default="outputs/graph",
        help="Directory containing topic subdirectories with graph.json files",
    )
    parser.add_argument(
        "--output",
        default="outputs/graph/unified",
        help="Output directory for unified graph",
    )
    parser.set_defaults(cmd="merge")


def add_query_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "query",
        help="Query a knowledge graph (step 4: search/explore)",
    )
    parser.add_argument(
        "graph_file",
        help="Path to graph.json file",
    )
    parser.add_argument(
        "--search",
        help="Search nodes by keyword (label, id, attributes)",
    )
    parser.add_argument(
        "--field",
        help="Restrict search to a specific field (label, id, authors, etc.)",
    )
    parser.add_argument(
        "--neighbors",
        help="Get neighbors of a node (by node id)",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=1,
        help="Neighbor traversal depth (default: 1)",
    )
    parser.add_argument(
        "--path",
        nargs=2,
        metavar=("SOURCE", "TARGET"),
        help="Find shortest path between two node ids",
    )
    parser.add_argument(
        "--community",
        type=int,
        help="Get all nodes in a community (by community id)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum search results (default: 20)",
    )
    parser.set_defaults(cmd="query")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hydrolitagent",
        description="Literature knowledge base toolkit for hydrology research",
    )
    subparsers = parser.add_subparsers(dest="command", title="subcommands")
    add_prepare_subparser(subparsers)
    add_extract_subparser(subparsers)
    add_graph_subparser(subparsers)
    add_merge_subparser(subparsers)
    add_query_subparser(subparsers)
    return parser


def main() -> None:
    _load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "prepare":
        from .graph.build import prepare_graph

        wd, manifests = prepare_graph(
            papers_dir=args.papers_dir,
            working_dir=args.working_dir,
            chunk_size=args.chunk_size,
        )
        print(f"\nManifests written to {wd}/")
        print("Next: set your API key and run extraction, then:")
        print(f"  uv run hydrolitagent extract {args.papers_dir}")
        print(f"  uv run hydrolitagent graph {args.papers_dir}")

    elif args.command == "extract":
        from .graph.build import extract_chunks

        extract_chunks(
            papers_dir=args.papers_dir,
            working_dir=args.working_dir,
            backend=args.backend,
            max_concurrency=args.concurrency,
        )
        print(f"\nExtraction done. Next: uv run hydrolitagent graph {args.papers_dir}")

    elif args.command == "graph":
        from .graph.build import build_graph

        build_graph(
            papers_dir=args.papers_dir,
            output_dir=args.output,
            incremental=args.update,
            prompt_config=args.prompt,
        )

    elif args.command == "merge":
        from pathlib import Path
        from .graph.merge import merge_graphs

        graphs_dir = Path(args.graphs_dir)
        graph_paths = sorted(graphs_dir.glob("*/graph.json"))
        if not graph_paths:
            print(f"No graph.json files found under {graphs_dir}")
            sys.exit(1)
        merge_graphs(graph_paths, Path(args.output))

    elif args.command == "query":
        from .query import find_path, get_community, get_neighbors, load_graph, search_nodes

        graph = load_graph(args.graph_file)
        node_count = len(graph.get("nodes", []))
        edge_count = len(graph.get("edges", []))
        print(f"Loaded graph: {node_count} nodes, {edge_count} edges")

        if args.search:
            results = search_nodes(graph, args.search, field=args.field, limit=args.limit)
            print(f"\nSearch results for '{args.search}' ({len(results)} found):")
            for r in results:
                topics = ", ".join(r.get("topics", []))
                com = r.get("_community_label", "?")
                print(f"  [{r.get('file_type', '?')}] {r['label']}")
                print(f"    id: {r['id']}")
                if topics:
                    print(f"    topics: {topics}")
                print(f"    community: {com}")
                print()
        elif args.neighbors:
            result = get_neighbors(graph, args.neighbors, depth=args.depth)
            if "error" in result:
                print(result["error"])
            else:
                n = result["node"]
                print(f"Center: {n['label']} ({n['id']})")
                print(f"Community: {n.get('_community_label', '?')}")
                for i, layer in enumerate(result["neighbors"]):
                    print(f"\n  Depth {i+1}: {len(layer)} neighbors")
                    for nb in layer[:10]:
                        print(f"    - {nb['label']}")
                    if len(layer) > 10:
                        print(f"    ... and {len(layer) - 10} more")
        elif args.path:
            src, tgt = args.path
            result = find_path(graph, src, tgt)
            if "error" in result:
                print(result["error"])
            else:
                print(f"Path length: {result['length']} hops")
                for i, step in enumerate(result["path"]):
                    arrow = f" --[{step.get('_edge_type', '?')}]--> " if i > 0 else ""
                    print(f"  {i}{arrow}{step['label']} ({step['id']})")
        elif args.community is not None:
            result = get_community(graph, args.community)
            if "error" in result:
                print(result["error"])
            else:
                com = result["community"]
                print(f"Community {com['id']}: {com['label']}")
                print(f"Cohesion: {com.get('cohesion', '?')}")
                print(f"Nodes: {len(result['nodes'])}")
                print(f"Internal edges: {len(result['edges'])}")
                for n in result["nodes"][:15]:
                    print(f"  [{n.get('file_type', '?')}] {n['label']}")
                if len(result["nodes"]) > 15:
                    print(f"  ... and {len(result['nodes']) - 15} more nodes")

    else:
        parser.print_help()
        sys.exit(1)
