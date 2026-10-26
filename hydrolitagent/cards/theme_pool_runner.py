"""One global knowledge pool, incremental candidate evolution and reading reuse.

Stage 5: the live workflow reads Markdown, not PDFs. Every model call goes
through one ``CardRunner`` obtained from ``composition``:

* discovery and refinement are synthesis tasks (``paper=None``; the prompt
  carries the cards), role ``theme_discovery`` / ``theme_synthesis``;
* a focused reading is a ``focused_reading`` task against a ``PreparedPaper``
  converted by the configured ``PaperConverter`` and cached by ``PaperStore``.

Focused readings are accepted only when ``domain.grounding`` verifies the
model's reading receipt against the prepared Markdown. A verified reading proves
the output is grounded in the text; it never proves the science is correct.

This module never imports a concrete provider, and never receives a PDF path
from the model side: the only PDF it touches is the source that the converter
hashes before conversion.
"""
from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import replace

from hydrolitagent.cards import theme_pool as pool
from hydrolitagent.cards import themes as core
from hydrolitagent.cards.application.prepare_paper import prepare_paper
from hydrolitagent.cards.application.workspace import (
    runtime_dir,
    stage_paper_workspace,
    stage_text_workspace,
)
from hydrolitagent.cards.domain.grounding import expected_canaries, verify_reading
from hydrolitagent.cards.domain.reading import GroundingError, ReadingReceipt
from hydrolitagent.cards.domain.source_access import MARKDOWN_PREPARED
from hydrolitagent.cards.ports.paper import ConversionFailure
from hydrolitagent.cards.ports.runner import CardRunRequest
from hydrolitagent.cards.progress import report_progress
from hydrolitagent.cards.publication import text_hash


def _summary(config, state, report):
    report["themes"] = []
    for tid, entry in sorted(state["themes"].items()):
        if entry["status"] != pool.ACTIVE:
            continue
        current = entry["current"]
        directory = pool.root_path(config, current["directory"])
        report["themes"].append({"theme_id": tid, "title": entry["title"], "status": entry["status"],
            "initial_path": str(directory / "initial.md"), "revised_path": str(directory / "revised.md"),
            "readings": [{"evidence_id": ref["source"]["evidence_id"],
                          "path": str(pool.reading_path(config, ref) / "reading.md")}
                         for ref in current["readings"]]})
    report["candidate_count"] = report["refined_count"] = len(report["themes"])
    report["retired_count"] = sum(e["status"] == pool.RETIRED for e in state["themes"].values())
    report["status"] = "CANDIDATES_REFINED" if report["themes"] else "NO_CANDIDATES"


def _links(config, refs, directory):
    lines = ["\n\n---\n程序维护的来源引用（不代表独立科学核验）：\n"]
    for ref in refs:
        eid = ref["source"]["evidence_id"]
        pack = core._safe_path(config.paths.evidence_packs_dir, ref["source"]["package_directory"])
        read = pool.reading_path(config, ref) / "reading.md"
        lines.append(f"- [{eid} 粗卡](<{core._link(pack / 'card.md', directory)}>)"
                     f" · [定向精读](<{core._link(read, directory)}>)")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# Source → prepared paper
# --------------------------------------------------------------------------------------


def _prepared_source(config, source, *, delivery_preparer, pipeline):
    """Deliver the pack's PDF, convert it once, and prove the identities match.

    The delivery step verifies the PDF against the evidence pack; the store
    hashes the file again before conversion, so a PDF that changed between the
    two steps is rejected instead of being read under a stale identity.
    """

    identity = source["record"]
    delivery = delivery_preparer(config.zotero, config.pdf_gate, config.tasks,
        config.paths.tasks_file, config.paths.lock_file, config.paths.evidence_packs_dir,
        identity["parent_key"], allow_trial_states=True)
    if (delivery.pdf_sha256 != identity["pdf_sha256"] or delivery.parent_key != identity["parent_key"]
            or delivery.group_id != identity["group_id"]
            or delivery.attachment_key != identity["attachment_key"]
            or core._file_sha(delivery.pdf_path) != identity["pdf_sha256"]):
        raise core.ThemeError("THEME_PDF_MISMATCH", "原始 PDF 与证据包身份不符，未调用模型")
    try:
        prepared = prepare_paper(
            delivery.pdf_path,
            converter=pipeline.converter,
            store=pipeline.store,
            options=pipeline.options,
            group_id=identity["group_id"],
            parent_key=identity["parent_key"],
            attachment_key=identity["attachment_key"],
        )
    except ConversionFailure as exc:
        # One unreadable PDF blocks its theme, not the whole pool run.
        raise core.ThemeError(exc.error.code, exc.error.message,
                              fix=exc.error.fix) from exc
    if prepared.source.pdf_sha256 != identity["pdf_sha256"]:
        raise core.ThemeError("THEME_INPUT_CHANGED", "原始 PDF 在转换前改变，未接受结果")
    return delivery, prepared


def _reading_prompt(prepared):
    """Input material for one focused reading, built from the prepared paper."""

    markdown = prepared.markdown_path.read_text(encoding="utf-8")
    return {
        "markdown_file": "paper.md",
        "markdown_sha256": prepared.markdown_sha256,
        "page_count": prepared.page_count,
        "reading_canaries": list(expected_canaries(markdown)),
        "page_anchors": [
            {"page": anchor.page, "role": anchor.role, "heading": anchor.heading}
            for anchor in prepared.page_anchors
        ],
        "figures": [
            {"figure_id": figure.figure_id, "page": figure.page,
             "file": f"figures/{figure.path.name}", "caption": figure.caption}
            for figure in prepared.figures
        ],
    }


def _reading_access(prepared, output):
    """Ground a focused reading and project it into ``source_access``.

    A hard grounding failure is re-raised as a ``ThemeError`` so the theme pool
    records one structured blocker instead of an uncaught exception. A reading
    whose quote coverage is below the threshold is rejected here: a partial read
    must not become theme evidence.
    """

    markdown = prepared.markdown_path.read_text(encoding="utf-8")
    if text_hash(markdown) != prepared.markdown_sha256:
        raise core.ThemeError("MARKDOWN_SHA_MISMATCH", "转换产物在落盘后发生了变化，拒绝使用")
    declared_pages = output.get("source_page_count")
    if declared_pages is not None and declared_pages != prepared.page_count:
        raise core.ThemeError("THEME_READING_PAGE_COUNT_MISMATCH",
                              "模型页数与已转换 Markdown 的页锚点数不一致",
                              declared=declared_pages, actual=prepared.page_count)
    try:
        reading = verify_reading(
            ReadingReceipt.from_output(output), markdown, prepared.page_anchors
        )
    except GroundingError as exc:
        raise core.ThemeError(exc.code, str(exc), diagnostic=dict(exc.detail)) from exc
    if not reading.verified:
        raise core.ThemeError("THEME_READING_NOT_VERIFIED",
                              "定向精读的引文覆盖率不足，未作为主题证据保存",
                              reading=reading.as_dict())
    return {
        "method": MARKDOWN_PREPARED,
        "source_pdf_sha256": prepared.source.pdf_sha256,
        "markdown_sha256": prepared.markdown_sha256,
        "parent_key": prepared.source.parent_key,
        "page_count": prepared.page_count,
        "converter_id": prepared.converter_id,
        "converter_version": prepared.converter_version,
        "reading": reading.as_dict(),
    }


# --------------------------------------------------------------------------------------
# One pool change
# --------------------------------------------------------------------------------------


def run(config, report, *, progress, pipeline, delivery_preparer, remaining_seconds):
    """Run one pool change through the configured runner."""

    sources = core._sources(config)
    report.update(protocol_version=pool.PROTOCOL, source_count=len(sources),
                  pool_path=str(config.paths.themes_dir),
                  index_path=str(config.paths.themes_dir / "index.md"),
                  reused_reading_count=0, updated_theme_count=0,
                  note="统一文献池与主题池；运行记录不隔开知识。候选可自动演化，正式主题不自动覆盖")
    if not sources:
        report.update(status="NO_ROUGH_CARDS")
        return
    options = config.theme_pipeline
    assets_root = options.assets_dir or config.paths.templates_dir / "themes"
    assets = {name: (assets_root / name).read_text(encoding="utf-8")
              for name in core.PIPELINE_ASSETS}
    for name in core.PIPELINE_ASSETS:
        if name.endswith(".json"):
            json.loads(assets[name])
    cg = replace(config.card_generator, model=options.model or config.card_generator.model,
        reasoning_effort=options.reasoning_effort or config.card_generator.reasoning_effort,
        generation_timeout_seconds=options.timeout_seconds or config.card_generator.generation_timeout_seconds)
    # The runner is configuration, not a hard-coded provider: an unknown id is
    # rejected by the registry when the pipeline is built, with the list of ids
    # that would have worked.
    binding = {"protocol_version": pool.PROTOCOL, "group_id": config.zotero.group_id,
        "research_goal": options.research_goal, "sources": [s["record"] for s in sources.values()],
        "model": cg.model, "reasoning_effort": cg.reasoning_effort,
        "assets": {k: text_hash(v) for k, v in assets.items()}}
    state, imported = pool.migrate(config, binding, apply=not report["dry_run"])
    report["imported_theme_count"] = imported
    pool.check_index(config, state)
    if report["dry_run"]:
        report.update(status="LOCAL_PREVIEW", source_ids=list(sources), candidate_count=sum(
            e["status"] == pool.ACTIVE for e in state["themes"].values()),
            input_changed=state["last_input"] != core._digest(binding))
        return
    if report.get("migration_only"):
        _summary(config, state, report)
        report["action"] = "MIGRATED" if imported else "UNCHANGED"
        return
    if state["last_input"] == core._digest(binding):
        _summary(config, state, report)
        refs = {r["reading_id"] for e in state["themes"].values() if e["status"] == pool.ACTIVE
                for r in e["current"]["readings"]}
        report.update(action="UNCHANGED", reused_reading_count=len(refs),
                      reused_step_count=1 + len(refs) + report["candidate_count"])
        return
    # Built lazily: a dry run, a migration-only run and an unchanged rerun must
    # not require a working runner.
    pipeline = pipeline or core._default_pipeline(config)
    base = pool.load(config)  # None for a completely new, uninitialized pool.
    catalog = pool.reading_catalog(config, state)
    change_id = "CHANGE-" + core._digest({"base": base, "input": binding})[:24]
    change_dir = pool.root_path(config, "changes/" + change_id)
    report.update(change_id=change_id, change_path=str(change_dir))
    core._publish(change_dir / "inputs.json", core._json({"base_registry": base, "input": binding}))

    def unchanged():
        core._assert_sources(sources)
        if pool.load(config) != base:
            raise core.ThemeError("THEME_POOL_CHANGED", "处理中主题池发生变化，保留结果、不覆盖")
        pool.check_index(config, state)

    def run_stage(stage, *, schema_name, role, prompt, source=None):
        """One runner call; a reading is converted and grounded, a synthesis is not."""

        unchanged()
        remaining = remaining_seconds()
        if remaining < 1:
            raise core.ThemeError("RUN_TIME_LIMIT", "本轮时间预算已用完，保存结果下次继续")
        report["current_stage"] = stage
        report_progress(progress, "phase", stage=stage, message=stage)
        schema_text = assets[schema_name]
        schema = json.loads(schema_text)
        timeout_seconds = min(cg.generation_timeout_seconds, remaining)
        prepared = delivery = None
        if source is not None:
            delivery, prepared = _prepared_source(
                config, source, delivery_preparer=delivery_preparer, pipeline=pipeline
            )
            prompt = prompt(prepared)
        run_id = uuid.uuid4().hex[:16]
        if prepared is not None:
            workspace = stage_paper_workspace(
                prepared,
                run_id=run_id,
                root=runtime_dir(config),
                context={"role": role, "stage": stage,
                         "paper": _reading_prompt(prepared)},
                schema_text=schema_text,
            )
        else:
            workspace = stage_text_workspace(
                run_id=run_id,
                root=runtime_dir(config),
                context={"role": role, "stage": stage},
                schema_text=schema_text,
            )
        report["model_call_count"] += 1
        try:
            result = pipeline.runner.run(CardRunRequest(
                run_id=run_id, paper=prepared, prompt=prompt, output_schema=schema,
                workspace=workspace, timeout_seconds=timeout_seconds, role=role,
                model=cg.model, reasoning_effort=cg.reasoning_effort,
                reading_mode="file", progress=progress,
            ))
            if not result.ok:
                error = result.error
                raise core.ThemeError(
                    error.code if error else "THEME_MODEL_FAILED",
                    error.message if error else "主题步骤调用失败",
                    provider={"runner_id": result.runner_id,
                              **(dict(error.detail) if error and error.detail else {})},
                )
            if not isinstance(result.output, Mapping):
                raise core.ThemeError("THEME_TRANSPORT_INVALID", "运行器没有返回可保存的结果对象")
            payload = {
                "ok": True,
                "output": dict(result.output),
                "runner_id": result.runner_id,
                "usage": dict(result.usage) if result.usage else None,
                "configured_model": result.model or cg.model,
                "configured_reasoning_effort": result.reasoning_effort or cg.reasoning_effort,
                "warnings": list(result.warnings),
            }
            if prepared is not None:
                payload["source_access"] = _reading_access(prepared, payload["output"])
                if core._file_sha(delivery.pdf_path) != source["record"]["pdf_sha256"]:
                    raise core.ThemeError("THEME_INPUT_CHANGED", "原始 PDF 在处理期间改变，未接受结果")
            unchanged()
            shutil.rmtree(workspace, ignore_errors=True)
            return payload
        except Exception:
            # A failed stage keeps its staged material for diagnosis; the caller
            # records the blocker and the saved steps stay reusable.
            report["last_workspace"] = str(workspace)
            raise

    old_sources = {s["evidence_id"]: s for s in state["observed_sources"]}
    existing = []
    for tid, entry in state["themes"].items():
        directory = pool.root_path(config, entry["current"]["directory"])
        existing.append({"theme_id": tid, "title": entry["title"], "status": entry["status"],
            "predecessors": entry["predecessors"], "successors": entry["successors"],
            "revised_markdown": (directory / "revised.md").read_text(encoding="utf-8")})
    discovery_prompt = assets["discovery.md"] + "\n\n" + assets["pool-discovery.md"] + "\n\n输入材料：\n" + core._json({
        "research_goal": options.research_goal, "existing_themes": existing,
        "cards": [{"evidence_id": eid, "markdown": s["card"],
                   "changed": old_sources.get(eid) != s["record"]} for eid, s in sources.items()],
        "available_readings": [{"reading_id": r["reading_id"], "evidence_id": r["source"]["evidence_id"],
            "focus": r["focus"], "context": r["context"], "markdown": r["markdown"]}
            for r in catalog.values() if r["source"] == sources.get(r["source"]["evidence_id"], {}).get("record")]})
    discovery = core._result_record(change_dir / "discovery-result.json",
        {"protocol_version": pool.PROTOCOL, "base": core._digest(base), "input": binding},
        lambda: run_stage("统一主题池：跨文献关联与候选演化",
                          schema_name="pool-discovery.schema.json",
                          role="theme_discovery", prompt=discovery_prompt), report)
    actions = pool.plan_actions(discovery["output"], state, sources, change_id, catalog)
    unchanged()
    core._publish(change_dir / "plan.json", core._json(actions))
    core._publish(change_dir / "problem-clusters.md", discovery["output"]["problem_clusters_markdown"])
    saved = {}
    report["action_count"] = len(actions)
    for action in actions:
        for child in action["themes"]:
            tid = child["theme_id"]
            directory = pool.root_path(config, f"candidates/{tid}/versions/{change_id}")
            initial = "<!-- CANDIDATE_INITIAL; AI-generated -->\n" + child["candidate_markdown"]
            core._publish(directory / "initial.md", initial)
            core._publish(directory / "plan.json", core._json({"action": action["kind"],
                "predecessors": action["theme_ids"], "reason": action["reason"], "candidate": child}))
            item = {"theme_id": tid, "title": child["title"], "initial_path": str(directory / "initial.md"), "readings": []}
            report["themes"].append(item)
            refs, focused = [], []
            try:
                for task in child["paper_tasks"]:
                    source = sources[task["evidence_id"]]
                    reuse = task["reuse_reading_id"]
                    if reuse:
                        ref = {k: v for k, v in catalog[reuse].items() if k != "markdown"}
                        body = pool.check_reading(config, ref)
                        report["reused_reading_count"] += 1
                        report["reused_step_count"] += 1
                    else:
                        read_binding = {"protocol_version": pool.PROTOCOL, "source": source["record"],
                            "focus": task["focus"], "context": child["candidate_markdown"],
                            "model": cg.model, "reasoning_effort": cg.reasoning_effort,
                            "assets": {k: binding["assets"][k] for k in core.READING_ASSETS},
                            "converter": {"id": pipeline.converter.converter_id,
                                          "version": pipeline.converter.converter_version}}
                        read_dir = core._safe_path(source["pack"], "readings", "RD-" + core._digest(read_binding)[:24])
                        prompt = (lambda prepared, candidate=child["candidate_markdown"],
                                  focus=task["focus"], evidence_id=task["evidence_id"],
                                  rough_card=source["card"]: assets["focused-reading-markdown.md"]
                                  + "\n\n输入材料：\n" + core._json({
                                      "candidate": candidate, "focus": focus,
                                      "evidence_id": evidence_id, "rough_card": rough_card,
                                      "reading_parameters": _reading_prompt(prepared)}))
                        record = core._result_record(read_dir / "result.json", read_binding,
                            lambda: run_stage(f"定向精读 {tid} {task['evidence_id']}",
                                              schema_name="focused-reading-markdown.schema.json",
                                              role="focused_reading", prompt=prompt, source=source),
                            report)
                        ref = pool.reading_reference(config, read_dir, record, source["record"],
                                                     task["focus"], child["candidate_markdown"])
                        body = record["output"]["reading_markdown"]
                    refs.append(ref)
                    focused.append({"evidence_id": task["evidence_id"], "reading_id": ref["reading_id"],
                        "reading_markdown": body, "original_focus": ref["focus"], "current_focus": task["focus"],
                        "reuse_reason": task["reuse_reason"]})
                    item["readings"].append({"evidence_id": task["evidence_id"],
                                            "path": str(pool.reading_path(config, ref) / "reading.md")})
                parents = [e for e in existing if e["theme_id"] in action["theme_ids"]]
                revision_input = {"candidate": child, "research_goal": options.research_goal,
                    "focused_readings": focused, "previous_themes": parents,
                    "change_kind": action["kind"], "change_reason": action["reason"]}
                revision = core._result_record(directory / "revision-result.json",
                    {"protocol_version": pool.PROTOCOL, "input": revision_input},
                    lambda: run_stage(f"主题回填 {tid}", schema_name="refinement.schema.json",
                        role="theme_synthesis",
                        prompt=assets["refinement.md"] + "\n\n输入材料：\n" + core._json(revision_input)),
                    report)
                body = core._nonempty(revision["output"].get("revised_markdown"), "回填主题正文")
                unchanged()
                core._publish(directory / "revised.md", "<!-- CANDIDATE_REFINED; NOT CONFIRMED -->\n" + body
                              + _links(config, refs, directory))
                core._publish(directory / "manifest.json", core._json({"theme_id": tid, "status": pool.ACTIVE,
                    "formal_confirmation": None, "change_id": change_id, "reason": action["reason"],
                    "kind": action["kind"], "predecessors": action["theme_ids"], "readings": refs}))
                saved[tid] = {"directory": directory.relative_to(config.paths.themes_dir).as_posix(),
                    "hashes": pool.file_hashes(directory, ("initial.md", "revised.md", "plan.json", "manifest.json",
                                                         "revision-result.json")), "readings": refs}
                item.update(status=pool.ACTIVE, revised_path=str(directory / "revised.md"))
                report["updated_theme_count"] += 1
                report_progress(progress, "phase", message=f"{tid} 新版本已保存；等待本次变更完整提交")
            except (core.ThemeError, core.PdfDeliveryError, core.PdfGateError, core.ZoteroApiError) as exc:
                item.update(status="BLOCKED", error={"code": exc.code, "message": str(exc)})
                raise
    unchanged()
    next_state = pool.apply_actions(state, actions, saved, change_id, binding)
    pool.commit(config, base, next_state, change_dir)
    _summary(config, next_state, report)
    report["action"] = "EVOLVED" if actions else "NO_CHANGE_NEEDED"
