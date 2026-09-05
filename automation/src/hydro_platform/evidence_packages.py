from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hydro_platform.config import TaskConfig
from hydro_platform.tasks import RuntimeLock, build_task_id, load_task_registry


ELIGIBLE_STATE = "READY_FOR_EXTRACTION"
PLACEHOLDER_CARD = "# 待生成证据卡\n\n状态：PLACEHOLDER\n"
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9]+$")
_HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_TASK_ID_PATTERN = re.compile(r"^TASK-[0-9a-f]{64}$")


class EvidencePackageError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _timestamp(value: datetime | None = None) -> str:
    moment = value or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_key(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not _KEY_PATTERN.fullmatch(value):
        raise EvidencePackageError(
            "EVIDENCE_TASK_INVALID",
            f"{name} 必须是只包含字母和数字的 Zotero Key",
        )
    return value


def _slugify(title: Any, *, max_length: int = 60) -> str:
    text = unicodedata.normalize("NFKC", title if isinstance(title, str) else "")
    pieces: list[str] = []
    separator_pending = False
    for character in text.strip().lower():
        if character.isalnum():
            if separator_pending and pieces:
                pieces.append("-")
            pieces.append(character)
            separator_pending = False
        else:
            separator_pending = True
    slug = "".join(pieces).strip("-")
    if not slug:
        return "untitled"
    return slug[:max_length].rstrip("-") or "untitled"


def validate_evidence_task(task: Any, group_id: int) -> dict[str, Any]:
    if not isinstance(task, dict):
        raise EvidencePackageError("EVIDENCE_TASK_INVALID", "任务记录必须是 JSON 对象")
    if task.get("group_id") != group_id:
        raise EvidencePackageError("EVIDENCE_TASK_INVALID", "任务群组与目标群组不一致")

    parent_key = _safe_key(task.get("parent_key"), name="parent_key")
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not _TASK_ID_PATTERN.fullmatch(task_id):
        raise EvidencePackageError("EVIDENCE_TASK_INVALID", f"任务 {parent_key} 缺少有效 task_id")

    input_data = task.get("input")
    if not isinstance(input_data, dict):
        raise EvidencePackageError("EVIDENCE_TASK_INVALID", f"任务 {parent_key} 缺少输入指纹")
    attachment_key = _safe_key(input_data.get("attachment_key"), name="attachment_key")
    pdf_sha256 = input_data.get("pdf_sha256")
    if not isinstance(pdf_sha256, str) or not _HASH_PATTERN.fullmatch(pdf_sha256):
        raise EvidencePackageError(
            "EVIDENCE_TASK_INVALID",
            f"任务 {parent_key} 缺少有效 PDF SHA-256",
        )
    normalized_hash = pdf_sha256.lower()
    expected_task_id = build_task_id(
        group_id,
        parent_key,
        attachment_key,
        normalized_hash,
    )
    if task_id != expected_task_id:
        raise EvidencePackageError(
            "EVIDENCE_TASK_INVALID",
            f"任务 {parent_key} 的 task_id 与输入指纹不一致",
        )

    title = task.get("title")
    normalized_title = title.strip() if isinstance(title, str) and title.strip() else "Untitled"
    return {
        "task_id": task_id,
        "group_id": group_id,
        "parent_key": parent_key,
        "attachment_key": attachment_key,
        "pdf_sha256": normalized_hash,
        "title": normalized_title,
    }


def _manifest(task: dict[str, Any], at: str) -> dict[str, Any]:
    parent_key = task["parent_key"]
    return {
        "schema_version": 1,
        "evidence_id": f"EV-{parent_key}",
        "group_id": task["group_id"],
        "parent_key": parent_key,
        "attachment_key": task["attachment_key"],
        "pdf_sha256": task["pdf_sha256"],
        "source_task_id": task["task_id"],
        "title": task["title"],
        "card_status": "PLACEHOLDER",
        "created_at": at,
        "updated_at": at,
    }


def load_evidence_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidencePackageError(
            "EVIDENCE_MANIFEST_INVALID",
            f"无法读取证据包清单：{path}",
        ) from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise EvidencePackageError(
            "EVIDENCE_MANIFEST_INVALID",
            f"证据包清单结构或版本无效：{path}",
        )
    required_strings = (
        "evidence_id",
        "parent_key",
        "attachment_key",
        "pdf_sha256",
        "source_task_id",
        "title",
        "card_status",
        "created_at",
        "updated_at",
    )
    if any(not isinstance(data.get(name), str) or not data[name] for name in required_strings):
        raise EvidencePackageError(
            "EVIDENCE_MANIFEST_INVALID",
            f"证据包清单缺少必要字段：{path}",
        )
    if (
        isinstance(data.get("group_id"), bool)
        or not isinstance(data.get("group_id"), int)
        or data["group_id"] <= 0
        or not _KEY_PATTERN.fullmatch(data["parent_key"])
        or not _KEY_PATTERN.fullmatch(data["attachment_key"])
        or not _HASH_PATTERN.fullmatch(data["pdf_sha256"])
        or not _TASK_ID_PATTERN.fullmatch(data["source_task_id"])
        or data["card_status"] != "PLACEHOLDER"
    ):
        raise EvidencePackageError(
            "EVIDENCE_MANIFEST_INVALID",
            f"证据包清单字段格式无效：{path}",
        )
    return data


def find_evidence_package(root: Path, parent_key: str) -> Path | None:
    prefix = f"EV-{parent_key}-".casefold()
    matches = [entry for entry in root.iterdir() if entry.name.casefold().startswith(prefix)]
    if len(matches) > 1:
        raise EvidencePackageError(
            "EVIDENCE_PACKAGE_DUPLICATE",
            f"父条目 {parent_key} 对应多个证据包目录，拒绝自动选择",
        )
    if not matches:
        return None
    package_path = matches[0]
    if not package_path.is_dir():
        raise EvidencePackageError(
            "EVIDENCE_PACKAGE_INVALID",
            f"证据包路径不是目录：{package_path}",
        )
    return package_path


def _existing_result(package_path: Path, task: dict[str, Any]) -> dict[str, Any]:
    manifest_path = package_path / "manifest.json"
    card_path = package_path / "card.md"
    if not manifest_path.is_file() or not card_path.is_file():
        raise EvidencePackageError(
            "EVIDENCE_PACKAGE_INCOMPLETE",
            f"证据包缺少 manifest.json 或 card.md：{package_path}",
        )

    manifest = load_evidence_manifest(manifest_path)
    expected = {
        "evidence_id": f"EV-{task['parent_key']}",
        "group_id": task["group_id"],
        "parent_key": task["parent_key"],
        "attachment_key": task["attachment_key"],
        "pdf_sha256": task["pdf_sha256"],
        "source_task_id": task["task_id"],
    }
    mismatched = [name for name, value in expected.items() if manifest.get(name) != value]
    if mismatched:
        raise EvidencePackageError(
            "EVIDENCE_INPUT_MISMATCH",
            f"证据包与当前任务输入不一致（{', '.join(mismatched)}）：{package_path}",
        )

    try:
        card_content = card_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvidencePackageError(
            "EVIDENCE_CARD_INVALID",
            f"无法读取证据卡：{card_path}",
        ) from exc
    return {
        "evidence_id": expected["evidence_id"],
        "parent_key": task["parent_key"],
        "action": "UNCHANGED",
        "card_state": "PLACEHOLDER" if card_content == PLACEHOLDER_CARD else "PRESERVED",
        "path": str(package_path.resolve()),
    }


def _create_package(root: Path, task: dict[str, Any], at: str) -> dict[str, Any]:
    package_name = f"EV-{task['parent_key']}-{_slugify(task['title'])}"
    package_path = root / package_name
    temporary_path = Path(tempfile.mkdtemp(prefix=".tmp-package-", dir=root))
    try:
        (temporary_path / "manifest.json").write_text(
            json.dumps(_manifest(task, at), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (temporary_path / "card.md").write_text(PLACEHOLDER_CARD, encoding="utf-8")
        os.replace(temporary_path, package_path)
    except OSError as exc:
        raise EvidencePackageError(
            "EVIDENCE_PACKAGE_WRITE_FAILED",
            f"无法原子创建证据包：{package_path}",
        ) from exc
    finally:
        if temporary_path.exists():
            shutil.rmtree(temporary_path, ignore_errors=True)

    return {
        "evidence_id": f"EV-{task['parent_key']}",
        "parent_key": task["parent_key"],
        "action": "CREATED",
        "card_state": "PLACEHOLDER",
        "path": str(package_path.resolve()),
    }


def sync_evidence_packages(
    group_id: int,
    task_config: TaskConfig,
    task_path: str | Path,
    lock_path: str | Path,
    evidence_packs_path: str | Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    at = _timestamp(moment)
    root = Path(evidence_packs_path)

    with RuntimeLock(lock_path, stale_seconds=task_config.lock_stale_seconds):
        registry = load_task_registry(task_path, group_id, now=moment)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise EvidencePackageError(
                "EVIDENCE_ROOT_UNAVAILABLE",
                f"无法创建或访问证据包根目录：{root}",
            ) from exc

        packages: list[dict[str, Any]] = []
        eligible_count = 0
        for _, raw_task in sorted(registry["tasks"].items()):
            if raw_task.get("state") != ELIGIBLE_STATE:
                continue
            eligible_count += 1
            task = validate_evidence_task(raw_task, group_id)
            existing = find_evidence_package(root, task["parent_key"])
            packages.append(
                _existing_result(existing, task)
                if existing is not None
                else _create_package(root, task, at)
            )

    created_count = sum(package["action"] == "CREATED" for package in packages)
    unchanged_count = sum(package["action"] == "UNCHANGED" for package in packages)
    return {
        "schema_version": 1,
        "ok": True,
        "group_id": group_id,
        "eligible_task_count": eligible_count,
        "package_count": len(packages),
        "created_count": created_count,
        "unchanged_count": unchanged_count,
        "packages": packages,
        "evidence_packs_path": str(root.resolve()),
    }
