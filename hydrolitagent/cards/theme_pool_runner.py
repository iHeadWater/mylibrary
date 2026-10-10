"""One global knowledge pool, incremental candidate evolution and reading reuse."""
from __future__ import annotations

from dataclasses import replace

from hydrolitagent.cards import themes as core
from hydrolitagent.cards import theme_pool as pool
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


def run(config, report, *, progress, text_adapter, pdf_adapter, delivery_preparer, remaining_seconds):
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
    assets = {name: (assets_root / name).read_text(encoding="utf-8") for name in core.ASSETS}
    for name in core.ASSETS:
        if name.endswith(".json"):
            core.json.loads(assets[name])
    cg = replace(config.card_generator, model=options.model or config.card_generator.model,
        reasoning_effort=options.reasoning_effort or config.card_generator.reasoning_effort,
        generation_timeout_seconds=options.timeout_seconds or config.card_generator.generation_timeout_seconds)
    if cg.adapter != "codex_cli" or cg.pdf_reader.adapter != "local_path":
        raise core.ThemeError("THEME_ADAPTER_UNSUPPORTED", "统一主题池目前需要codex_cli + local_path")
    if cg.pdf_direct_trial is None or cg.pdf_direct_trial.reading_prompt_file is None:
        raise core.ThemeError("THEME_READING_CONFIG_MISSING", "缺少本地PDF阅读配置")
    binding = {"protocol_version": pool.PROTOCOL, "group_id": config.zotero.group_id,
        "research_goal": options.research_goal, "sources": [s["record"] for s in sources.values()],
        "model": cg.model, "reasoning_effort": cg.reasoning_effort,
        "assets": {k: text_hash(v) for k, v in assets.items()},
        "pdf_reading_prompt_sha256": text_hash(cg.pdf_direct_trial.reading_prompt_file.read_text(encoding="utf-8"))}
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
    base = pool.load(config)  # None for a completely new, uninitialized pool.
    catalog = pool.reading_catalog(config, state)
    change_id = "CHANGE-" + core._digest({"base": base, "input": binding})[:24]
    change_dir = pool.root_path(config, "changes/" + change_id)
    report.update(change_id=change_id, change_path=str(change_dir))
    core._publish(change_dir / "inputs.json", core._json({"base_registry": base, "input": binding}))
    text_adapter = text_adapter or core.CodexTextAdapter(cg, progress=progress)
    pdf_adapter = pdf_adapter or core.CodexLocalPdfAdapter(cg, progress=progress)

    def unchanged():
        core._assert_sources(sources)
        if pool.load(config) != base:
            raise core.ThemeError("THEME_POOL_CHANGED", "处理中主题池发生变化，保留结果、不覆盖")
        pool.check_index(config, state)

    def invoke(stage, prompt, schema, source=None):
        unchanged()
        remaining = remaining_seconds()
        if remaining < 1:
            raise core.ThemeError("RUN_TIME_LIMIT", "本轮时间预算已用完，保存结果下次继续")
        report["current_stage"] = stage
        report_progress(progress, "phase", stage=stage, message=stage)
        kwargs = {"output_schema_path": assets_root / schema,
                  "timeout_seconds": min(cg.generation_timeout_seconds, remaining), "run_label": stage}
        if source is None:
            report["model_call_count"] += 1
            result = text_adapter.generate(prompt, **kwargs)
        else:
            identity = source["record"]
            delivery = delivery_preparer(config.zotero, config.pdf_gate, config.tasks,
                config.paths.tasks_file, config.paths.lock_file, config.paths.evidence_packs_dir,
                identity["parent_key"], allow_trial_states=True)
            if (delivery.pdf_sha256 != identity["pdf_sha256"] or delivery.parent_key != identity["parent_key"]
                    or delivery.group_id != identity["group_id"] or delivery.attachment_key != identity["attachment_key"]
                    or core._file_sha(delivery.pdf_path) != identity["pdf_sha256"]):
                raise core.ThemeError("THEME_PDF_MISMATCH", "原始PDF与证据包身份不符，未调用模型")
            report["model_call_count"] += 1
            result = pdf_adapter.generate(prompt, working_directory=delivery.pdf_path.parent,
                source_pdf_path=delivery.pdf_path, zotero_parent_key=identity["parent_key"], **kwargs)
            if core._file_sha(delivery.pdf_path) != identity["pdf_sha256"]:
                raise core.ThemeError("THEME_INPUT_CHANGED", "原始PDF在处理期间改变，未接受结果")
        unchanged()
        return result

    old_sources = {s["evidence_id"]: s for s in state["observed_sources"]}
    existing = []
    for tid, entry in state["themes"].items():
        directory = pool.root_path(config, entry["current"]["directory"])
        existing.append({"theme_id": tid, "title": entry["title"], "status": entry["status"],
            "predecessors": entry["predecessors"], "successors": entry["successors"],
            "revised_markdown": (directory / "revised.md").read_text(encoding="utf-8")})
    prompt = assets["discovery.md"] + "\n\n" + assets["pool-discovery.md"] + "\n\n输入材料：\n" + core._json({
        "research_goal": options.research_goal, "existing_themes": existing,
        "cards": [{"evidence_id": eid, "markdown": s["card"],
                   "changed": old_sources.get(eid) != s["record"]} for eid, s in sources.items()],
        "available_readings": [{"reading_id": r["reading_id"], "evidence_id": r["source"]["evidence_id"],
            "focus": r["focus"], "context": r["context"], "markdown": r["markdown"]}
            for r in catalog.values() if r["source"] == sources.get(r["source"]["evidence_id"], {}).get("record")]})
    discovery = core._result_record(change_dir / "discovery-result.json",
        {"protocol_version": pool.PROTOCOL, "base": core._digest(base), "input": binding},
        lambda: invoke("统一主题池：跨文献关联与候选演化", prompt, "pool-discovery.schema.json"), report)
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
                            "assets": {k: binding["assets"][k] for k in ("focused-reading.md", "focused-reading.schema.json")},
                            "pdf_reading_prompt_sha256": binding["pdf_reading_prompt_sha256"]}
                        read_dir = core._safe_path(source["pack"], "readings", "RD-" + core._digest(read_binding)[:24])
                        prompt = assets["focused-reading.md"] + "\n\n输入材料：\n" + core._json({
                            "candidate": child["candidate_markdown"], "focus": task["focus"],
                            "evidence_id": task["evidence_id"], "rough_card": source["card"]})
                        record = core._result_record(read_dir / "result.json", read_binding,
                            lambda: invoke(f"定向精读 {tid} {task['evidence_id']}", prompt, "focused-reading.schema.json", source), report)
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
                    lambda: invoke(f"主题回填 {tid}", assets["refinement.md"] + "\n\n输入材料：\n"
                        + core._json(revision_input), "refinement.schema.json"), report)
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
