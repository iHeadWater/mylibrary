from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .config import EnrichmentConfig
from .models import Record


def doi_from_identifier(identifier: str) -> str:
    if identifier.lower().startswith("doi:"):
        return identifier[4:].strip()
    if identifier.startswith("10."):
        return identifier.strip()
    return ""


def cache_key(record: Record) -> str:
    base = doi_from_identifier(record.identifier) or record.title
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


def fetch_json(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "hydrolitagent/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def openalex_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    positions: dict[int, str] = {}
    for word, indexes in inverted.items():
        for index in indexes:
            positions[index] = word
    return " ".join(positions[index] for index in sorted(positions))


def query_semantic_scholar(record: Record, timeout: int) -> dict[str, Any] | None:
    doi = doi_from_identifier(record.identifier)
    if doi:
        paper_id = "DOI:" + urllib.parse.quote(doi, safe="")
        url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}?fields=title,abstract,year,venue,authors,url,externalIds"
    else:
        query = urllib.parse.urlencode(
            {"query": record.title, "limit": 1, "fields": "title,abstract,year,venue,authors,url,externalIds"}
        )
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?{query}"
    data = fetch_json(url, timeout)
    if "data" in data:
        data = data["data"][0] if data["data"] else {}
    if not data:
        return None
    external = data.get("externalIds") or {}
    return {
        "provider": "semantic_scholar",
        "title": data.get("title") or "",
        "abstract": data.get("abstract") or "",
        "year": data.get("year") or "",
        "venue": data.get("venue") or "",
        "doi": external.get("DOI") or "",
        "url": data.get("url") or "",
        "authors": [author.get("name", "") for author in data.get("authors", []) if author.get("name")],
    }


def query_openalex(record: Record, timeout: int) -> dict[str, Any] | None:
    doi = doi_from_identifier(record.identifier)
    if doi:
        url = "https://api.openalex.org/works/doi:" + urllib.parse.quote(doi, safe="")
        data = fetch_json(url, timeout)
    else:
        query = urllib.parse.urlencode({"search": record.title, "per-page": 1})
        data = fetch_json(f"https://api.openalex.org/works?{query}", timeout)
        results = data.get("results") or []
        data = results[0] if results else {}
    if not data:
        return None
    return {
        "provider": "openalex",
        "title": data.get("title") or "",
        "abstract": openalex_abstract(data.get("abstract_inverted_index")),
        "year": data.get("publication_year") or "",
        "venue": ((data.get("primary_location") or {}).get("source") or {}).get("display_name") or "",
        "doi": (data.get("doi") or "").replace("https://doi.org/", ""),
        "url": data.get("id") or "",
        "authors": [
            item.get("author", {}).get("display_name", "")
            for item in data.get("authorships", [])
            if item.get("author", {}).get("display_name")
        ],
    }


def query_crossref(record: Record, timeout: int) -> dict[str, Any] | None:
    doi = doi_from_identifier(record.identifier)
    if doi:
        url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    else:
        query = urllib.parse.urlencode({"query.title": record.title, "rows": 1})
        url = f"https://api.crossref.org/works?{query}"
    data = fetch_json(url, timeout).get("message", {})
    if "items" in data:
        data = data["items"][0] if data["items"] else {}
    if not data:
        return None
    authors = []
    for author in data.get("author", []):
        authors.append(" ".join(part for part in [author.get("given"), author.get("family")] if part))
    return {
        "provider": "crossref",
        "title": (data.get("title") or [""])[0],
        "abstract": data.get("abstract") or "",
        "year": ((data.get("published-print") or data.get("published-online") or {}).get("date-parts") or [[""]])[0][0],
        "venue": (data.get("container-title") or [""])[0],
        "doi": data.get("DOI") or "",
        "url": data.get("URL") or "",
        "authors": authors,
    }


PROVIDERS = {
    "semantic_scholar": query_semantic_scholar,
    "openalex": query_openalex,
    "crossref": query_crossref,
}


def provider_order(record: Record, config: EnrichmentConfig) -> list[str]:
    configured = [provider for provider in config.providers if provider in PROVIDERS]
    if doi_from_identifier(record.identifier):
        preferred = ["semantic_scholar", "openalex", "crossref"]
    else:
        preferred = ["openalex", "semantic_scholar"]
    ordered = [provider for provider in preferred if provider in configured]
    if doi_from_identifier(record.identifier):
        ordered.extend(provider for provider in configured if provider not in ordered)
    return ordered


def load_cached(path: Path) -> dict[str, Any] | None:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_cached(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_enrichment(record: Record, data: dict[str, Any]) -> None:
    if data.get("title") and ("title_needs_confirmation" in record.review_flags or not record.title):
        record.title = data["title"]
        record.review_flags = [flag for flag in record.review_flags if flag != "title_needs_confirmation"]
    if data.get("abstract") and not record.summary:
        record.summary = data["abstract"]
    if data.get("url") and data["url"] not in record.evidence_links:
        record.evidence_links.append(data["url"])
    if data.get("doi") and not record.identifier:
        record.identifier = data["doi"]
    if data.get("venue") and not record.venue_or_type:
        record.venue_or_type = data["venue"]


def enrich_records(records: list[Record], config: EnrichmentConfig) -> None:
    for record in records:
        if record.kind != "paper":
            continue
        cache_path = config.cache_dir / f"{cache_key(record)}.json"
        cached = load_cached(cache_path)
        if cached:
            apply_enrichment(record, cached)
            continue
        enriched = None
        last_error = ""
        for provider in provider_order(record, config):
            func = PROVIDERS.get(provider)
            if not func:
                continue
            try:
                enriched = func(record, config.timeout_seconds)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = f"{provider}: {exc}"
                continue
            if enriched:
                break
        if enriched:
            save_cached(cache_path, enriched)
            apply_enrichment(record, enriched)
        else:
            record.review_flags.append("enrichment_failed")
            if last_error:
                record.review_flags.append(last_error[:120])
