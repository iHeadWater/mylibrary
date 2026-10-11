"""Rough cards -> candidates -> per-paper focused PDF reading -> revised candidates.

Only process contracts are enforced. Markdown remains opaque model output.
Each model result is durably saved before rendering; reruns resume immutable steps.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from hydrolitagent.cards.card_generators.codex_local_pdf import CodexLocalPdfAdapter
from hydrolitagent.cards.card_generators.codex_text import CodexTextAdapter
from hydrolitagent.cards.evidence_packages import EvidencePackageError, load_evidence_manifest
from hydrolitagent.cards.pdf_delivery import PdfDeliveryError, prepare_pdf_delivery
from hydrolitagent.cards.pdf_gate import PdfGateError
from hydrolitagent.cards.progress import report_progress
from hydrolitagent.cards.publication import atomic_text, text_hash, validate_saved_package
from hydrolitagent.cards.tasks import PipelineRunLock, TaskStoreError
from hydrolitagent.cards.zotero import ZoteroApiError

LEGACY_PROTOCOL = "cards-to-refined-candidates-v1"
PROTOCOL = "unified-theme-pool-v1"
LEGACY_ASSETS = ("discovery.md", "discovery.schema.json", "focused-reading.md",
          "focused-reading.schema.json", "refinement.md", "refinement.schema.json")
ASSETS = LEGACY_ASSETS + ("pool-discovery.md", "pool-discovery.schema.json")
SOURCE_FIELDS = ("evidence_id", "group_id", "parent_key", "attachment_key", "pdf_sha256")


class ThemeError(RuntimeError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


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
        "execution": {**{k: result.get(k) for k in ("cli_version", "ephemeral", "usage", "source_access")},
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


def _source_links(tasks, sources, directory, theme_id=None):
    lines = ["\n\n---\n程序维护的来源引用（不代表独立科学核验）：\n"]
    for task in tasks:
        eid = task["evidence_id"]
        path = sources[eid]["pack"] / "card.md"
        lines.append(f"- [{eid} 粗读卡](<{_link(path, directory)}>)")
        if theme_id:
            reading = sources[eid]["pack"] / "readings" / theme_id / "reading.md"
            lines[-1] += f" · [本主题定向精读](<{_link(reading, directory)}>)"
    return "\n".join(lines) + "\n"


def _run_legacy(config, report, *, progress, text_adapter, pdf_adapter, delivery_preparer, remaining_seconds):
    """Historical implementation retained for migration regression fixtures only.

    No CLI, scheduler or production dispatcher selects this path.
    """
    sources = _sources(config)
    report["source_count"] = len(sources)
    if not sources:
        report.update(status="NO_ROUGH_CARDS", note="尚无可用于主题生成的正式粗卡；未调用模型")
        return
    options = config.theme_pipeline
    assets_root = options.assets_dir or config.paths.templates_dir / "themes"
    assets = {name: (assets_root / name).read_text(encoding="utf-8") for name in LEGACY_ASSETS}
    for name in LEGACY_ASSETS:
        if name.endswith(".json"):
            json.loads(assets[name])
    cg = replace(config.card_generator, model=options.model or config.card_generator.model,
        reasoning_effort=options.reasoning_effort or config.card_generator.reasoning_effort,
        generation_timeout_seconds=options.timeout_seconds or config.card_generator.generation_timeout_seconds)
    if cg.adapter != "codex_cli" or cg.pdf_reader.adapter != "local_path":
        raise ThemeError("THEME_ADAPTER_UNSUPPORTED", "当前主题流程需要 codex_cli + local_path；暂未实现其他提供商适配")
    if cg.pdf_direct_trial is None or cg.pdf_direct_trial.reading_prompt_file is None:
        raise ThemeError("THEME_READING_CONFIG_MISSING", "缺少已配置的本地 PDF 阅读提示词")
    reading_prompt = cg.pdf_direct_trial.reading_prompt_file
    binding = {"protocol_version": LEGACY_PROTOCOL, "group_id": config.zotero.group_id,
        "research_goal": options.research_goal, "sources": [s["record"] for s in sources.values()],
        "model": cg.model, "reasoning_effort": cg.reasoning_effort,
        "assets": {k: text_hash(v) for k, v in assets.items()},
        "pdf_reading_prompt_sha256": text_hash(reading_prompt.read_text(encoding="utf-8"))}
    batch_id = "BATCH-" + _digest(binding)[:20]
    batch = _safe_path(config.paths.themes_dir, "candidates", batch_id)
    report.update(batch_id=batch_id, batch_path=str(batch),
        note="仅基于本批粗卡的探索性候选；不代表领域全貌；精读回填后仍需人确认才能转正式主题")
    if report.get("dry_run"):
        report.update(status="LOCAL_PREVIEW", source_ids=list(sources),
            discovery_saved=(batch / "discovery-result.json").exists(),
            batch_completed=(batch / "completion.json").exists())
        return
    _publish(_safe_path(batch, "inputs.json"), _json(binding))
    text_adapter = text_adapter or CodexTextAdapter(cg, progress=progress)
    pdf_adapter = pdf_adapter or CodexLocalPdfAdapter(cg, progress=progress)

    def invoke(stage, prompt, schema_name, *, source=None):
        _assert_sources(sources)
        remaining = remaining_seconds()
        if remaining < 1:
            raise ThemeError("RUN_TIME_LIMIT", "本轮时间预算已用完；完成步骤保留，下次继续")
        report["current_stage"] = stage
        report_progress(progress, "phase", stage=stage, message=stage)
        kwargs = {"output_schema_path": assets_root / schema_name,
                  "timeout_seconds": min(cg.generation_timeout_seconds, remaining), "run_label": stage}
        if source is None:
            report["model_call_count"] += 1
            return text_adapter.generate(prompt, **kwargs)
        delivery = delivery_preparer(config.zotero, config.pdf_gate, config.tasks,
            config.paths.tasks_file, config.paths.lock_file, config.paths.evidence_packs_dir,
            source["record"]["parent_key"], allow_trial_states=True)
        record = source["record"]
        if (delivery.pdf_sha256 != record["pdf_sha256"] or delivery.parent_key != record["parent_key"]
            or delivery.group_id != record["group_id"] or delivery.attachment_key != record["attachment_key"]
            or _file_sha(delivery.pdf_path) != record["pdf_sha256"]):
            raise ThemeError("THEME_PDF_MISMATCH", "定向精读 PDF 与粗卡来源不同；未调用模型")
        report["model_call_count"] += 1
        result = pdf_adapter.generate(prompt, working_directory=delivery.pdf_path.parent, source_pdf_path=delivery.pdf_path,
            zotero_parent_key=record["parent_key"], **kwargs)
        if _file_sha(delivery.pdf_path) != record["pdf_sha256"]:
            raise ThemeError("THEME_INPUT_CHANGED", "定向精读过程中原始 PDF 改变，未接受结果")
        return result

    prompt = assets["discovery.md"] + "\n\n输入材料：\n" + _json({"research_goal": options.research_goal,
        "cards": [{"evidence_id": eid, "markdown": source["card"]} for eid, source in sources.items()]})
    discovery = _result_record(_safe_path(batch, "discovery-result.json"), binding,
        lambda: invoke("候选主题：粗卡问题簇与初版", prompt, "discovery.schema.json"), report)
    themes = _discovery(discovery["output"], sources)
    _assert_sources(sources)
    _publish(_safe_path(batch, "problem-clusters.md"), discovery["output"]["problem_clusters_markdown"])
    index = [f"# 候选主题批次 {batch_id}\n\n状态和来源见各主题 manifest.json。仅为探索性候选，不是正式主题。\n"]
    for number, theme in enumerate(themes, 1):
        theme_id = "TH-" + batch_id[6:] + f"-{number:03d}"
        directory = _safe_path(batch, theme_id)
        initial = "<!-- CANDIDATE_INITIAL; AI-generated; not independently verified -->\n" + theme["candidate_markdown"]
        initial += _source_links(theme["paper_tasks"], sources, directory)
        _publish(_safe_path(directory, "initial.md"), initial)
        _publish(_safe_path(directory, "plan.json"), _json({"theme_id": theme_id, **theme}))
        index.append(f"- [{theme['title'].replace(chr(10), ' ')}](<{theme_id}/initial.md>) · [{theme_id} 修订结果](<{theme_id}/revised.md>)")
    _publish(_safe_path(batch, "index.md"), "\n".join(index) + "\n")
    report["candidate_count"] = len(themes)
    for number, theme in enumerate(themes, 1):
        theme_id = "TH-" + batch_id[6:] + f"-{number:03d}"
        directory = _safe_path(batch, theme_id)
        item = {"theme_id": theme_id, "title": theme["title"], "initial_path": str(directory / "initial.md"), "readings": []}
        report["themes"].append(item)
        focused = []
        try:
            for order, task in enumerate(theme["paper_tasks"], 1):
                source = sources[task["evidence_id"]]
                reading_dir = _safe_path(source["pack"], "readings", theme_id)
                read_binding = {"batch_id": batch_id, "theme_id": theme_id, "source": source["record"],
                    "theme_sha256": _digest(theme), "focus": task["focus"]}
                read_prompt = assets["focused-reading.md"] + "\n\n输入材料：\n" + _json({
                    "theme_id": theme_id, "candidate": theme["candidate_markdown"], "focus": task["focus"],
                    "evidence_id": task["evidence_id"], "rough_card": source["card"]})
                stage = f"theme_focused_reading {number}/{len(themes)} {theme_id} 文献 {order}/{len(theme['paper_tasks'])} {task['evidence_id']}"
                reading = _result_record(_safe_path(reading_dir, "result.json"), read_binding,
                    lambda: invoke(stage, read_prompt, "focused-reading.schema.json", source=source), report)
                access = reading["execution"].get("source_access") or {}
                if (reading["execution"].get("ephemeral") is not True
                    or access.get("source_sha256") != source["record"]["pdf_sha256"]
                    or access.get("parent_key") != source["record"]["parent_key"]
                    or access.get("method") != "local_pdf_path"
                    or access.get("source_identity_verified") is not True
                    or access.get("source_unchanged") is not True
                    or access.get("model_reading_report_accepted") is not True):
                    raise ThemeError("THEME_READING_PROCESS_INVALID", "缺少原始 PDF 来源及阅读流程记录，不能冒充定向精读")
                body = _nonempty(reading["output"].get("reading_markdown"), "定向精读正文")
                _assert_sources(sources)
                _publish(_safe_path(reading_dir, "reading.md"), "<!-- AI theme-focused reading; not independently verified -->\n" + body)
                read_manifest = {"status": "FOCUSED_READING_SAVED", **read_binding,
                    "reading_sha256": text_hash(body), "result_sha256": _digest(reading),
                    "scientific_correctness_verified": False}
                _publish(_safe_path(reading_dir, "manifest.json"), _json(read_manifest))
                focused.append({"evidence_id": task["evidence_id"], "reading_markdown": body,
                    "result_sha256": _digest(reading)})
                item["readings"].append({"evidence_id": task["evidence_id"], "path": str(reading_dir / "reading.md")})
                report_progress(progress, "phase", message=f"定向精读已保存：{reading_dir / 'reading.md'}")
            revised_binding = {"theme_id": theme_id, "theme_sha256": _digest(theme),
                "readings": [{"evidence_id": r["evidence_id"], "result_sha256": r["result_sha256"]} for r in focused]}
            revision_prompt = assets["refinement.md"] + "\n\n输入材料：\n" + _json({"candidate": theme,
                "research_goal": options.research_goal, "focused_readings": focused})
            revision = _result_record(_safe_path(directory, "revision-result.json"), revised_binding,
                lambda: invoke(f"候选主题回填修订 {number}/{len(themes)} {theme_id}", revision_prompt, "refinement.schema.json"), report)
            revised = _nonempty(revision["output"].get("revised_markdown"), "修订主题正文")
            revised = "<!-- CANDIDATE_REFINED; NOT CONFIRMED; AI-generated -->\n" + revised
            revised += _source_links(theme["paper_tasks"], sources, directory, theme_id)
            _assert_sources(sources)
            _publish(_safe_path(directory, "revised.md"), revised)
            _publish(_safe_path(directory, "manifest.json"), _json({"status": "CANDIDATE_REFINED",
                "formal_confirmation": None, "theme_id": theme_id, "batch_id": batch_id,
                "initial_sha256": text_hash((directory / "initial.md").read_text(encoding="utf-8")),
                "revised_sha256": text_hash(revised), "reading_references": [{**r,
                    "path": _link(sources[r["evidence_id"]]["pack"] / "readings" / theme_id / "reading.md", directory)}
                    for r in revised_binding["readings"]],
                "scientific_correctness_verified": False}))
            item.update(status="CANDIDATE_REFINED", revised_path=str(directory / "revised.md"))
            report["refined_count"] += 1
            report_progress(progress, "phase", message=f"修订候选主题已保存：{directory / 'revised.md'}")
        except (ThemeError, PdfDeliveryError, PdfGateError, ZoteroApiError) as exc:
            item.update(status="BLOCKED", error={"code": exc.code, "message": str(exc), **getattr(exc, "details", {})})
            report.update(ok=False, status="COMPLETED_WITH_BLOCKERS")
            report.setdefault("error", {"code": exc.code, "message": f"{theme_id}：{exc}", "theme_id": theme_id})
            report_progress(progress, "phase", message=f"{theme_id} 暂停：{exc.code}；已完成步骤保留")
            # Stop on provider/global failure; other PDF/source-specific blocked themes can still finish.
            if isinstance(exc, ThemeError) and (exc.code.startswith("CODEX_") or exc.code in {"THEME_PROVIDER_ERROR", "RUN_TIME_LIMIT"}):
                report["deferred_theme_count"] = len(themes) - number
                break
    if report["ok"]:
        _assert_sources(sources)
        _publish(_safe_path(batch, "completion.json"), _json({"status": "CANDIDATES_REFINED", "batch_id": batch_id,
            "theme_ids": [item["theme_id"] for item in report["themes"]], "formal_confirmation": None}))
        report["status"] = "CANDIDATES_REFINED" if themes else "NO_CANDIDATES"


def _run(config, report, **kwargs):
    from hydrolitagent.cards.theme_pool_runner import run
    return run(config, report, **kwargs)


def run_themes(config, *, progress=None, dry_run=False, text_adapter=None, pdf_adapter=None,
               delivery_preparer=None, remaining_seconds=None, migration_only=False):
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
            _run(config, report, progress=progress, text_adapter=text_adapter, pdf_adapter=pdf_adapter,
                delivery_preparer=delivery_preparer, remaining_seconds=remaining_seconds)
        else:
            with PipelineRunLock(config.paths.lock_file.with_name(config.paths.lock_file.name + ".themes")):
                _run(config, report, progress=progress, text_adapter=text_adapter, pdf_adapter=pdf_adapter,
                    delivery_preparer=delivery_preparer or prepare_pdf_delivery, remaining_seconds=remaining_seconds)
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
