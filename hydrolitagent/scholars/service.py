"""单人/批量编排：一个人失败不影响整批，产物最后统一写出。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .collect import collect_records
from .config import ScholarsConfig
from .dedupe import dedupe_works
from .errors import ScholarsError
from .identity import resolve_identity
from .models import BatchResult, IdentityResult, PersonQuery, PersonResult, PersonStats, WorkRecord
from .openalex import OpenAlexClient
from .output import (
    write_form_summary,
    write_review_md,
    write_summary_audit,
    write_summary_json,
    write_works_by_person,
    write_works_csv,
)
from .stats import person_review_flags, summarize


def _filter_supplement(records: Sequence[WorkRecord], config: ScholarsConfig) -> list[WorkRecord]:
    kept: list[WorkRecord] = []
    for work in records:
        if config.query.work_types and work.work_type not in config.query.work_types:
            continue
        if not work.year:
            continue
        if work.year < config.query.from_date.year:
            continue
        if config.query.to_date is not None and work.year > config.query.to_date.year:
            continue
        kept.append(work)
    return kept


def _failed(query: PersonQuery, identity: IdentityResult, message: str, status: str = "failed") -> PersonResult:
    return PersonResult(
        query=query,
        identity=identity,
        stats=PersonStats(),
        status=status,
        error=message,
        review_flags=(identity.status,),
    )


def run_person(
    client: OpenAlexClient,
    query: PersonQuery,
    config: ScholarsConfig,
    *,
    supplement: Sequence[WorkRecord] = (),
) -> PersonResult:
    try:
        identity = resolve_identity(
            client,
            query,
            config.identity,
            from_year=config.query.from_date.year,
        )
    except ScholarsError as exc:
        return _failed(query, IdentityResult(status="invalid", message=str(exc)), str(exc))
    except Exception as exc:  # noqa: BLE001 - 单人失败隔离
        return _failed(query, IdentityResult(status="invalid"), f"{type(exc).__name__}: {exc}")

    if not identity.resolved:
        status = "ambiguous" if identity.status == "ambiguous" else "not_found"
        return PersonResult(
            query=query,
            identity=identity,
            stats=PersonStats(),
            status=status,
            review_flags=(identity.status, *identity.flags),
        )

    try:
        fetch = client.fetch_works(
            identity.author_ids,
            from_date=config.query.from_date.isoformat(),
            to_date=config.query.to_date.isoformat() if config.query.to_date else None,
            work_types=config.query.work_types,
            max_works=config.query.max_works,
        )
        records = collect_records(
            fetch.works,
            query,
            identity.author_ids,
            config,
            client=client,
        )
        records, _ = dedupe_works(records)
        supplement = _filter_supplement(supplement, config)
        if supplement:
            records, _ = dedupe_works([*records, *supplement])
        stats = summarize(
            records,
            include_retracted_in_total=config.query.include_retracted_in_total,
        )
        stats = replace(stats, fetched_count=len(fetch.works), truncated=fetch.truncated)
        flags = person_review_flags(records, identity, fetch)
        return PersonResult(
            query=query,
            identity=identity,
            stats=stats,
            works=tuple(records),
            review_flags=flags,
            status="ok",
        )
    except ScholarsError as exc:
        return _failed(query, identity, str(exc))
    except Exception as exc:  # noqa: BLE001 - 单人失败隔离
        return _failed(query, identity, f"{type(exc).__name__}: {exc}")


def make_client(
    config: ScholarsConfig,
    *,
    cache_dir: str | Path | None = None,
    refresh: bool = False,
    transport=None,
) -> OpenAlexClient:
    return OpenAlexClient(
        config.openalex,
        api_key=config.api_key,
        cache_dir=cache_dir,
        refresh=refresh,
        transport=transport,
    )


def run_batch(
    queries: Iterable[PersonQuery],
    config: ScholarsConfig,
    *,
    client: OpenAlexClient | None = None,
    supplements: dict[str, Sequence[WorkRecord]] | None = None,
    fail_fast: bool = False,
) -> BatchResult:
    supplements = supplements or {}
    owns_client = client is None
    client = client or make_client(config)
    results: list[PersonResult] = []
    try:
        for query in queries:
            result = run_person(
                client,
                query,
                config,
                supplement=supplements.get(query.name, ()),
            )
            results.append(result)
            if fail_fast and result.status != "ok":
                break
    finally:
        if owns_client:
            client.close()

    return BatchResult(
        people=tuple(results),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        config=config.to_dict(),
    )


def default_output_dir(config: ScholarsConfig) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return config.output.root / stamp


def write_outputs(batch: BatchResult, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "form_summary_csv": output_dir / "form_summary.csv",
        "summary_audit_csv": output_dir / "summary_audit.csv",
        "works_csv": output_dir / "works.csv",
        "works_by_person_md": output_dir / "works_by_person.md",
        "summary_json": output_dir / "summary.json",
        "review_md": output_dir / "review.md",
    }
    write_form_summary(paths["form_summary_csv"], batch.people)
    write_summary_audit(paths["summary_audit_csv"], batch.people)
    write_works_csv(paths["works_csv"], batch.people)
    write_works_by_person(paths["works_by_person_md"], batch)
    write_review_md(paths["review_md"], batch)
    batch_with_paths = replace(
        batch,
        outputs={key: str(path) for key, path in paths.items()},
    )
    write_summary_json(paths["summary_json"], batch_with_paths)
    return {key: str(path) for key, path in paths.items()}
