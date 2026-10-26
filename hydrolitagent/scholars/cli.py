"""``hydrolitagent scholars`` 子命令。

退出码：0 全部成功；2 配置/名单错误（无产物）；3 部分人员歧义/失败（产物已写）；130 中断。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .config import ScholarsConfig, load_config
from .errors import ConfigError, RosterError, ScholarsError
from .identity import resolve_identity
from .models import BatchResult, PersonQuery, WebCandidate
from .output import write_web_candidates
from .roster import load_roster, roster_person_to_query
from .service import default_output_dir, make_client, run_batch, write_outputs
from .websearch import load_supplement, search_web


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hydrolitagent scholars",
        description="按人/机构检索 OpenAlex 论文，统计产出、作者位次与研究方向",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve", help="确认作者身份；同名时只列候选，不自动选择")
    _add_common(resolve, require_name=False)
    _add_query_identity(resolve)

    stats = subparsers.add_parser("stats", help="单人统计并写出汇总/明细")
    _add_common(stats, require_name=False)
    _add_query_identity(stats)
    _add_run_options(stats)

    batch = subparsers.add_parser("batch", help="批量名单统计并写出汇总/明细")
    _add_common(batch, require_name=False)
    batch.add_argument("--roster", required=True, help="名单 CSV/TOML")
    _add_run_options(batch)
    _add_cache_options(batch)

    return parser


def _add_common(parser: argparse.ArgumentParser, *, require_name: bool) -> None:
    parser.add_argument("--config", help="配置文件；默认 configs/scholars.toml")
    parser.add_argument("--institution-id", help="覆盖单位 OpenAlex ID，如 I27357992")
    parser.add_argument("--from-date", help="统计起始日期，默认 2021-01-01")
    parser.add_argument("--to-date", help="统计截止日期，默认今天")
    parser.add_argument(
        "--work-type",
        action="append",
        dest="work_types",
        help="作品类型，可重复；默认 article/review/conference-paper",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")


def _add_query_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", help="中文姓名")
    parser.add_argument("--name-en", help="英文名/拼音名（OpenAlex 必需）")
    parser.add_argument("--alias", action="append", default=[], help="额外别名，可重复")
    parser.add_argument("--institute", default="", help="所属研究所（仅写入汇总表）")
    parser.add_argument("--orcid", default="", help="ORCID iD")
    parser.add_argument("--openalex-id", action="append", default=[], help="OpenAlex 作者 ID，可重复")
    _add_cache_options(parser)


def _add_cache_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cache-dir", help="OpenAlex 响应缓存目录")
    parser.add_argument("--no-cache", action="store_true", help="不使用缓存")
    parser.add_argument("--refresh", action="store_true", help="忽略缓存重新请求")


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", help="产物目录；默认 outputs/scholars/<时间戳>")
    parser.add_argument("--dry-run", action="store_true", help="只查询/打印，不写产物")
    parser.add_argument("--fail-fast", action="store_true", help="批量遇到第一个非 ok 人员就停止")
    parser.add_argument("--supplement", help="人工确认论文清单 CSV")
    parser.add_argument(
        "--web-search",
        choices=["none", "deepseek", "firecrawl"],
        default="none",
        help="中文库网页检索；deepseek 用 DEEPSEEK_API_KEY，结果只进候选，不计入统计",
    )


def _overrides(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if getattr(args, "institution_id", None):
        overrides["institution_id"] = args.institution_id
    if getattr(args, "from_date", None):
        overrides["from_date"] = args.from_date
    if getattr(args, "to_date", None):
        overrides["to_date"] = args.to_date
    if getattr(args, "work_types", None):
        overrides["work_types"] = args.work_types
    return overrides


def _load_config(args: argparse.Namespace) -> ScholarsConfig:
    return load_config(args.config, overrides=_overrides(args))


def _cache_dir(args: argparse.Namespace, config: ScholarsConfig) -> Path | None:
    if getattr(args, "no_cache", False):
        return None
    if getattr(args, "cache_dir", None):
        return Path(args.cache_dir)
    return config.output.root / ".cache"


def _query_from_args(args: argparse.Namespace) -> PersonQuery:
    names = [value for value in (args.name, args.name_en) if value]
    aliases = tuple(args.alias or ())
    if not names and not args.orcid and not args.openalex_id:
        raise ConfigError("需要 --name / --name-en 之一，或 --orcid / --openalex-id")
    name = names[0] if names else ""
    if len(names) > 1:
        # --name-en 作为别名参与检索，--name 作为表格姓名
        aliases = tuple(dict.fromkeys([*aliases, *names[1:]]))
    return PersonQuery(
        name=name or (args.orcid or (args.openalex_id or [""])[0]),
        institute=args.institute or "",
        aliases=aliases,
        orcid=args.orcid or "",
        openalex_ids=tuple(args.openalex_id or ()),
        index=1,
    )


def _emit(payload: dict[str, Any], *, as_json: bool, human: list[str]) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("\n".join(human))


def _error_payload(operation: str, exc: Exception) -> dict[str, Any]:
    code = getattr(exc, "code", "INTERNAL_ERROR")
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "operation": operation,
        "status": "error",
        "error": {"code": code, "message": str(exc)},
    }


def _cmd_resolve(args: argparse.Namespace) -> int:
    config = _load_config(args)
    query = _query_from_args(args)
    client = make_client(
        config,
        cache_dir=_cache_dir(args, config),
        refresh=args.refresh,
    )
    try:
        identity = resolve_identity(
            client,
            query,
            config.identity,
            from_year=config.query.from_date.year,
        )
    finally:
        client.close()

    payload = {
        "schema_version": SCHEMA_VERSION,
        "ok": identity.resolved,
        "operation": "scholars_resolve",
        "status": identity.status,
        "query": query.to_dict(),
        "identity": identity.to_dict(),
        "error": None,
    }
    human = [f"状态：{identity.status}"]
    if identity.message:
        human.append(identity.message)
    if identity.candidates:
        human.append("")
        human.append(f"候选（{len(identity.candidates)}）：")
        for candidate in identity.candidates:
            human.append(
                f"  {candidate.openalex_id}  {candidate.display_name}  "
                f"{candidate.works_count} 篇  ORCID={candidate.orcid or '-'}  "
                f"单位={'、'.join(candidate.institutions[:3]) or '-'}  "
                f"评分={candidate.score}  {candidate.url}"
            )
    if identity.resolved:
        human.append("")
        human.append("已确定作者 ID：" + "、".join(identity.author_ids))
    _emit(payload, as_json=args.json, human=human)
    return 0 if identity.resolved else 3


def _run_queries(
    args: argparse.Namespace,
    config: ScholarsConfig,
    queries: Sequence[PersonQuery],
    *,
    operation: str,
) -> tuple[BatchResult, dict[str, str], list[WebCandidate]]:
    supplements = load_supplement(args.supplement) if args.supplement else {}
    client = make_client(
        config,
        cache_dir=_cache_dir(args, config),
        refresh=getattr(args, "refresh", False),
    )
    try:
        batch = run_batch(
            queries,
            config,
            client=client,
            supplements=supplements,
            fail_fast=args.fail_fast,
        )
    finally:
        client.close()

    web_candidates: list[WebCandidate] = []
    if args.web_search != "none":
        for query in queries:
            try:
                web_candidates.extend(search_web(query, config, args.web_search))
            except ScholarsError as exc:
                print(f"[warn] {query.name} 网页检索失败：{exc}", file=sys.stderr)

    outputs: dict[str, str] = {}
    if not args.dry_run:
        output_dir = Path(args.output_dir) if args.output_dir else default_output_dir(config)
        outputs = write_outputs(batch, output_dir)
        if web_candidates:
            candidate_path = output_dir / "web_candidates.csv"
            write_web_candidates(candidate_path, web_candidates)
            outputs["web_candidates_csv"] = str(candidate_path)
    return batch, outputs, web_candidates


def _batch_payload(batch: BatchResult, outputs: dict[str, str], operation: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": batch.ok,
        "operation": operation,
        "status": "complete" if batch.ok else "partial",
        "generated_at": batch.generated_at,
        "config": batch.config,
        "totals": batch.totals(),
        "people": [person.to_dict() for person in batch.people],
        "outputs": outputs,
        "error": None if batch.ok else {
            "code": "PARTIAL_FAILURE",
            "message": "有人员未解析或查询失败；数量列已留空，详见 review.md。",
        },
    }


def _human_batch(batch: BatchResult, outputs: dict[str, str]) -> list[str]:
    lines = [
        "序号  姓名        状态        论文数  第一/通讯  复核标记",
    ]
    for index, person in enumerate(batch.people, start=1):
        paper = str(person.stats.paper_count) if person.status == "ok" else "-"
        first = str(person.stats.first_or_corresponding_count) if person.status == "ok" else "-"
        lines.append(
            f"{person.query.index or index:<4}  {person.query.name:<10}  "
            f"{person.status:<10}  {paper:<6}  {first:<8}  "
            f"{'；'.join(person.review_flags) or '-'}"
        )
    if outputs:
        lines.append("")
        lines.append("产物：")
        for key, path in outputs.items():
            lines.append(f"  {key}: {path}")
    return lines


def _cmd_stats(args: argparse.Namespace) -> int:
    config = _load_config(args)
    query = _query_from_args(args)
    batch, outputs, _ = _run_queries(args, config, [query], operation="scholars_stats")
    payload = _batch_payload(batch, outputs, "scholars_stats")
    _emit(payload, as_json=args.json, human=_human_batch(batch, outputs))
    return 0 if batch.ok else 3


def _cmd_batch(args: argparse.Namespace) -> int:
    config = _load_config(args)
    roster = load_roster(args.roster)
    for warning in roster.warnings:
        print(f"[warn] {warning}", file=sys.stderr)
    queries = [roster_person_to_query(person) for person in roster.people]
    batch, outputs, _ = _run_queries(args, config, queries, operation="scholars_batch")
    payload = _batch_payload(batch, outputs, "scholars_batch")
    _emit(payload, as_json=args.json, human=_human_batch(batch, outputs))
    return 0 if batch.ok else 3


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdio()
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "resolve":
            return _cmd_resolve(args)
        if args.command == "stats":
            return _cmd_stats(args)
        if args.command == "batch":
            return _cmd_batch(args)
        parser.print_help()
        return 2
    except (ConfigError, RosterError) as exc:
        _emit(_error_payload(args.command, exc), as_json=args.json, human=[f"错误：{exc}"])
        return 2
    except ScholarsError as exc:
        _emit(_error_payload(args.command, exc), as_json=args.json, human=[f"错误：{exc}"])
        return 3
    except KeyboardInterrupt:
        return 130
