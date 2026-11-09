"""Read-only theme-pool audit plus two explicit maintenance operations.

The registry is the only authority for theme identity. This module never
infers a theme from a directory name: it classifies candidate directories by
whether the registry's ``current`` or ``history`` entries reference them.

``merge`` retires registered themes that share the same evidence set.
``prune`` moves registered-table-orphan candidate roots aside; it never
deletes anything.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from hydrolitagent.cards import theme_pool as pool
from hydrolitagent.cards import themes as core
from hydrolitagent.cards.publication import atomic_text
from hydrolitagent.cards.tasks import PipelineRunLock

EVIDENCE_RE = re.compile(r"EV-[0-9A-Z]{8}")


def _fail(code: str, message: str, **details) -> None:
    raise core.ThemeError(code, message, **details)


def _lock(config):
    path = config.paths.lock_file.with_name(config.paths.lock_file.name + ".themes")
    return PipelineRunLock(path)


def _state(config, code: str = "THEME_AUDIT_NO_REGISTRY"):
    state = pool.load(config)
    if state is None:
        _fail(code, "主题池注册表不存在；先运行 themes-run，不要从目录推断主题")
    return state


def _rel(config, path: Path) -> str:
    return path.relative_to(config.paths.themes_dir).as_posix()


def _referenced_dirs(config, state) -> set[str]:
    referenced = set()
    for entry in state["themes"].values():
        for reference in [entry["current"], *entry["history"]]:
            referenced.add(Path(reference["directory"]).as_posix())
    return referenced


def _version_dirs(theme_root: Path) -> list[Path]:
    versions = theme_root / "versions"
    if not versions.is_dir():
        return []
    return sorted(
        (path for path in versions.iterdir() if path.is_dir() and path.name.startswith("CHANGE-")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _evidence_from_markdown(path: Path) -> tuple[list[str], str]:
    if not path.is_file():
        return [], "none"
    found = sorted(set(EVIDENCE_RE.findall(path.read_text(encoding="utf-8", errors="replace"))))
    return found, "markdown" if found else "none"


def _evidence_from_manifest(directory: Path) -> tuple[list[str], str]:
    manifest = directory / "manifest.json"
    if not manifest.is_file():
        return [], "none"
    try:
        record = _read_json(manifest)
    except (OSError, ValueError):
        return [], "none"
    found = sorted({
        reading["source"]["evidence_id"]
        for reading in record.get("readings", [])
        if isinstance(reading, dict)
        and isinstance(reading.get("source"), dict)
        and isinstance(reading["source"].get("evidence_id"), str)
    })
    return found, "manifest" if found else "none"


def _registered_evidence(config, entry) -> tuple[list[str], str]:
    directory = pool.root_path(config, entry["current"]["directory"])
    found, source = _evidence_from_manifest(directory)
    if found:
        return found, source
    return _evidence_from_markdown(directory / "revised.md")


def _orphan_evidence(theme_root: Path) -> tuple[list[str], str]:
    for directory in _version_dirs(theme_root):
        found, source = _evidence_from_manifest(directory)
        if found:
            return found, source
        plan = directory / "plan.json"
        if plan.is_file():
            try:
                candidate = _read_json(plan).get("candidate", {})
                text = candidate.get("candidate_markdown", "") if isinstance(candidate, dict) else ""
            except (OSError, ValueError):
                text = ""
            found = sorted(set(EVIDENCE_RE.findall(text)))
            if found:
                return found, "plan"
        found, source = _evidence_from_markdown(directory / "initial.md")
        if found:
            return found, source
    return [], "none"


def _duplicate_groups(items: list[tuple[str, list[str]]]) -> list[dict]:
    grouped: dict[tuple[str, ...], list[str]] = {}
    for theme_id, evidence in items:
        if evidence:
            grouped.setdefault(tuple(sorted(evidence)), []).append(theme_id)
    return [
        {"evidence": list(evidence), "themes": sorted(themes)}
        for evidence, themes in sorted(grouped.items())
        if len(themes) > 1
    ]


def audit(config) -> dict:
    """Classify candidate roots without writing anything."""
    state = _state(config)
    referenced = _referenced_dirs(config, state)
    registered = []
    registered_evidence = []
    for theme_id, entry in sorted(state["themes"].items()):
        evidence, source = _registered_evidence(config, entry)
        registered.append({
            "theme_id": theme_id,
            "title": entry["title"],
            "status": entry["status"],
            "evidence": evidence,
            "evidence_source": source,
            "current_directory": entry["current"]["directory"],
        })
        if entry["status"] != pool.RETIRED:
            registered_evidence.append((theme_id, evidence))

    orphan_roots = []
    orphan_evidence = []
    candidates = config.paths.themes_dir / "candidates"
    roots = sorted(candidates.glob("TH-*")) if candidates.is_dir() else []
    for theme_root in roots:
        if not theme_root.is_dir():
            continue
        versions = _version_dirs(theme_root)
        if any(_rel(config, version) in referenced for version in versions):
            continue
        evidence, source = _orphan_evidence(theme_root)
        orphan_roots.append({
            "theme_id": theme_root.name,
            "versions": [version.name for version in versions],
            "evidence": evidence,
            "evidence_source": source,
        })
        orphan_evidence.append((theme_root.name, evidence))

    return {
        "schema_version": 1,
        "ok": True,
        "operation": "themes_audit",
        "status": "OK",
        "registry_generation": state.get("generation"),
        "registered_count": len(registered),
        "active_count": sum(1 for item in registered if item["status"] != pool.RETIRED),
        "retired_count": sum(1 for item in registered if item["status"] == pool.RETIRED),
        "orphan_root_count": len(orphan_roots),
        "referenced_version_count": len(referenced),
        "registered": registered,
        "orphan_roots": orphan_roots,
        "duplicate_groups_registered": _duplicate_groups(registered_evidence),
        "duplicate_groups_orphans": _duplicate_groups(orphan_evidence),
    }


def merge(config, *, canonical: str, retire: list[str], reason: str) -> dict:
    """Retire registered themes that carry the same evidence set as canonical."""
    if not reason or not reason.strip():
        _fail("THEME_MERGE_INVALID", "必须给出合并理由")
    targets = list(dict.fromkeys(retire or []))
    if not targets:
        _fail("THEME_MERGE_INVALID", "至少需要一个待退役主题")
    if canonical in targets:
        _fail("THEME_MERGE_INVALID", "canonical 不能同时出现在待退役列表中")

    with _lock(config):
        base = _state(config, "THEME_MERGE_NO_REGISTRY")
        canonical_entry = base["themes"].get(canonical)
        if canonical_entry is None:
            _fail("THEME_MERGE_UNKNOWN_THEME", "canonical 主题不在注册表中", theme_id=canonical)
        if canonical_entry["status"] == pool.RETIRED:
            _fail("THEME_MERGE_CANONICAL_RETIRED", "canonical 主题已退役", theme_id=canonical)

        canonical_evidence = set(_registered_evidence(config, canonical_entry)[0])
        changed = []
        already = []
        for theme_id in targets:
            entry = base["themes"].get(theme_id)
            if entry is None:
                _fail("THEME_MERGE_UNKNOWN_THEME", "待退役主题不在注册表中", theme_id=theme_id)
            if entry["status"] == pool.RETIRED:
                if canonical in entry.get("successors", []):
                    already.append(theme_id)
                    continue
                _fail("THEME_MERGE_TARGET_RETIRED", "待退役主题已退役到别的主题",
                      theme_id=theme_id, successors=entry.get("successors", []))
            target_evidence = set(_registered_evidence(config, entry)[0])
            if target_evidence != canonical_evidence:
                _fail("THEME_MERGE_EVIDENCE_MISMATCH",
                      "待退役主题与 canonical 的证据集不同；不按目录名猜测",
                      theme_id=theme_id,
                      canonical_evidence=sorted(canonical_evidence),
                      target_evidence=sorted(target_evidence))
            changed.append(theme_id)

        if not changed:
            return {
                "schema_version": 1, "ok": True, "operation": "themes_merge",
                "status": "NO_CHANGE_NEEDED", "canonical": canonical,
                "retired": [], "already_retired": already,
                "generation": base.get("generation"),
            }

        request = {
            "canonical": canonical,
            "retire": changed,
            "reason": reason,
            "generation": base.get("generation"),
        }
        change_id = "CHANGE-" + core._digest({"base": base, "merge": request})[:24]
        change_dir = pool.root_path(config, "changes/" + change_id)
        core._publish(change_dir / "inputs.json",
                      core._json({"base_registry": base, "merge": request}))

        next_state = copy.deepcopy(base)
        for theme_id in changed:
            entry = next_state["themes"][theme_id]
            entry["status"] = pool.RETIRED
            entry["successors"] = sorted(set(entry.get("successors", [])) | {canonical})
        committed = pool.commit(config, base, next_state, change_dir)

    return {
        "schema_version": 1, "ok": True, "operation": "themes_merge",
        "status": "CANDIDATES_MERGED", "canonical": canonical,
        "retired": changed, "already_retired": already,
        "generation": committed.get("generation"),
        "change_id": change_id, "change_path": str(change_dir),
        "index_sha256": committed.get("index_sha256"),
    }


def _is_redirected(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def prune(config, *, apply: bool) -> dict:
    """Move candidate roots that the registry never references; never delete."""
    with _lock(config):
        state = _state(config, "THEME_PRUNE_NO_REGISTRY")
        referenced = _referenced_dirs(config, state)
        candidates = config.paths.themes_dir / "candidates"
        orphans = []
        roots = sorted(candidates.glob("TH-*")) if candidates.is_dir() else []
        for theme_root in roots:
            if not theme_root.is_dir():
                continue
            versions = _version_dirs(theme_root)
            if any(_rel(config, version) in referenced for version in versions):
                continue
            orphans.append(theme_root)

        if not orphans:
            return {
                "schema_version": 1, "ok": True, "operation": "themes_prune",
                "status": "NO_ORPHANS", "apply": apply, "moved": [],
                "registry_generation": state.get("generation"),
            }
        if not apply:
            return {
                "schema_version": 1, "ok": True, "operation": "themes_prune",
                "status": "DRY_RUN", "apply": False,
                "orphans": [path.name for path in orphans],
                "registry_generation": state.get("generation"),
            }

        for theme_root in orphans:
            if _is_redirected(theme_root):
                _fail("THEME_PRUNE_REDIRECTED", "孤儿目录是链接或 junction；拒绝移动",
                      path=str(theme_root))

        change_id = "CHANGE-" + uuid4().hex[:24]
        archive_root = pool.root_path(config, "orphans/" + change_id)
        archive_root.mkdir(parents=True, exist_ok=True)
        moved = []
        try:
            for theme_root in orphans:
                destination = archive_root / theme_root.name
                shutil.move(str(theme_root), str(destination))
                moved.append({
                    "theme_id": theme_root.name,
                    "source": _rel(config, theme_root),
                    "destination": _rel(config, destination),
                })
        except OSError as exc:
            atomic_text(archive_root / "manifest.json", core._json({
                "schema_version": 1, "operation": "themes_prune", "status": "PARTIAL",
                "change_id": change_id, "registry_generation": state.get("generation"),
                "moved": moved, "error": type(exc).__name__,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }))
            _fail("THEME_PRUNE_PARTIAL", "归档中断；已移动项记录在 manifest.json",
                  change_id=change_id, moved=[item["theme_id"] for item in moved])

        atomic_text(archive_root / "manifest.json", core._json({
            "schema_version": 1, "operation": "themes_prune", "status": "MOVED",
            "change_id": change_id, "registry_generation": state.get("generation"),
            "moved": moved, "created_at": datetime.now(timezone.utc).isoformat(),
        }))
    return {
        "schema_version": 1, "ok": True, "operation": "themes_prune",
        "status": "ORPHANS_ARCHIVED", "apply": True, "change_id": change_id,
        "archive_path": str(archive_root), "moved": moved,
        "registry_generation": state.get("generation"),
    }
