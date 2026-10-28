"""Validated single-paper drafts as sources of the unified theme pipeline.

The theme pipeline used to read only evidence packs. The pack entry point
(``evidence-generate --item-key``) was removed together with the legacy
PDF-reading adapter, while the Markdown-first single-paper path keeps producing
drafts under ``<literature root>/zotero/<identity>/drafts/<draft id>/``. This
module turns those drafts into the same source record shape the pack scanner
produces, so the rest of the theme pipeline does not learn a second contract.

A draft is a source only when a separate validation record still describes the
current bytes:

* the draft says it is awaiting validation and was produced by the Markdown
  pipeline;
* its newest validation record passed, verified the reading and is eligible for
  theme generation;
* that record's ``draft_sha256`` equals the canonical fingerprint of the draft
  on disk, i.e. the draft has not changed since it was validated.

The draft is never re-validated here (that is ``card_validation``'s job), never
rewritten, and never moved. A rejected draft is counted under a stable reason
key and does not stop the other sources.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from hydrolitagent._config import resolve_literature_root
from hydrolitagent.cards.card_validation import fingerprint, read_strict_json
from hydrolitagent.cards.publication import text_hash

DRAFT_STATUS = "DRAFT_PENDING_VALIDATION"
DRAFT_PIPELINE = "markdown"
DRAFT_FILENAME = "draft.json"
CARD_FILENAME = "card.md"
EVIDENCE_PREFIX = "EV-"

# Every scan reports the same keys, zero included, so a run report's schema does
# not depend on which sources happened to be broken this time.
REJECT_REASONS = (
    "unvalidated",        # no draft.json, wrong state, or no validation record yet
    "failed_validation",  # the newest validation record did not pass
    "partial",            # passed the rules but the reading was not verified
    "stale",              # validated bytes differ from the draft on disk now
    "foreign_group",      # group library that is not the configured target
    "invalid_identity",   # malformed key, hash, size, library or path
    "unreadable",         # JSON/card/record could not be read
)

KEY_PATTERN = re.compile(r"[A-Z0-9]{8}")
SHA256_PATTERN = re.compile(r"[a-f0-9]{64}")
DRAFT_ID_PATTERN = re.compile(r"[a-f0-9]{16}")
EVIDENCE_ID_PATTERN = re.compile(r"EV-[A-Z0-9]{8}")


@dataclass(frozen=True)
class DraftSource:
    """One validated draft, ready to be handed to the theme workflow."""

    evidence_id: str
    directory: Path
    card: str
    record: dict[str, Any]
    pdf_size_bytes: int
    converter_id: str | None
    converter_version: str | None


@dataclass(frozen=True)
class DraftScan:
    items: tuple[DraftSource, ...]
    rejected: dict[str, int]
    root: Path


def _empty_rejections() -> dict[str, int]:
    return {reason: 0 for reason in REJECT_REASONS}


def _reject(rejected: dict[str, int], reason: str) -> tuple[None, str]:
    rejected[reason] += 1
    return None, reason


def _validated_at(record: dict[str, Any]) -> datetime | None:
    value = record.get("validated_at")
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def newest_validation(directory: Path) -> tuple[dict[str, Any] | None, str]:
    """Return the newest parseable validation record, or a rejection reason.

    A later record always wins: a re-validation that failed must not be masked
    by an older pass, otherwise a stale PASS label would admit the draft.
    """

    paths = sorted((directory / "validations").glob("*/validation.json"))
    if not paths:
        return None, "unvalidated"
    dated: list[tuple[datetime, int, dict[str, Any]]] = []
    for index, path in enumerate(paths):
        try:
            record = read_strict_json(path)
        except (OSError, ValueError, TypeError, RecursionError):
            continue
        if not isinstance(record, dict):
            continue
        moment = _validated_at(record)
        if moment is None:
            continue
        dated.append((moment, index, record))
    if not dated:
        return None, "unreadable"
    dated.sort(key=lambda item: (item[0], item[1]))
    return dated[-1][2], ""


def _identity(source: Any, group_id: int | None) -> tuple[dict[str, Any] | None, str]:
    """Validate the draft's source block and return it with the library group."""

    if not isinstance(source, dict):
        return None, "invalid_identity"
    library = source.get("library")
    if (not isinstance(library, dict)
            or library.get("type") not in {"user", "group"}
            or type(library.get("id")) is not int or library["id"] < 0
            or (library["type"] == "group" and library["id"] == 0)):
        return None, "invalid_identity"
    group = None if library["type"] == "user" else library["id"]
    if library["type"] == "group" and group != group_id:
        return None, "foreign_group"
    parent_key, attachment_key = source.get("parent_key"), source.get("attachment_key")
    if (not isinstance(parent_key, str) or not KEY_PATTERN.fullmatch(parent_key)
            or not isinstance(attachment_key, str) or not KEY_PATTERN.fullmatch(attachment_key)
            or not isinstance(source.get("pdf_sha256"), str)
            or not SHA256_PATTERN.fullmatch(source["pdf_sha256"])
            or type(source.get("pdf_size_bytes")) is not int
            or source["pdf_size_bytes"] < 1):
        return None, "invalid_identity"
    return {
        "group_id": group,
        "parent_key": parent_key,
        "attachment_key": attachment_key,
        "pdf_sha256": source["pdf_sha256"],
        "pdf_size_bytes": source["pdf_size_bytes"],
    }, ""


def inspect_draft(
    directory: Path, *, literature_root: Path, group_id: int | None
) -> tuple[DraftSource | None, str]:
    """Accept one draft directory or return ``(None, reason)``.

    The reason strings are the keys of ``REJECT_REASONS``; the caller counts
    them instead of silently dropping a source.
    """

    root = Path(literature_root).resolve()
    try:
        resolved = Path(directory).resolve(strict=True)
    except OSError:
        return None, "unreadable"
    if not resolved.is_relative_to(root):
        return None, "invalid_identity"

    draft_path = resolved / DRAFT_FILENAME
    if not draft_path.is_file():
        return None, "unvalidated"
    try:
        draft = read_strict_json(draft_path)
    except (OSError, ValueError, TypeError, RecursionError):
        return None, "unreadable"
    if not isinstance(draft, dict):
        return None, "unreadable"
    if (draft.get("status") != DRAFT_STATUS or draft.get("pipeline") != DRAFT_PIPELINE):
        return None, "unvalidated"
    draft_id = draft.get("draft_id")
    if not isinstance(draft_id, str) or not DRAFT_ID_PATTERN.fullmatch(draft_id):
        return None, "invalid_identity"

    identity, reason = _identity(draft.get("source"), group_id)
    if identity is None:
        return None, reason

    try:
        card = (resolved / CARD_FILENAME).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, "unreadable"

    record, reason = newest_validation(resolved)
    if record is None:
        return None, reason
    if record.get("status") != "PASS" or record.get("ok") is not True:
        return None, "failed_validation"
    if (record.get("reading_verified") is not True
            or record.get("eligible_for_theme_generation") is not True):
        return None, "partial"
    try:
        current = fingerprint(draft)
    except (ValueError, TypeError, OverflowError, RecursionError):
        # A value that cannot be canonicalised (e.g. 1e999) is not a draft the
        # validator could have hashed either.
        return None, "unreadable"
    if record.get("draft_id") != draft_id or record.get("draft_sha256") != current:
        return None, "stale"

    parent_key = identity["parent_key"]
    evidence_id = EVIDENCE_PREFIX + parent_key
    if not EVIDENCE_ID_PATTERN.fullmatch(evidence_id):
        return None, "invalid_identity"
    provenance = draft.get("provenance")
    converter_id = converter_version = None
    if isinstance(provenance, dict):
        candidate_id, candidate_version = provenance.get("converter_id"), provenance.get("converter_version")
        if isinstance(candidate_id, str) and isinstance(candidate_version, str):
            converter_id, converter_version = candidate_id, candidate_version
    return DraftSource(
        evidence_id=evidence_id,
        directory=resolved,
        card=card,
        record={
            "evidence_id": evidence_id,
            "group_id": identity["group_id"],
            "parent_key": parent_key,
            "attachment_key": identity["attachment_key"],
            "pdf_sha256": identity["pdf_sha256"],
            "card_sha256": text_hash(card),
            # Relative to the literature root: the pool registry must not embed
            # machine-specific absolute paths, or a moved library looks changed.
            "package_directory": resolved.relative_to(root).as_posix(),
        },
        pdf_size_bytes=identity["pdf_size_bytes"],
        converter_id=converter_id,
        converter_version=converter_version,
    ), ""


def scan_drafts(config: Any, literature_root: Any = None) -> DraftScan:
    """Scan every draft under ``<literature root>/zotero/*/drafts/*``."""

    root = Path(literature_root) if literature_root is not None else resolve_literature_root()
    root = root.expanduser().resolve()
    rejected = _empty_rejections()
    items: list[DraftSource] = []
    pattern = root / "zotero"
    directories: list[Path] = []
    if pattern.is_dir():
        try:
            directories = sorted(path for path in pattern.glob("*/drafts/*") if path.is_dir())
        except OSError:
            directories = []
    for directory in directories:
        item, reason = inspect_draft(
            directory, literature_root=root, group_id=config.zotero.group_id
        )
        if item is None:
            _reject(rejected, reason)
            continue
        items.append(item)
    return DraftScan(items=tuple(items), rejected=rejected, root=root)


__all__ = [
    "DraftScan",
    "DraftSource",
    "DRAFT_FILENAME",
    "REJECT_REASONS",
    "inspect_draft",
    "scan_drafts",
]
