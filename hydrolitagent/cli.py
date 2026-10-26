from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """把仓库根的 .env 载入 os.environ(已存在的键不覆盖)。

    解析本身归 ``_config.read_dotenv_values`` —— 这里曾有第二份手写的
    dotenv 解析,且不剥离行内注释,``KEY=value  # 注释`` 会把注释一起当值。
    """
    from ._config import read_dotenv_values

    for key, value in read_dotenv_values().items():
        if key not in os.environ:
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


def add_paths_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "paths",
        help="Print the resolved literature product paths",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON (consumed by the skills)",
    )
    parser.set_defaults(cmd="paths")


def _paths_payload() -> dict[str, object]:
    """解析出的各产物路径 + 是否在工作区外 + 是否存在。

    由 ``literature._paths`` 提供 —— 那是全仓库唯一知道产物根在哪的地方。
    """
    from .literature import _paths

    root = _paths.OUTPUT_ROOT
    try:
        external = not root.resolve().is_relative_to(_paths.PROJECT_ROOT.resolve())
    except (OSError, ValueError):
        external = True

    payload: dict[str, object] = {
        "project_root": str(_paths.PROJECT_ROOT),
        "literature_root": str(root),
        "external": external,
    }
    for key, path in (
        ("weekly_review", _paths.WEEKLY_REVIEW_DIR),
        ("papers", _paths.PAPERS_DIR),
        ("bilibili", _paths.BILIBILI_DIR),
        ("zotero", _paths.ZOTERO_DIR),
    ):
        payload[key] = str(path)
        payload[f"{key}_exists"] = path.is_dir()
    return payload


def _print_paths(*, as_json: bool) -> None:
    payload = _paths_payload()
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    suffix = "  (工作区外)" if payload["external"] else ""
    print(f"仓库根: {payload['project_root']}")
    print(f"产物根: {payload['literature_root']}{suffix}")
    for key, label in (
        ("weekly_review", "周报产物"),
        ("papers", "PDF"),
        ("bilibili", "B站上传"),
        ("zotero", "NotebookLM"),
    ):
        mark = "✓" if payload[f"{key}_exists"] else "—"
        print(f"  {mark} {label:<10} {payload[key]}")
    if not payload["weekly_review_exists"]:
        print("\n(带 — 的目录尚未创建;跑对应流程时会自动建)")


def add_scholars_subparser(subparsers: argparse._SubParsersAction) -> None:
    """学者论文统计：按人检索 OpenAlex 并生成自查表数据。

    与 ``cards`` 一样是独立子 CLI；这里只放占位，实际 parser 在
    ``hydrolitagent/scholars/cli.py``。
    """
    subparsers.add_parser(
        "scholars",
        help="按人检索 OpenAlex 论文并生成学院自查统计",
    )


def add_cards_subparser(subparsers: argparse._SubParsersAction) -> None:
    """文献卡与主题卡：把参数原样透传给 hydrolitagent.cards.cli 自己的 parser。

    用 ``REMAINDER`` 而不是在这里重写 5 条命令的参数定义——那套 parser 已经写好了
    （``hydrolitagent/cards/cli.py``），重写一遍只会造成两处定义漂移。
    ``add_help=False`` 让 ``cards --help`` 落到内层 parser，输出那 5 条命令的说明。
    """
    # 只用于让 `hydrolitagent --help` 列出 cards；实际派发在 main() 入口拦截，
    # 不走 argparse（见那里的注释）。
    subparsers.add_parser(
        "cards",
        help="文献卡与主题卡:自己的 Zotero -> 文献卡 -> 主题卡",
    )


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
    add_paths_subparser(subparsers)
    add_cards_subparser(subparsers)
    add_scholars_subparser(subparsers)
    return parser


def main() -> None:
    # 入口统一兜底：默认中文 Windows 控制台（GBK/cp936）打不出 "✓" 等符号，
    # `paths` 人读分支曾因此抛 UnicodeEncodeError（finding F-R2-003）。
    # 从源头 reconfigure 而非捕 UnicodeEncodeError——后者会吞掉真正该暴露的
    # 编码问题；仓库先例见 scripts/download_paper.py 的同款写法。
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        # 老 Python 无 reconfigure / 流已关闭：不阻断主流程
        pass
    _load_dotenv()

    # `cards` 是一整套独立子 CLI（自带 parser 与 5 条命令）。这里直接透传 argv，
    # 不走 argparse 的 REMAINDER —— 后者会把 `cards --help` 里的 `--help` 当成
    # 外层选项，报 "unrecognized arguments: --help"。
    argv = sys.argv[1:]
    if argv and argv[0] == "cards":
        from hydrolitagent.cards.cli import main as cards_main

        raise SystemExit(cards_main(argv[1:]))
    if argv and argv[0] == "scholars":
        from hydrolitagent.scholars.cli import main as scholars_main

        raise SystemExit(scholars_main(argv[1:]))

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

    elif args.command == "paths":
        _print_paths(as_json=args.json)

    else:
        parser.print_help()
        sys.exit(1)
