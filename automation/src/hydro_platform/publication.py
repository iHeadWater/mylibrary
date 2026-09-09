"""Recover interrupted multi-file publication from a local, durable prepared record."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from hydro_platform.evidence_packages import EvidencePackageError, PLACEHOLDER_CARD, load_evidence_manifest


def text_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def identity(manifest):
    return {k: manifest.get(k) for k in
            ("group_id", "parent_key", "attachment_key", "pdf_sha256", "source_task_id", "evidence_id")}


def publication_path(lock_path, manifest):
    # Keys come from validated manifests, never from arbitrary file paths in the record.
    return Path(lock_path).parent / "pending-publications" / f"{manifest['group_id']}-{manifest['parent_key']}.json"


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def prepare_publication(lock_path, original_manifest, manifest, card, audit):
    path = publication_path(lock_path, manifest)
    if path.exists():
        raise EvidencePackageError("PUBLICATION_PENDING", "已有待保存记录，应先对账恢复，不能重跑模型覆盖记录")
    payload = {"schema_version": 1, "original_manifest": original_manifest,
               "manifest": manifest, "card": card, "audit": audit}
    atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return path


def validate_saved_package(package_path):
    package_path = Path(package_path)
    manifest = load_evidence_manifest(package_path / "manifest.json")
    card = (package_path / "card.md").read_text(encoding="utf-8")
    if manifest["card_status"] == "PLACEHOLDER":
        if card != PLACEHOLDER_CARD or (package_path / "quality-audit.json").exists():
            raise EvidencePackageError("EVIDENCE_PACKAGE_INCONSISTENT", "占位状态与卡片或审计文件不一致；保留现有文件")
        return None
    generation = manifest["generation"]
    if text_hash(card) != generation["card_sha256"]:
        raise EvidencePackageError("EVIDENCE_CARD_CHANGED", "卡片与清单指纹不一致；保留现有文件，不自动覆盖")
    if "quality_audit_sha256" in generation:
        audit = (package_path / "quality-audit.json").read_text(encoding="utf-8")
        if (text_hash(audit) != generation["quality_audit_sha256"]
            or json.loads(audit).get("quality_report", {}).get("status") != generation["quality_status"]):
            raise EvidencePackageError("EVIDENCE_AUDIT_CHANGED", "生成审计与清单不一致；保留文件")
    return manifest


def recover_publication(package_path, lock_path, current_manifest):
    """Caller holds the registry lock. Do not overwrite user edits or publish unknown inputs."""
    package_path = Path(package_path)
    record_path = publication_path(lock_path, current_manifest)
    if not record_path.exists():
        return False
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("schema_version") != 1:
            raise ValueError("bad record")
        manifest, original = record["manifest"], record["original_manifest"]
        card, audit = record["card"], record["audit"]
        if (identity(manifest) != identity(current_manifest) or identity(original) != identity(manifest)
            or current_manifest not in (original, manifest) or original["card_status"] != "PLACEHOLDER"
            or manifest["card_status"] != "ROUGH" or card == PLACEHOLDER_CARD
            or text_hash(card) != manifest["generation"]["card_sha256"]
            or text_hash(audit) != manifest["generation"]["quality_audit_sha256"]
            or json.loads(audit).get("quality_report", {}).get("status") != manifest["generation"]["quality_status"]):
            raise ValueError("record identity/content mismatch")
        current_card = (package_path / "card.md").read_text(encoding="utf-8")
        audit_path = package_path / "quality-audit.json"
        if current_card not in (PLACEHOLDER_CARD, card):
            raise ValueError("user card changes")
        if audit_path.exists() and audit_path.read_text(encoding="utf-8") != audit:
            raise ValueError("user audit changes")
        # Validate the saved manifest before changing any shared file.
        fd, temporary = tempfile.mkstemp(prefix=".recovery-manifest-", suffix=".tmp", dir=package_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False)
            load_evidence_manifest(Path(temporary))
        finally:
            Path(temporary).unlink(missing_ok=True)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise EvidencePackageError("PUBLICATION_RECOVERY_CONFLICT", "待保存记录或现有文件有冲突；保留全部内容，未重跑模型") from exc
    # Record stays durable until all three files are committed; a second crash is recoverable.
    if not audit_path.exists():
        atomic_text(audit_path, audit)
    if current_card != card:
        atomic_text(package_path / "card.md", card)
    if current_manifest != manifest:
        atomic_text(package_path / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    validate_saved_package(package_path)
    record_path.unlink()
    return True
