"""Rough cards -> candidates -> per-paper focused reading -> revised candidates.

The live pipeline reads prepared Markdown: every source PDF is converted once by
the configured ``PaperConverter``, and a focused reading is accepted only when
``domain.grounding`` verifies its quotes and canaries against that conversion.
Model prose remains opaque output; only the process contract is enforced.

Each model result is durably saved before rendering; reruns resume immutable
steps. Historical PDF-reading batches are read as static fixtures and migrated
into the pool; they are never regenerated.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from hydrolitagent.cards.evidence_packages import EvidencePackageError, load_evidence_manifest
from hydrolitagent.cards.pdf_delivery import PdfDeliveryError, prepare_pdf_delivery
from hydrolitagent.cards.pdf_gate import PdfGateError
from hydrolitagent.cards.publication import atomic_text, text_hash, validate_saved_package
from hydrolitagent.cards.tasks import PipelineRunLock, TaskStoreError
from hydrolitagent.cards.zotero import ZoteroApiError

PROTOCOL = "unified-theme-pool-v1"
# Assets the historical PDF-reading batch used. Kept so legacy batches can be
# replayed and decoded; the live pipeline does not read them.
LEGACY_ASSETS = ("discovery.md", "discovery.schema.json", "focused-reading.md",
          "focused-reading.schema.json", "refinement.md", "refinement.schema.json")
ASSETS = LEGACY_ASSETS + ("pool-discovery.md", "pool-discovery.schema.json")
# Assets the Markdown-first pipeline actually uses. The focused reading prompt
# and schema differ from v1: the model reads paper.md and must return a reading
# receipt, so the output can be grounded instead of trusted.
READING_ASSETS = ("focused-reading-markdown.md", "focused-reading-markdown.schema.json")
# The v1 assets stay in the binding even though the live pipeline no longer reads
# them: a legacy batch's recorded asset hashes are compared against this set, so
# dropping them would make every migrated pool look stale. They are not used to
# generate anything.
PIPELINE_ASSETS = (*ASSETS, *READING_ASSETS)
SOURCE_FIELDS = ("evidence_id", "group_id", "parent_key", "attachment_key", "pdf_sha256")


class ThemeError(RuntimeError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


# --- Runner seam ----------------------------------------------------------------------
# The live theme workflow receives a ``composition.MarkdownPipeline`` (converter,
# paper store, runner, options). It never names a provider: the runner id is
# configuration, and the registry decides how to build it.


def _default_pipeline(config):
    """Build the configured Markdown pipeline through the composition root."""

    from hydrolitagent.cards.composition import build_theme_pipeline
    return build_theme_pipeline(config)


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _digest(value):
    return text_hash(_json(value))


def _nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ThemeError("THEME_OUTPUT_EMPTY", f"{label} 为空或不是文本；原始输出保留")
    return value  # Never normalize headings, labels, tables, or prose.


def _safe_path(root, *parts):
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ThemeError("THEME_PATH_OUTSIDE_ROOT", "输出路径指向配置目录之外，未写入")
    # Do not publish through symbolic links or Windows junctions.
    current = target
    while current != root:
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ThemeError("THEME_PATH_REDIRECTED", "输出路径包含重定向，未覆盖")
        current = current.parent
    return target


def _publish(path, content):
    """Atomic no-clobber publication, including interrupted partial bundles."""
    expected = content.encode("utf-8")
    def matches_existing():
        # Git autocrlf may change physical line endings on another Windows checkout.
        # Treat that as transport normalization, never as permission to rewrite prose.
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        return not path.is_symlink() and path.read_text(encoding="utf-8") == normalized
    if path.exists():
        if not matches_existing():
            raise ThemeError("THEME_FILE_CONFLICT", "文件已存在且与保存记录不同；保留修改，不重跑或覆盖", path=str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".theme-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(expected)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(name, path)  # Unlike replace(), cannot overwrite a concurrently created file.
        except FileExistsError:
            if not matches_existing():
                raise ThemeError("THEME_FILE_CONFLICT", "文件在保存期间发生变化，未覆盖", path=str(path))
    finally:
        Path(name).unlink(missing_ok=True)


def _file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sources(config):
    result = {}
    root = config.paths.evidence_packs_dir
    for manifest_path in sorted(root.glob("*/manifest.json")):
        manifest = load_evidence_manifest(manifest_path)
        if manifest["group_id"] != config.zotero.group_id or manifest["card_status"] != "ROUGH":
            continue
        pack = _safe_path(root, manifest_path.parent.name)
        manifest = validate_saved_package(pack)
        eid = manifest["evidence_id"]
        if not re.fullmatch(r"EV-[A-Z0-9]{8}", eid) or eid != "EV-" + manifest["parent_key"]:
            raise ThemeError("THEME_SOURCE_ID_INVALID", "证据包标识与父条目不一致")
        if eid in result:
            raise ThemeError("THEME_DUPLICATE_SOURCE", "同一篇文献存在多个证据包；不重复读取", evidence_id=eid)
        card = (pack / "card.md").read_text(encoding="utf-8")
        result[eid] = {"pack": pack, "card": card, "record": {
            **{k: manifest[k] for k in SOURCE_FIELDS}, "card_sha256": text_hash(card),
            "package_directory": pack.name}}
    return result


def _assert_sources(sources):
    for source in sources.values():
        manifest = validate_saved_package(source["pack"])
        if manifest is None or any(manifest[k] != source["record"][k] for k in SOURCE_FIELDS):
            raise ThemeError("THEME_INPUT_CHANGED", "运行过程中证据包来源改变；不混用新旧结果")
        if text_hash((source["pack"] / "card.md").read_text(encoding="utf-8")) != source["record"]["card_sha256"]:
            raise ThemeError("THEME_INPUT_CHANGED", "运行过程中粗卡改变；不混用新旧结果")


def _discovery(output, sources):
    _nonempty(output.get("problem_clusters_markdown"), "问题簇说明")
    raw = output.get("themes")
    if not isinstance(raw, list):
        raise ThemeError("THEME_ROUTE_INVALID", "缺少可读取的候选主题清单")
    themes = []
    seen = set()
    for theme in raw:
        if not isinstance(theme, dict):
            raise ThemeError("THEME_ROUTE_INVALID", "候选主题路由不是对象")
        _nonempty(theme.get("title"), "主题名称")
        _nonempty(theme.get("candidate_markdown"), "候选主题正文")
        tasks = theme.get("paper_tasks")
        if not isinstance(tasks, list) or not tasks:
            raise ThemeError("THEME_ROUTE_INVALID", "候选主题没有关联可精读的来源")
        grouped = {}
        for task in tasks:
            if not isinstance(task, dict) or not isinstance(task.get("evidence_id"), str) or task["evidence_id"] not in sources:
                raise ThemeError("THEME_UNKNOWN_SOURCE", "主题引用了统一文献池之外的证据包；未调用 PDF 或写入模型指定路径")
            focus = _nonempty(task.get("focus"), "定向精读任务")
            grouped.setdefault(task["evidence_id"], [])
            if focus not in grouped[task["evidence_id"]]:
                grouped[task["evidence_id"]].append(focus)
        normalized = {"title": theme["title"], "candidate_markdown": theme["candidate_markdown"],
            "paper_tasks": [{"evidence_id": eid, "focus": "\n\n".join(foci)} for eid, foci in sorted(grouped.items())]}
        fingerprint = _digest(normalized)
        if fingerprint not in seen:
            themes.append(normalized)
            seen.add(fingerprint)
    return themes


def _result_record(path, binding, invoke, report):
    if path.exists():
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        record = wrapper["record"]
        if _digest(record) != wrapper["sha256"] or record["binding"] != binding:
            raise ThemeError("THEME_CHECKPOINT_CONFLICT", "步骤记录与输入或指纹不符；未重跑", path=str(path))
        report["reused_step_count"] += 1
        return record
    result = invoke()
    if not result.get("ok"):
        error = result.get("error", {})
        raise ThemeError(error.get("code", "THEME_MODEL_FAILED"), error.get("message", "主题步骤调用失败"),
                         provider=error)
    if not isinstance(result.get("output"), dict):
        raise ThemeError("THEME_TRANSPORT_INVALID", "模型没有返回可保存的结果对象")
    record = {"protocol_version": binding.get("protocol_version", PROTOCOL), "binding": binding, "output": result["output"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        # Only the keys the result actually carries are written: a legacy result
        # keeps its exact previous on-disk shape instead of gaining null fields.
        "execution": {**{k: result[k] for k in (
                "cli_version", "ephemeral", "usage", "source_access",
                "runner_id", "warnings") if k in result},
            "model": result.get("configured_model", result.get("model")),
            "reasoning_effort": result.get("configured_reasoning_effort", result.get("reasoning_effort"))},
        "scientific_correctness_verified": False}
    _publish(path, _json({"record": record, "sha256": _digest(record)}))
    report["saved_step_count"] += 1
    return record


def _link(path, directory):
    try:
        return Path(os.path.relpath(path, directory)).as_posix()
    except ValueError:
        # Windows paths on separate drives have no relative representation.
        return path.as_posix()


def _run(config, report, **kwargs):
    from hydrolitagent.cards.theme_pool_runner import run
    return run(config, report, **kwargs)


def run_themes(config, *, progress=None, dry_run=False,
               delivery_preparer=None, remaining_seconds=None, migration_only=False,
               pipeline=None):
    """Run the theme pipeline.

    ``pipeline`` is the ``composition.MarkdownPipeline`` (converter, paper store,
    runner, options). Without it the configured runner is built through
    ``composition`` on first use, so ``run_themes(config)`` stays callable.
    """
    started = time.monotonic()
    cap = config.pipeline.max_run_seconds
    remaining_seconds = remaining_seconds or (lambda: float("inf") if cap is None else cap - (time.monotonic() - started))
    report = {"schema_version": 1, "ok": True, "operation": "themes_run", "status": "STARTED",
        "protocol_version": PROTOCOL, "run_id": uuid4().hex, "model_call_count": 0,
        "saved_step_count": 0, "reused_step_count": 0, "candidate_count": 0,
        "refined_count": 0, "themes": [], "dry_run": dry_run,
        "migration_only": migration_only, "git_modified": False}
    try:
        if dry_run:
            _run(config, report, progress=progress,
                delivery_preparer=delivery_preparer, remaining_seconds=remaining_seconds,
                pipeline=pipeline)
        else:
            with PipelineRunLock(config.paths.lock_file.with_name(config.paths.lock_file.name + ".themes")):
                _run(config, report, progress=progress,
                    delivery_preparer=delivery_preparer or prepare_pdf_delivery, remaining_seconds=remaining_seconds,
                    pipeline=pipeline)
    except KeyboardInterrupt:
        report.update(ok=False, status="CANCELLED", error={"code": "CANCELLED", "message": "已中止；保存的候选/精读步骤保留，下次继续"})
    except (ThemeError, EvidencePackageError, PdfDeliveryError, PdfGateError, TaskStoreError, ZoteroApiError) as exc:
        report.update(ok=False, status="BLOCKED", error={"code": exc.code, "message": str(exc), **getattr(exc, "details", {})})
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        report.update(ok=False, status="BLOCKED", error={"code": "THEME_LOCAL_ERROR",
            "message": "文件、配置或步骤记录不可读取；已完成结果保留，不覆盖、不自动重跑", "exception_type": type(exc).__name__})
    report.update(elapsed_seconds=round(time.monotonic() - started, 2), model_invoked=report["model_call_count"] > 0)
    if not dry_run:
        path = config.paths.logs_dir / "theme-runs" / (report["run_id"] + ".json")
        report["report_path"] = str(path)
        try:
            atomic_text(path, _json(report))
        except OSError:
            report.pop("report_path", None)
            report.update(ok=False, report_warning="摘要写入失败；已保存的主题和精读不会撤销")
    return report



def load_subject_card_sources(config, selected):
    """#33 input boundary: accept #30 drafts only through the #31 gate.

    The legacy evidence-pack scanner remains separate. Resolve every selection
    before returning any input for a theme-generation call.
    """
    from hydrolitagent.cards.card_validation import CardValidationError, load_validated_subject_card
    if not isinstance(selected, list) or not selected:
        raise ThemeError("CARD_SELECTION_INVALID", "需要显式选择主体卡、输入和校验记录")
    result = []
    for reference in selected:
        if not isinstance(reference, dict) or any(
            not isinstance(reference.get(key), (str, Path))
            for key in ("draft_path", "input_path", "validation_path")
        ):
            raise ThemeError("CARD_SELECTION_INVALID", "主体卡选择缺少草稿、输入或校验记录路径")
        try:
            accepted = load_validated_subject_card(config, **{
                key: reference[key] for key in ("draft_path", "input_path", "validation_path")
            })
        except CardValidationError as exc:
            raise ThemeError(exc.code, str(exc), validation=exc.report) from exc
        draft = accepted["draft"]
        result.append({"card": draft["card_body_markdown"], "source": draft["source"],
                       "machine_fields": draft["machine_fields"], "validation": accepted["validation"]})
    return result
