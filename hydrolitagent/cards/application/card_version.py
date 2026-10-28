"""Immutable card versions: one ``card_id`` per paper, one directory per result.

A draft is a working artefact: it is generated, re-validated and eventually
replaced. A version is an asset: it is written once, never rewritten, and the
theme step reads it by ``card_id@version_id``.

The rules are deliberately narrow:

* **only a passed card becomes a version** -- the newest validation record must
  say ``PASS`` and must still describe the draft on disk, so a card cannot be
  promoted by editing it after it was validated;
* **a partial reading is not a version either** -- a version is the asset the
  theme step consumes, and that step refuses a partial reading, so admitting one
  here would only move the failure downstream;
* **the same result is one version** -- identity is the pair (draft fingerprint,
  input fingerprint); saving it twice returns the existing version instead of
  appending a duplicate;
* **a new result is a new number** -- ``v1``, ``v2`` … are human-readable names;
  the content fingerprint lives in ``manifest.json`` and is what idempotency
  compares;
* **a failed write moves nothing** -- files land in a staging directory that is
  renamed into place atomically, and ``current.json`` is written last. A run that
  fails half-way leaves no version directory and keeps the previous pointer.

Nothing here re-validates a card, rewrites a draft or calls a model.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hydrolitagent.cards.application.draft_sources import newest_validation
from hydrolitagent.cards.card_validation import fingerprint, read_strict_json
from hydrolitagent.cards.domain.errors import CardGenerationError
from hydrolitagent.cards.publication import atomic_text, text_hash

CARD_ID_PREFIX = "EV-"
CARD_VERSIONS_DIRNAME = "card-versions"
VERSION_PREFIX = "v"
VERSIONS_SUBDIRNAME = "versions"
CARD_FILENAME = "card.md"
MACHINE_FIELDS_FILENAME = "machine_fields.json"
SOURCE_FILENAME = "source.json"
VALIDATION_FILENAME = "validation.json"
MANIFEST_FILENAME = "manifest.json"
CURRENT_FILENAME = "current.json"
MANIFEST_SCHEMA_VERSION = 1
# A rename only loses a race with another writer; a few retries are plenty for a
# single-user CLI and keep the numbering dense.
MAX_VERSION_ATTEMPTS = 3
STAGING_PREFIX = ".tmp-"

_KEY = re.compile(r"[A-Z0-9]{8}")
_VERSION_NAME = re.compile(r"v([1-9][0-9]*)")
_VERSION_ID = re.compile(r"v[1-9][0-9]*")
_CARD_ID = re.compile(r"EV-[A-Z0-9]{8}")


def _fail(code: str, message: str, **diagnostic: Any) -> None:
    raise CardGenerationError(code, message, diagnostic=diagnostic or None)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _read_object(path: Path, what: str) -> dict[str, Any]:
    try:
        value = read_strict_json(path)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise CardGenerationError(
            "CARD_VERSION_INPUT_INVALID",
            f"{what}读取失败：{type(exc).__name__}",
            diagnostic={"path": str(path)},
        ) from exc
    if not isinstance(value, dict):
        _fail("CARD_VERSION_INPUT_INVALID", f"{what}不是 JSON 对象", path=str(path))
    return value


def card_id_for(draft: Any) -> str:
    """The stable id of the card this draft belongs to: ``EV-<parent item key>``."""

    source = draft.get("source") if isinstance(draft, Mapping) else None
    parent = source.get("parent_key") if isinstance(source, Mapping) else None
    if not isinstance(parent, str) or not _KEY.fullmatch(parent):
        _fail("CARD_VERSION_INPUT_INVALID", "草稿缺少可用的父条目 Key，无法分配 card_id")
    return CARD_ID_PREFIX + parent


def content_sha256(draft_sha256: str, input_sha256: str) -> str:
    """Version identity: the card's content together with the input it rests on."""

    return hashlib.sha256(f"{draft_sha256}|{input_sha256}".encode("utf-8")).hexdigest()


def _card_root(root: Path, card_id: str) -> Path:
    return Path(root) / CARD_VERSIONS_DIRNAME / card_id


def _existing_versions(versions_dir: Path) -> list[tuple[int, Path]]:
    if not versions_dir.is_dir():
        return []
    found: list[tuple[int, Path]] = []
    for entry in versions_dir.iterdir():
        match = _VERSION_NAME.fullmatch(entry.name)
        if match and entry.is_dir():
            found.append((int(match.group(1)), entry))
    return sorted(found)


def _validation_for(draft_path: Path, validation_path: Path | None) -> dict[str, Any]:
    if validation_path is not None:
        return _read_object(Path(validation_path), "校验记录")
    record, reason = newest_validation(draft_path.parent)
    if record is None:
        _fail(
            "CARD_VERSION_REQUIRES_PASS",
            "找不到这份草稿的校验记录；先运行 cards evidence-validate",
            reason=reason,
        )
    return record


def _require_passing(record: Mapping[str, Any], draft: Mapping[str, Any]) -> str:
    """Return the draft fingerprint the record describes, or refuse to promote."""

    if record.get("status") != "PASS" or record.get("ok") is not True:
        _fail("CARD_VERSION_REQUIRES_PASS", "只有校验通过（PASS）的主体卡才能保存为版本")
    if record.get("reading_verified") is not True:
        _fail(
            "CARD_VERSION_REQUIRES_VERIFIED_READING",
            "阅读未经验证（PARTIAL）的卡片不能保存为版本；先让整篇阅读通过校验",
        )
    try:
        current = fingerprint(draft)
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise CardGenerationError(
            "CARD_VERSION_INPUT_INVALID", "草稿无法规范化，不能计算版本指纹"
        ) from exc
    if record.get("draft_id") != draft.get("draft_id") or record.get("draft_sha256") != current:
        _fail(
            "CARD_VERSION_VALIDATION_STALE",
            "校验记录描述的草稿与当前草稿不一致；请先重新校验",
            validated_draft_id=record.get("draft_id"),
            current_draft_id=draft.get("draft_id"),
        )
    return current


def _generation_record(draft: Mapping[str, Any]) -> dict[str, Any]:
    """Enough provenance to answer "who produced this, with what"."""

    generation: dict[str, Any] = {}
    audit = draft.get("process_audit")
    if isinstance(audit, Mapping):
        for key in ("protocol_version", "runner_id", "model", "model_invoked", "duration_seconds"):
            if audit.get(key) is not None:
                generation[key] = audit[key]
    provenance = draft.get("provenance")
    if isinstance(provenance, Mapping):
        for key in ("prompt_version", "prompt_sha256", "converter_id", "converter_version"):
            if provenance.get(key) is not None:
                generation[key] = provenance[key]
    if isinstance(draft.get("usage"), Mapping):
        generation["usage"] = draft["usage"]
    return generation


def _write_version_files(
    directory: Path, files: Mapping[str, str], manifest: Mapping[str, Any]
) -> None:
    """Write every file of one version into ``directory`` (never the live one)."""

    for name, content in files.items():
        (directory / name).write_text(content, encoding="utf-8", newline="\n")
    (directory / MANIFEST_FILENAME).write_text(
        _json_text(manifest), encoding="utf-8", newline="\n"
    )


def _version_payload(draft: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, str]:
    body = draft.get("card_body_markdown")
    if not isinstance(body, str) or not body.strip():
        _fail("CARD_VERSION_INPUT_INVALID", "草稿没有可保存的正文（card_body_markdown）")
    machine_fields = draft.get("machine_fields")
    if not isinstance(machine_fields, Mapping):
        _fail("CARD_VERSION_INPUT_INVALID", "草稿缺少机器字段（machine_fields）")
    return {
        # The draft preview carries a "pending validation" banner; a version is
        # past that gate, so it stores the body the model wrote, not the preview.
        CARD_FILENAME: body if body.endswith("\n") else body + "\n",
        MACHINE_FIELDS_FILENAME: _json_text(machine_fields),
        SOURCE_FILENAME: _json_text(draft.get("source")),
        VALIDATION_FILENAME: _json_text(record),
    }


def _build_manifest(
    *,
    card_id: str,
    version_id: str,
    content: str,
    draft: Mapping[str, Any],
    record: Mapping[str, Any],
    draft_sha256: str,
    files: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "card_id": card_id,
        "version_id": version_id,
        "version_number": int(version_id[len(VERSION_PREFIX):]),
        "content_sha256": content,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "draft_id": draft.get("draft_id"),
        "draft_sha256": draft_sha256,
        "input_sha256": record.get("input_sha256"),
        "validation_id": record.get("validation_id"),
        "validation_policy_version": record.get("policy_version"),
        "validator_sha256": record.get("validator_sha256"),
        "reading_status": record.get("reading_status"),
        "theme_eligible": record.get("eligible_for_theme_generation") is True,
        "source": draft.get("source"),
        "generation": _generation_record(draft),
        "files": {name: text_hash(content) for name, content in files.items()},
    }


def _result(
    *, card_id: str, version_id: str, directory: Path, created: bool, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "card_version_save",
        "ok": True,
        "created": created,
        "card_id": card_id,
        "version_id": version_id,
        "version_number": manifest.get("version_number"),
        "content_sha256": manifest.get("content_sha256"),
        "version_directory": str(directory),
        "manifest": dict(manifest),
    }


def save_card_version(
    root: Path,
    draft_path: Path,
    validation_path: Path | None = None,
) -> dict[str, Any]:
    """Save one immutable version of a passed card; idempotent on identical input."""

    draft_path = Path(draft_path)
    draft = _read_object(draft_path, "草稿")
    card_id = card_id_for(draft)
    record = _validation_for(draft_path, validation_path)
    draft_sha256 = _require_passing(record, draft)

    input_sha256 = record.get("input_sha256")
    if not isinstance(input_sha256, str) or not input_sha256:
        _fail("CARD_VERSION_INPUT_INVALID", "校验记录缺少输入指纹，无法判定版本")
    content = content_sha256(draft_sha256, input_sha256)

    card_root = _card_root(root, card_id)
    versions_dir = card_root / VERSIONS_SUBDIRNAME
    existing = _existing_versions(versions_dir)
    for number, directory in existing:
        try:
            manifest = read_strict_json(directory / MANIFEST_FILENAME)
        except (OSError, ValueError, TypeError, RecursionError):
            continue
        if isinstance(manifest, Mapping) and manifest.get("content_sha256") == content:
            return _result(
                card_id=card_id,
                version_id=directory.name,
                directory=directory,
                created=False,
                manifest=manifest,
            )

    files = _version_payload(draft, record)
    number = existing[-1][0] if existing else 0
    for _ in range(MAX_VERSION_ATTEMPTS):
        number += 1
        version_id = f"{VERSION_PREFIX}{number}"
        target = versions_dir / version_id
        if target.exists():
            continue
        versions_dir.mkdir(parents=True, exist_ok=True)
        manifest = _build_manifest(
            card_id=card_id,
            version_id=version_id,
            content=content,
            draft=draft,
            record=record,
            draft_sha256=draft_sha256,
            files=files,
        )
        staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=versions_dir))
        try:
            _write_version_files(staging, files, manifest)
            os.rename(staging, target)
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise CardGenerationError(
                "CARD_VERSION_IO_ERROR",
                f"版本写入失败：{type(exc).__name__}；当前版本指针未改动",
                diagnostic={"card_id": card_id, "attempted_version": version_id},
            ) from exc
        atomic_text(
            card_root / CURRENT_FILENAME,
            _json_text({
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "card_id": card_id,
                "version_id": version_id,
                "content_sha256": content,
                "updated_at": manifest["created_at"],
            }),
        )
        return _result(
            card_id=card_id, version_id=version_id, directory=target, created=True, manifest=manifest
        )
    _fail(
        "CARD_VERSION_IO_ERROR",
        "版本号竞争重试次数用尽；当前版本指针未改动",
        card_id=card_id,
    )


def load_card_version(
    root: Path, card_id: str, version_id: str | None = None
) -> dict[str, Any]:
    """Read one version by ``card_id@version_id``; without one, read the current."""

    if not isinstance(card_id, str) or not _CARD_ID.fullmatch(card_id):
        _fail("CARD_VERSION_NOT_FOUND", "card_id 形如 EV-ABCD1234", card_id=card_id)
    card_root = _card_root(root, card_id)
    if version_id is None:
        current_path = card_root / CURRENT_FILENAME
        try:
            current = read_strict_json(current_path)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            raise CardGenerationError(
                "CARD_VERSION_NOT_FOUND",
                "这张卡还没有任何已保存的版本",
                diagnostic={"card_id": card_id},
            ) from exc
        version_id = current.get("version_id") if isinstance(current, Mapping) else None
    if not isinstance(version_id, str) or not _VERSION_ID.fullmatch(version_id):
        _fail("CARD_VERSION_NOT_FOUND", "version_id 形如 v1、v2", version_id=version_id)
    directory = card_root / VERSIONS_SUBDIRNAME / version_id
    if not directory.is_dir():
        _fail(
            "CARD_VERSION_NOT_FOUND",
            "找不到这个版本",
            card_id=card_id,
            version_id=version_id,
        )
    manifest = _read_object(directory / MANIFEST_FILENAME, "版本清单")
    try:
        card = (directory / CARD_FILENAME).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CardGenerationError(
            "CARD_VERSION_INPUT_INVALID",
            "版本正文无法读取",
            diagnostic={"version_directory": str(directory)},
        ) from exc
    return {
        "schema_version": 1,
        "operation": "card_version_show",
        "ok": True,
        "card_id": card_id,
        "version_id": version_id,
        "version_number": manifest.get("version_number"),
        "card": card,
        "machine_fields": _read_object(directory / MACHINE_FIELDS_FILENAME, "版本机器字段"),
        "source": _read_object(directory / SOURCE_FILENAME, "版本来自身份"),
        "manifest": manifest,
        "paths": {
            "version_directory": str(directory),
            "card": str(directory / CARD_FILENAME),
            "machine_fields": str(directory / MACHINE_FIELDS_FILENAME),
            "manifest": str(directory / MANIFEST_FILENAME),
            "validation": str(directory / VALIDATION_FILENAME),
        },
    }


__all__ = [
    "CARD_VERSIONS_DIRNAME",
    "card_id_for",
    "content_sha256",
    "load_card_version",
    "save_card_version",
]
