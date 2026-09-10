"""Portable, idempotent contribution records; no models and no guessed identities."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from hydro_platform.evidence_packages import load_evidence_manifest
from hydro_platform.publication import atomic_text, text_hash, validate_saved_package
from hydro_platform.snapshot import fetch_snapshot
from hydro_platform.tasks import PipelineRunLock


class ActivityError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def canonical(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def safe_path(root, *parts):
    root = Path(root)
    path = root.joinpath(*parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ActivityError("REPORT_PATH_OUTSIDE_ROOT", "共享记录路径超出配置目录")
    current = path
    while current != root:
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ActivityError("REPORT_PATH_REDIRECTED", "共享记录路径包含重定向，不写入")
        current = current.parent
    return path


def read_record(path):
    if not path.exists():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        record = wrapper["record"]
        if (wrapper.get("schema_version") != 1 or not isinstance(record, dict)
            or text_hash(canonical(record)) != wrapper.get("sha256")):
            raise ValueError("record hash")
        return record
    except (ValueError, KeyError, TypeError) as exc:
        raise ActivityError("ACTIVITY_RECORD_CONFLICT", "共享记录损坏或被修改；保留现场，不覆盖") from exc


def write_record(path, record):
    atomic_text(path, canonical({"schema_version": 1, "record": record, "sha256": text_hash(canonical(record))}))


def now_text(now=None):
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def clean(value):
    return " ".join(value.split()) if isinstance(value, str) else None


def member_mapping(config):
    path = safe_path(config.paths.members_dir, "members.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or not isinstance(data.get("members"), list):
            raise ValueError("members")
        result, ids = {}, set()
        for member in data["members"]:
            uid, mid = member["zotero_user_id"], member["member_id"]
            name = clean(member["display_name"])
            if (type(uid) is not int or uid < 1 or uid in result or not isinstance(mid, str)
                or not re.fullmatch(r"(?:STU|TCH)-[A-Z0-9-]+", mid) or mid in ids or not name):
                raise ValueError("member identity")
            ids.add(mid)
            result[uid] = {"member_id": mid, "display_name": name}
        return result
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ActivityError("MEMBERS_INVALID", "成员映射无效或重复；不能猜测个人归属") from exc


def actor_from(item, mapping):
    actor = item.get("created_by_user")
    if not isinstance(actor, dict) or type(actor.get("id")) is not int or actor["id"] < 1:
        return {"kind": "UNKNOWN", "reason": "ZOTERO_CREATOR_UNAVAILABLE"}
    uid = actor["id"]
    return {"kind": "ZOTERO_USER", "zotero_user_id": uid, "username": clean(actor.get("username")),
            "source": "meta.createdByUser", **mapping.get(uid, {})}


def saved_cards(config):
    cards, issues, seen = {}, [], set()
    root = config.paths.evidence_packs_dir
    for path in sorted(root.glob("*/manifest.json")):
        key = None
        try:
            path = safe_path(root, path.parent.name, "manifest.json")
            manifest = load_evidence_manifest(path)
            if manifest["group_id"] != config.zotero.group_id:
                continue
            key = manifest["parent_key"]
            if key in seen:
                raise ActivityError("EVIDENCE_PACKAGE_DUPLICATE", "父条目有多个证据包")
            seen.add(key)
            if manifest["card_status"] != "ROUGH":
                continue
            safe_path(root, path.parent.name, "card.md")
            complete = validate_saved_package(path.parent)
            generation = complete["generation"]
            cards[key] = {"title": clean(manifest["title"]), "evidence_id": manifest["evidence_id"],
                "pdf_sha256": manifest["pdf_sha256"], "attachment_key": manifest["attachment_key"],
                "card_sha256": generation["card_sha256"],
                "generation_mode": "DRAFT_RECOVERED" if generation.get("workflow_protocol_version") ==
                    "rough-card-draft-recovery-v1" else "GENERATED",
                "source_occurred_at": clean(generation.get("generated_at")),
                "package_directory": path.parent.name}
        except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
            if key:
                cards.pop(key, None)
            issues.append({"parent_key": key, "reason_code": getattr(exc, "code", "EVIDENCE_RECORD_UNREADABLE")})
    return cards, issues


def _identity(kind, group_id, key, fingerprint=None):
    return "ACT-" + text_hash(canonical([kind, group_id, key, fingerprint]))


def load_ledger(config):
    path = safe_path(config.paths.activity_dir, "ledger.json")
    ledger = read_record(path)
    if ledger is not None:
        try:
            if ledger["group_id"] != config.zotero.group_id:
                raise ActivityError("ACTIVITY_GROUP_MISMATCH", "事件账本属于其他群组，不能覆盖")
            if (ledger["schema_version"] != 1 or not isinstance(ledger["events"], dict)
                or any(not isinstance(ledger["baseline"][name], list) for name in ("parents", "pdf_attachments", "cards"))):
                raise ValueError("ledger")
            for event_id, event in ledger["events"].items():
                if (event.get("group_id") != ledger["group_id"]
                    or event["type"] not in {"PAPER_ADDED", "PDF_ADDED", "CARD_COMPLETED", "TASK_BLOCKED"}
                    or event_id != _identity(event["type"], ledger["group_id"], event["subject_key"], event.get("fingerprint"))):
                    raise ValueError("event identity")
        except (KeyError, TypeError, ValueError) as exc:
            raise ActivityError("ACTIVITY_RECORD_CONFLICT", "事件账本结构不一致；未重建或覆盖") from exc
    return path, ledger


def sync_activity(config, *, snapshot=None, run_report=None, now=None):
    """First observation is a baseline. All later events survive runtime loss."""
    observed = now_text(now)
    path = safe_path(config.paths.activity_dir, "ledger.json")
    lock = config.paths.lock_file.with_name(config.paths.lock_file.name + ".activity")
    with PipelineRunLock(lock):
        _, ledger = load_ledger(config)
        original_hash = text_hash(canonical(ledger)) if ledger is not None else None
        source = snapshot if snapshot is not None else fetch_snapshot(config.zotero, page_size=config.scan.page_size)
        if source["group_id"] != config.zotero.group_id:
            raise ActivityError("ACTIVITY_GROUP_MISMATCH", "扫描内容不属于目标群组")
        mapping = member_mapping(config)
        cards, issues = saved_cards(config)
        initialized = ledger is None
        if initialized:
            # Even broken existing packs are baseline history, not today's contribution.
            baseline_cards = sorted(set(cards) | {row["parent_key"] for row in issues if row["parent_key"]})
            ledger = {"schema_version": 1, "group_id": config.zotero.group_id, "created_at": observed,
                "baseline": {"parents": sorted(source["parents"]), "pdf_attachments": sorted(source["pdf_attachments"]),
                             "cards": baseline_cards}, "events": {}}
        before = len(ledger["events"])
        def add(kind, key, parent_key, title, actor, *, fingerprint=None, source_time=None, details=None):
            event_id = _identity(kind, config.zotero.group_id, key, fingerprint)
            if event_id not in ledger["events"]:
                ledger["events"][event_id] = {"event_id": event_id, "type": kind, "group_id": config.zotero.group_id,
                    "subject_key": key, "parent_key": parent_key, "title": clean(title), "actor": actor,
                    "observed_at": observed, "source_occurred_at": clean(source_time),
                    "fingerprint": fingerprint, "details": details or {}}
        for key, item in sorted(source["parents"].items()):
            if key not in ledger["baseline"]["parents"]:
                add("PAPER_ADDED", key, key, item.get("title"), actor_from(item, mapping), source_time=item.get("date_added"))
        for key, pdf in sorted(source["pdf_attachments"].items()):
            parent = pdf.get("parent_key")
            if key not in ledger["baseline"]["pdf_attachments"] and parent in source["parents"]:
                add("PDF_ADDED", key, parent, source["parents"][parent].get("title"), actor_from(pdf, mapping),
                    source_time=pdf.get("date_added"), details={"attachment_key": key})
        for key, card in sorted(cards.items()):
            if key not in ledger["baseline"]["cards"]:
                # Report availability, not a claim that a model was invoked today.
                add("CARD_COMPLETED", key, key, card["title"],
                    {"kind": "SYSTEM", "member_id": config.activity_reporting.system_actor_id},
                    fingerprint=card["card_sha256"], source_time=card["source_occurred_at"],
                    details={k: card[k] for k in ("evidence_id", "attachment_key", "pdf_sha256", "generation_mode", "package_directory")})
        if run_report is not None:
            if run_report.get("group_id") != config.zotero.group_id:
                raise ActivityError("ACTIVITY_GROUP_MISMATCH", "运行报告不属于目标群组")
            for item in run_report.get("items", []):
                key, state = item.get("parent_key"), item.get("status")
                if not isinstance(key, str) or state not in {"WAITING", "BLOCKED", "FAILED"}:
                    continue
                reason = item.get("reason_code") or item.get("error", {}).get("code")
                reason = reason if isinstance(reason, str) and re.fullmatch(r"[A-Z0-9_]{1,100}", reason) else "UNKNOWN"
                add("TASK_BLOCKED", key, key, item.get("title"),
                    {"kind": "SYSTEM", "member_id": config.activity_reporting.system_actor_id},
                    fingerprint=text_hash(canonical([state, reason])), details={"state": state, "reason_code": reason})
        added = len(ledger["events"]) - before
        if initialized or added:
            current = read_record(path)
            current_hash = text_hash(canonical(current)) if current is not None else None
            if current_hash != original_hash:
                raise ActivityError("ACTIVITY_RECORD_CONFLICT", "扫描期间账本发生变化，未覆盖")
            write_record(path, ledger)
        return {"schema_version": 1, "ok": not issues, "operation": "activity_sync",
                "status": "BASELINE_CREATED" if initialized else "UPDATED" if added else "UNCHANGED",
                "group_id": config.zotero.group_id, "event_count": len(ledger["events"]), "added_event_count": added,
                "baseline_parent_count": len(ledger["baseline"]["parents"]), "issues": issues,
                "ledger_path": str(path), "model_call_count": 0, "zotero_modified": False, "git_modified": False,
                "note": "统计首次观测到的关键行为；原始发生时间单独保留。未知新增者不归给论文作者或当前登录者。"}
