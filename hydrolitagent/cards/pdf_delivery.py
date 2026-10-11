from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hydrolitagent.cards.config import PdfGateConfig, TaskConfig, ZoteroConfig
from hydrolitagent.cards.evidence_packages import (
    find_evidence_package,
    load_evidence_manifest,
    validate_evidence_task,
)
from hydrolitagent.cards.pdf_gate import ITEM_KEY_PATTERN, evaluate_pdf_gate
from hydrolitagent.cards.tasks import RuntimeLock, load_task_registry
from hydrolitagent.cards.zotero import ZoteroClient


DELIVERABLE_TASK_STATES = frozenset(
    {"READY_FOR_EXTRACTION", "PROCESSING", "RETRY_PENDING"}
)


class PdfDeliveryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _timestamp(value: datetime | None = None) -> str:
    moment = value or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PdfDelivery:
    group_id: int
    parent_key: str
    attachment_key: str
    task_id: str
    pdf_sha256: str
    pdf_path: Path
    file_size_bytes: int
    evidence_package_path: Path
    manifest_path: Path
    verified_at: str

    def as_result(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": True,
            "delivery_status": "READY",
            "delivery_mode": "LOCAL_FILE_PATH",
            "group_id": self.group_id,
            "parent_key": self.parent_key,
            "attachment_key": self.attachment_key,
            "task_id": self.task_id,
            "pdf_sha256": self.pdf_sha256,
            "pdf_path": str(self.pdf_path),
            "file_size_bytes": self.file_size_bytes,
            "evidence_package_path": str(self.evidence_package_path),
            "manifest_path": str(self.manifest_path),
            "verified_at": self.verified_at,
        }


def _validate_manifest_matches_task(
    manifest: dict[str, Any],
    task: dict[str, Any],
    manifest_path: Path,
) -> None:
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
        raise PdfDeliveryError(
            "PDF_DELIVERY_MANIFEST_MISMATCH",
            f"证据包 manifest 与任务不一致（{', '.join(mismatched)}）：{manifest_path}",
        )


def prepare_pdf_delivery(
    zotero: ZoteroConfig,
    gate: PdfGateConfig,
    task_config: TaskConfig,
    task_path: str | Path,
    lock_path: str | Path,
    evidence_packs_path: str | Path,
    parent_key: str,
    *,
    client: ZoteroClient | None = None,
    now: datetime | None = None,
    allow_trial_states: bool = False,
) -> PdfDelivery:
    if zotero.group_id is None:
        raise PdfDeliveryError("CONFIG_ERROR", "PDF 交付需要目标 Zotero 群组 ID")
    normalized_key = parent_key.strip().upper()
    if not ITEM_KEY_PATTERN.fullmatch(normalized_key):
        raise PdfDeliveryError("INVALID_ITEM_KEY", "父条目 Key 必须是 8 位字母或数字")

    evidence_root = Path(evidence_packs_path)
    with RuntimeLock(lock_path, stale_seconds=task_config.lock_stale_seconds):
        registry = load_task_registry(task_path, zotero.group_id, now=now)
        raw_task = registry["tasks"].get(normalized_key)
        if not isinstance(raw_task, dict):
            raise PdfDeliveryError(
                "PDF_DELIVERY_TASK_NOT_FOUND",
                f"任务清单中找不到父条目：{normalized_key}",
            )
        deliverable_states = (
            DELIVERABLE_TASK_STATES | {"COMPLETED", "QUALITY_FAILED"}
            if allow_trial_states
            else DELIVERABLE_TASK_STATES
        )
        if raw_task.get("state") not in deliverable_states:
            raise PdfDeliveryError(
                "PDF_DELIVERY_TASK_NOT_READY",
                f"任务 {normalized_key} 当前状态不可交付：{raw_task.get('state')}",
            )

        task = validate_evidence_task(raw_task, zotero.group_id)
        if task["parent_key"] != normalized_key:
            raise PdfDeliveryError(
                "PDF_DELIVERY_TASK_MISMATCH",
                "任务索引与任务记录中的父条目 Key 不一致",
            )
        if not evidence_root.is_dir():
            raise PdfDeliveryError(
                "PDF_DELIVERY_PACKAGE_MISSING",
                f"证据包根目录不存在：{evidence_root}",
            )
        try:
            package_path = find_evidence_package(evidence_root, normalized_key)
        except OSError as exc:
            raise PdfDeliveryError(
                "PDF_DELIVERY_PACKAGE_UNREADABLE",
                f"无法读取证据包目录：{evidence_root}",
            ) from exc
        if package_path is None:
            raise PdfDeliveryError(
                "PDF_DELIVERY_PACKAGE_MISSING",
                f"父条目 {normalized_key} 尚无证据包骨架，请先运行 packages-sync",
            )

        manifest_path = package_path / "manifest.json"
        card_path = package_path / "card.md"
        if not manifest_path.is_file() or not card_path.is_file():
            raise PdfDeliveryError(
                "PDF_DELIVERY_PACKAGE_INCOMPLETE",
                f"证据包缺少 manifest.json 或 card.md：{package_path}",
            )
        manifest = load_evidence_manifest(manifest_path)
        _validate_manifest_matches_task(manifest, task, manifest_path)

        gate_result = evaluate_pdf_gate(
            zotero,
            gate,
            normalized_key,
            client=client,
        )

    if gate_result.get("gate_status") != "READY":
        raise PdfDeliveryError(
            str(gate_result.get("reason_code") or "PDF_DELIVERY_NOT_READY"),
            str(gate_result.get("message") or "PDF 当前不可交付"),
        )
    pdf = gate_result.get("pdf")
    if not isinstance(pdf, dict):
        raise PdfDeliveryError(
            "PDF_DELIVERY_INVALID_GATE_RESULT",
            "PDF 门禁通过但没有返回 PDF 信息",
        )
    if pdf.get("attachment_key") != task["attachment_key"]:
        raise PdfDeliveryError(
            "PDF_ATTACHMENT_CHANGED",
            "Zotero 当前 PDF 附件与任务及 manifest 记录不一致",
        )
    current_hash = pdf.get("sha256")
    if not isinstance(current_hash, str) or current_hash.lower() != task["pdf_sha256"]:
        raise PdfDeliveryError(
            "PDF_INPUT_CHANGED",
            "Zotero 当前 PDF 哈希与任务及 manifest 记录不一致",
        )
    raw_path = pdf.get("local_path")
    if not isinstance(raw_path, str) or not raw_path:
        raise PdfDeliveryError(
            "PDF_DELIVERY_PATH_MISSING",
            "PDF 门禁通过但没有返回本地原始文件路径",
        )
    try:
        pdf_path = Path(raw_path).resolve(strict=True)
        file_size = pdf_path.stat().st_size
    except OSError as exc:
        raise PdfDeliveryError(
            "PDF_FILE_UNREADABLE",
            "PDF 复核后已无法访问，停止交付",
        ) from exc
    if file_size != pdf.get("file_size_bytes"):
        raise PdfDeliveryError(
            "PDF_INPUT_CHANGED",
            "PDF 文件大小在复核后发生变化，停止交付",
        )

    return PdfDelivery(
        group_id=zotero.group_id,
        parent_key=normalized_key,
        attachment_key=task["attachment_key"],
        task_id=task["task_id"],
        pdf_sha256=task["pdf_sha256"],
        pdf_path=pdf_path,
        file_size_bytes=file_size,
        evidence_package_path=package_path.resolve(),
        manifest_path=manifest_path.resolve(),
        verified_at=_timestamp(now),
    )
