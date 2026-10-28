"""Step material for the file-based theme session protocol.

This is the lower half of :mod:`theme_session`: it defines what a step *is*
(discovery, one focused reading, one refinement), builds the request files an
agent reads, stages ``paper.md`` and its figures, and saves the artifacts under
the same paths and fingerprints the one-shot ``themes-run`` uses. The protocol
shell -- ``state.json``, ``prepare``/``finalize`` and the result envelopes --
lives in ``theme_session``.

Keeping the two halves apart means the prompt/binding definitions used by both
execution modes stay in one place: ``theme_pool_runner.run`` and this module
call the same helpers from ``theme_pool_runner``, so the same answer is stored
under the same fingerprint whichever executor produced it.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hydrolitagent.cards import theme_pool as pool
from hydrolitagent.cards import theme_pool_runner as runner_core
from hydrolitagent.cards import themes as core
from hydrolitagent.cards.domain.grounding import expected_canaries, verify_reading
from hydrolitagent.cards.domain.paper import (
    FIGURES_DIRNAME,
    MARKDOWN_FILENAME,
    PageAnchor,
)
from hydrolitagent.cards.domain.reading import GroundingError, ReadingReceipt
from hydrolitagent.cards.domain.source_access import MARKDOWN_PREPARED
from hydrolitagent.cards.pdf_delivery import prepare_pdf_delivery
from hydrolitagent.cards.publication import text_hash

SESSION_PROTOCOL = "theme-session-steps-v1"
STATE_SCHEMA_VERSION = 1
STATE_FILENAME = "state.json"
REQUEST_FILENAME = "request.json"
SCHEMA_FILENAME = "output.schema.json"
RESPONSE_FILENAME = "response.json"
INSTRUCTIONS_FILENAME = "README.md"
# Where the answer of a completed step is kept once finalize has accepted it.
# One file per step id makes "was this response already consumed?" unambiguous
# even when two steps legitimately produce byte-identical answers.
RESPONSES_DIRNAME = "responses"

KIND_DISCOVERY = "theme_discovery"
KIND_READING = "focused_reading"
KIND_REFINEMENT = "theme_refinement"

_ROLE = {
    KIND_DISCOVERY: "theme_discovery",
    KIND_READING: "focused_reading",
    KIND_REFINEMENT: "theme_synthesis",
}
_SCHEMA = {
    KIND_DISCOVERY: "pool-discovery.schema.json",
    KIND_READING: "focused-reading-markdown.schema.json",
    KIND_REFINEMENT: "refinement.schema.json",
}
_NEXT_ACTION = {
    KIND_DISCOVERY: (
        "阅读 request.json 的输入材料（来源粗卡、既有主题、可复用精读），按 "
        f"{SCHEMA_FILENAME} 写 {RESPONSE_FILENAME}：problem_clusters_markdown 与 actions。"
    ),
    KIND_READING: (
        "完整阅读本目录的 paper.md 与 figures/，按 "
        f"{SCHEMA_FILENAME} 写 {RESPONSE_FILENAME}：逐字引文放 source_locations，"
        "reading_receipt 回显 markdown_sha256 与全部 canary。"
    ),
    KIND_REFINEMENT: (
        "阅读 request.json 中的精读结果，按 "
        f"{SCHEMA_FILENAME} 写 {RESPONSE_FILENAME}：revised_markdown。"
    ),
}
_SESSION_RUNNER_ID = "in_session"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------------------
# Configuration-derived material (mirrors ``theme_pool_runner.run``)
# --------------------------------------------------------------------------------------


def _assets(config, options) -> dict[str, str]:
    root = options.assets_dir or config.paths.templates_dir / "themes"
    assets = {name: (root / name).read_text(encoding="utf-8")
              for name in core.PIPELINE_ASSETS}
    for name in core.PIPELINE_ASSETS:
        if name.endswith(".json"):
            json.loads(assets[name])
    return assets


def _card_generation(config, options):
    """The model choice a step records, with the theme-pipeline override applied."""

    return replace(
        config.card_generator,
        model=options.model or config.card_generator.model,
        reasoning_effort=options.reasoning_effort or config.card_generator.reasoning_effort,
        generation_timeout_seconds=(options.timeout_seconds
                                    or config.card_generator.generation_timeout_seconds),
    )


def _binding(config, options, sources, assets) -> dict[str, Any]:
    cg = _card_generation(config, options)
    return {
        "protocol_version": pool.PROTOCOL,
        "group_id": config.zotero.group_id,
        "research_goal": options.research_goal,
        "sources": [s["record"] for s in sources.values()],
        "model": cg.model,
        "reasoning_effort": cg.reasoning_effort,
        "assets": {k: text_hash(v) for k, v in assets.items()},
    }


def _conversion_pipeline(config, pipeline):
    if pipeline is not None:
        return pipeline
    from hydrolitagent.cards.composition import build_session_pipeline

    return build_session_pipeline(config)


# --------------------------------------------------------------------------------------
# Step vocabulary
# --------------------------------------------------------------------------------------


def _step(kind: str, **extra) -> dict[str, Any]:
    if kind == KIND_DISCOVERY:
        step_id = "discovery"
    elif kind == KIND_READING:
        step_id = f"reading:{extra['theme_id']}:{extra['evidence_id']}"
    elif kind == KIND_REFINEMENT:
        step_id = f"refinement:{extra['theme_id']}"
    else:  # pragma: no cover - internal misuse
        raise ValueError(f"未知主题步骤：{kind}")
    return {"id": step_id, "kind": kind, "role": _ROLE[kind], "schema": _SCHEMA[kind], **extra}


def _discovery_step() -> dict[str, Any]:
    return _step(KIND_DISCOVERY)


def _steps_from_plan(plan) -> list[dict[str, Any]]:
    """The full step list after discovery: readings first, then one refinement."""

    steps: list[dict[str, Any]] = []
    for action in plan:
        for child in action["themes"]:
            tid = child["theme_id"]
            for task in child["paper_tasks"]:
                if task.get("reuse_reading_id"):
                    # A saved reading is reused as-is: no model step, no re-read.
                    continue
                steps.append(_step(KIND_READING, theme_id=tid,
                                   evidence_id=task["evidence_id"],
                                   focus=task["focus"], title=child["title"]))
            steps.append(_step(KIND_REFINEMENT, theme_id=tid, title=child["title"]))
    return steps


def _current_step(session) -> dict[str, Any]:
    for step in session.get("steps", []):
        if step["id"] == session.get("step"):
            return step
    raise core.ThemeError(
        "THEME_SESSION_STATE_INVALID",
        "state.json 指向的步骤不在步骤清单中；请重新运行 cards run prepare --theme",
    )


def _step_index(session, step) -> int:
    for index, candidate in enumerate(session.get("steps", [])):
        if candidate["id"] == step["id"]:
            return index
    return 0


def _remaining_steps(session, step) -> list[str]:
    ids = [item["id"] for item in session.get("steps", [])]
    try:
        return ids[ids.index(step["id"]) + 1:]
    except ValueError:
        return []


def _next_step(session) -> dict[str, Any] | None:
    completed = set(session.get("completed") or ())
    for step in session.get("steps", []):
        if step["id"] not in completed:
            return step
    return None


# --------------------------------------------------------------------------------------
# Run-directory files
# --------------------------------------------------------------------------------------


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise core.ThemeError(
            "THEME_SESSION_STATE_INVALID", f"{Path(path).name} 不是有效 JSON"
        ) from exc


def _read_request(run_dir) -> dict[str, Any] | None:
    path = Path(run_dir) / REQUEST_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _common_payload(session, step) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_protocol": SESSION_PROTOCOL,
        "protocol_version": pool.PROTOCOL,
        "run_id": session["run_id"],
        "change_id": session["change_id"],
        "step": step["id"],
        "step_kind": step["kind"],
        "step_index": _step_index(session, step),
        "remaining_steps": _remaining_steps(session, step),
        "steps_known": bool(session.get("steps_known")),
        "role": step["role"],
        "output_schema_file": SCHEMA_FILENAME,
        "response_file": RESPONSE_FILENAME,
        "next_action": _NEXT_ACTION[step["kind"]],
        "model": session.get("model"),
        "reasoning_effort": session.get("reasoning_effort"),
        "timeout_seconds": session.get("timeout_seconds"),
    }


def _instructions(run_dir, session, step) -> str:
    lines = [
        f"# 主题池分步任务：{step['kind']}",
        "",
        "这个目录由 `hydrolitagent cards run prepare --theme` 生成。平台**不会**调用模型，"
        "也不读取 PDF；本步骤的全部材料都在这个目录里。",
        "",
        "## 本步要做的事",
        "",
        f"1. {_NEXT_ACTION[step['kind']]}",
        f"2. 答案文件固定为 `{RESPONSE_FILENAME}`，放在本目录。",
        "",
        "## 约束",
        "",
        "- 不要修改 `paper.md` 或 `request.json`；平台会复核 Markdown 哈希。",
        "- 答案只按 `output.schema.json` 生成 JSON 对象，不要附加解释性正文。",
        "- finalize 通过后会把这个答案归档到 `responses/` 并移走 `response.json`；"
        "下一步要重新写一份 `response.json`。",
        "- `verified` 只表示程序检查通过，不等于科研结论正确。",
        "",
        "完成后由操作者执行：",
        "",
        "```text",
        f"uv run hydrolitagent cards run finalize --theme --run-dir {Path(run_dir)} --json",
        "```",
        "",
        f"当前步骤：`{step['id']}`（第 {_step_index(session, step) + 1} 步）；"
        f"后续步骤：{len(_remaining_steps(session, step))} 个。",
        "",
    ]
    return "\n".join(lines)


def _write_request(run_dir, session, step, payload, assets) -> None:
    run_dir = Path(run_dir)
    _write_text(run_dir / REQUEST_FILENAME, core._json(payload))
    _write_text(run_dir / SCHEMA_FILENAME, assets[step["schema"]])
    _write_text(run_dir / INSTRUCTIONS_FILENAME, _instructions(run_dir, session, step))


# --------------------------------------------------------------------------------------
# Step material
# --------------------------------------------------------------------------------------


def _anchor_payload(anchor: PageAnchor) -> dict[str, Any]:
    return {
        "page": anchor.page,
        "char_start": anchor.char_start,
        "char_end": anchor.char_end,
        "heading": anchor.heading,
        "role": anchor.role,
        "canary": anchor.canary,
    }


def _anchors_from(payload) -> tuple[PageAnchor, ...]:
    anchors = []
    for item in payload or ():
        anchors.append(PageAnchor(
            page=item["page"],
            char_start=item["char_start"],
            char_end=item["char_end"],
            heading=item.get("heading"),
            role=item.get("role", "unknown"),
            canary=item.get("canary"),
        ))
    return tuple(anchors)


def _anchors_for(request) -> tuple[PageAnchor, ...]:
    anchors = _anchors_from(request.get("page_anchors"))
    if not anchors:
        raise core.ThemeError("THEME_SESSION_STATE_INVALID",
                              "request.json 缺少页锚点；请重新运行 prepare")
    return anchors


def _stage_paper(run_dir, prepared) -> None:
    """Copy the prepared Markdown and figures into the agent's directory."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = run_dir / MARKDOWN_FILENAME
    source_text = prepared.markdown_path.read_text(encoding="utf-8")
    changed = (not markdown_path.is_file()
               or markdown_path.read_text(encoding="utf-8") != source_text)
    if changed:
        shutil.copyfile(prepared.markdown_path, markdown_path)
        figures_dir = run_dir / FIGURES_DIRNAME
        if figures_dir.is_dir():
            # Figures belong to one paper: never leave a previous step's images
            # beside a different paper.md.
            shutil.rmtree(figures_dir)
    if text_hash(markdown_path.read_text(encoding="utf-8")) != prepared.markdown_sha256:
        raise core.ThemeError("MARKDOWN_SOURCE_INVALID", "写入运行目录后的 paper.md 与转换结果不一致")
    figures_dir = run_dir / FIGURES_DIRNAME
    for figure in prepared.figures:
        target = figures_dir / figure.path.name
        if not target.is_file() or target.read_bytes() != figure.path.read_bytes():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(figure.path, target)


def _find_child(session, theme_id):
    for action in session.get("plan") or ():
        for child in action["themes"]:
            if child["theme_id"] == theme_id:
                return action, child
    raise core.ThemeError("THEME_SESSION_STATE_INVALID", "步骤指向的主题不在此次变更计划中")


def _focused_readings(config, session, action, child, context):
    """``(focused, refs)`` -- the material and pool references, in run()'s order."""

    focused, refs = [], []
    for task in child["paper_tasks"]:
        eid = task["evidence_id"]
        reuse = task.get("reuse_reading_id")
        if reuse:
            # Reuse is pool data, not a new step: the saved reading is re-read
            # through the pool's own validator so a stale record cannot pass.
            ref = {k: v for k, v in context.catalog[reuse].items() if k != "markdown"}
            body = pool.check_reading(config, ref)
        else:
            ref = (session.get("reading_refs") or {}).get(f"reading:{child['theme_id']}:{eid}")
            if ref is None:
                raise core.ThemeError(
                    "THEME_SESSION_STATE_INVALID", "精读步骤尚未完成，不能回填主题",
                    evidence_id=eid,
                )
            body = _saved_result(config, ref)["output"]["reading_markdown"]
        refs.append(ref)
        focused.append({
            "evidence_id": eid,
            "reading_id": ref["reading_id"],
            "reading_markdown": body,
            "original_focus": ref["focus"],
            "current_focus": task["focus"],
            "reuse_reason": task.get("reuse_reason"),
        })
    return focused, refs


def _build_request(config, run_dir, session, step, context, pipeline, delivery_preparer):
    payload = _common_payload(session, step)
    if step["kind"] == KIND_DISCOVERY:
        material = runner_core.discovery_input(
            config, context.options, context.state, context.sources, context.catalog)
        payload.update(
            prompt=runner_core.discovery_prompt(context.assets, material),
            input=material,
            binding={"protocol_version": pool.PROTOCOL,
                     "base": core._digest(context.base), "input": context.binding},
        )
        return payload

    action, child = _find_child(session, step["theme_id"])
    if step["kind"] == KIND_REFINEMENT:
        focused, refs = _focused_readings(config, session, action, child, context)
        material = runner_core.refinement_input(
            context.options, action, child, focused,
            runner_core.existing_themes(config, context.state))
        payload.update(
            prompt=context.assets["refinement.md"] + "\n\n输入材料：\n" + core._json(material),
            input=material,
            binding={"protocol_version": pool.PROTOCOL, "input": material},
            theme_id=step["theme_id"],
            readings=refs,
        )
        return payload

    source = context.sources[step["evidence_id"]]
    built = _conversion_pipeline(config, pipeline)
    _, prepared = runner_core._prepared_source(
        config, source,
        delivery_preparer=delivery_preparer or prepare_pdf_delivery,
        pipeline=built,
    )
    read_binding = runner_core.reading_binding(
        asset_hashes=context.binding["assets"], source=source, focus=step["focus"],
        candidate=child["candidate_markdown"], model=context.cg.model,
        reasoning_effort=context.cg.reasoning_effort, converter=built.converter,
    )
    read_dir = core._safe_path(source["pack"], "readings",
                               "RD-" + core._digest(read_binding)[:24])
    _stage_paper(run_dir, prepared)
    payload.update(
        prompt=runner_core.reading_prompt(
            context.assets, candidate=child["candidate_markdown"], focus=step["focus"],
            evidence_id=step["evidence_id"], rough_card=source["card"],
            reading_parameters=runner_core._reading_prompt(prepared)),
        binding=read_binding,
        theme_id=step["theme_id"],
        evidence_id=step["evidence_id"],
        focus=step["focus"],
        candidate=child["candidate_markdown"],
        reading_directory=read_dir.name,
        markdown_file=MARKDOWN_FILENAME,
        markdown_sha256=prepared.markdown_sha256,
        source_pdf_sha256=prepared.source.pdf_sha256,
        parent_key=prepared.source.parent_key,
        page_count=prepared.page_count,
        converter_id=prepared.converter_id,
        converter_version=prepared.converter_version,
        reading_canaries=list(expected_canaries(
            prepared.markdown_path.read_text(encoding="utf-8"))),
        page_anchors=[_anchor_payload(anchor) for anchor in prepared.page_anchors],
        figures=[{"figure_id": figure.figure_id, "page": figure.page,
                  "file": f"{FIGURES_DIRNAME}/{figure.path.name}",
                  "caption": figure.caption} for figure in prepared.figures],
    )
    return payload


def _stage_ready(run_dir, step, request) -> bool:
    """True when the existing request already describes this step and its material."""

    if request.get("step") != step["id"] or request.get("step_kind") != step["kind"]:
        return False
    if step["kind"] != KIND_READING:
        return True
    markdown_path = Path(run_dir) / MARKDOWN_FILENAME
    if not markdown_path.is_file():
        return False
    return text_hash(markdown_path.read_text(encoding="utf-8")) == request.get("markdown_sha256")


def _write_step(config, run_dir, session, step, context, pipeline, delivery_preparer) -> dict[str, Any]:
    run_dir = Path(run_dir)
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise core.ThemeError("THEME_SESSION_RUN_DIR_INVALID",
                              f"无法创建运行目录：{exc}") from exc
    if not run_dir.is_dir():
        raise core.ThemeError("THEME_SESSION_RUN_DIR_INVALID", "run-dir 已被同名文件占用，无法写入")
    request = _read_request(run_dir)
    if request is not None and _stage_ready(run_dir, step, request):
        payload = request
    else:
        payload = _build_request(config, run_dir, session, step, context,
                                 pipeline, delivery_preparer)
    if payload.get("step") != step["id"]:
        raise core.ThemeError("THEME_SESSION_STATE_INVALID", "request.json 与当前步骤不一致")
    _write_request(run_dir, session, step, payload, context.assets)
    return payload


# --------------------------------------------------------------------------------------
# Saved steps
# --------------------------------------------------------------------------------------


def _existing_record(path: Path, binding) -> dict[str, Any] | None:
    """Load a saved step if it exists; a mismatch is a conflict, not a rerun."""

    if not path.exists():
        return None
    wrapper = _read_json(path)
    record = wrapper.get("record") if isinstance(wrapper, dict) else None
    if (not isinstance(record, dict) or core._digest(record) != wrapper.get("sha256")
            or record.get("binding") != binding):
        raise core.ThemeError(
            "THEME_CHECKPOINT_CONFLICT", "步骤记录与输入或指纹不符；未重跑",
            path=str(path),
        )
    return record


def _write_record(path: Path, binding, output, execution) -> dict[str, Any]:
    record = {"protocol_version": pool.PROTOCOL, "binding": binding, "output": output,
              "created_at": _now(), "execution": execution,
              "scientific_correctness_verified": False}
    core._publish(path, core._json({"record": record, "sha256": core._digest(record)}))
    return record


def _execution(context, *, source_access=None) -> dict[str, Any]:
    execution = {
        "runner_id": _SESSION_RUNNER_ID,
        "model": context.cg.model,
        "reasoning_effort": context.cg.reasoning_effort,
        "warnings": [],
        "model_invoked": False,
    }
    if source_access is not None:
        execution["source_access"] = source_access
    return execution


def _saved_result(config, ref) -> dict[str, Any]:
    """The record behind one saved reading, re-read from its own directory."""

    directory = pool.reading_path(config, ref)
    wrapper = _read_json(directory / "result.json")
    record = wrapper.get("record") if isinstance(wrapper, dict) else None
    if (not isinstance(record, dict) or core._digest(record) != wrapper.get("sha256")
            or ref.get("result_sha256") != core._digest(record)):
        raise core.ThemeError("THEME_CHECKPOINT_CONFLICT", "精读记录与引用不符；未重跑",
                              path=str(directory / "result.json"))
    return record


# --------------------------------------------------------------------------------------
# Context
# --------------------------------------------------------------------------------------


class _Context:
    """Everything one prepare/finalize call derives from configuration and disk."""

    __slots__ = ("sources", "source_report", "options", "assets", "cg", "binding",
                 "state", "base", "catalog", "change_id", "change_dir")

    def __init__(self, **values) -> None:
        for name in self.__slots__:
            setattr(self, name, values[name])


def _open_context(config, literature_root, *, migrate_imports):
    """Collect sources, load (and optionally migrate) the pool, derive the change id.

    ``migrate_imports`` is true only for ``prepare``: importing completed legacy
    batches is a write, and finalize must not write anything before an answer
    has been accepted.
    """

    sources, source_report = core._collect_sources(config, literature_root)
    if not sources:
        return None, source_report, 0
    options = config.theme_pipeline
    assets = _assets(config, options)
    cg = _card_generation(config, options)
    binding = _binding(config, options, sources, assets)
    state, imported = pool.migrate(config, binding, apply=migrate_imports)
    pool.check_index(config, state)
    base = pool.load(config)
    change_id = "CHANGE-" + core._digest({"base": base, "input": binding})[:24]
    return _Context(sources=sources, source_report=source_report, options=options,
                    assets=assets, cg=cg, binding=binding, state=state, base=base,
                    catalog=pool.reading_catalog(config, state),
                    change_id=change_id,
                    change_dir=pool.root_path(config, "changes/" + change_id)), source_report, imported


def _reopen_context(config, session, literature_root):
    """Re-derive the context and refuse to mix steps from different inputs/pools."""

    sources, source_report = core._collect_sources(config, literature_root)
    options = config.theme_pipeline
    assets = _assets(config, options)
    cg = _card_generation(config, options)
    binding = _binding(config, options, sources, assets)
    if core._digest(binding) != session.get("binding_digest"):
        raise core.ThemeError(
            "THEME_INPUT_CHANGED",
            "来源、主题资产或模型配置与准备时不同；不混用新旧步骤",
        )
    if [s["record"] for s in sources.values()] != session.get("sources"):
        raise core.ThemeError("THEME_INPUT_CHANGED", "来源集合与准备时不同；不混用新旧步骤")
    core._assert_sources(sources, config)
    state, _ = pool.migrate(config, binding, apply=False)
    pool.check_index(config, state)
    base = pool.load(config)
    if core._digest(base) != session.get("base_digest"):
        raise core.ThemeError("THEME_POOL_CHANGED", "处理期间主题池发生变化；保留结果、不覆盖")
    return _Context(sources=sources, source_report=source_report, options=options,
                    assets=assets, cg=cg, binding=binding, state=state, base=base,
                    catalog=pool.reading_catalog(config, state),
                    change_id=session["change_id"],
                    change_dir=pool.root_path(config, "changes/" + session["change_id"]))


# --------------------------------------------------------------------------------------
# finalize
# --------------------------------------------------------------------------------------


def _save_discovery(config, session, context, request, output) -> list[dict[str, Any]]:
    path = context.change_dir / "discovery-result.json"
    binding = request["binding"]
    record = _existing_record(path, binding)
    if record is None:
        # Route validation precedes publication: an invalid answer never leaves a
        # checkpoint that would shadow the corrected one.
        actions = pool.plan_actions(output, context.state, context.sources,
                                    session["change_id"], context.catalog)
        record = _write_record(path, binding, output, _execution(context))
    else:
        actions = pool.plan_actions(record["output"], context.state, context.sources,
                                    session["change_id"], context.catalog)
    core._publish(context.change_dir / "plan.json", core._json(actions))
    core._publish(context.change_dir / "problem-clusters.md",
                  record["output"]["problem_clusters_markdown"])
    for action in actions:
        for child in action["themes"]:
            directory = pool.root_path(
                config, f"candidates/{child['theme_id']}/versions/{session['change_id']}")
            initial = "<!-- CANDIDATE_INITIAL; AI-generated -->\n" + child["candidate_markdown"]
            core._publish(directory / "initial.md", initial)
            core._publish(directory / "plan.json", core._json({
                "action": action["kind"], "predecessors": action["theme_ids"],
                "reason": action["reason"], "candidate": child}))
    return actions


def _save_reading(config, run_dir, session, context, step, request, output) -> dict[str, Any]:
    markdown_path = Path(run_dir) / MARKDOWN_FILENAME
    if not markdown_path.is_file():
        raise core.ThemeError("MARKDOWN_SOURCE_INVALID",
                              "运行目录缺少 paper.md；请重新运行 cards run prepare --theme")
    markdown = markdown_path.read_text(encoding="utf-8")
    if text_hash(markdown) != request.get("markdown_sha256"):
        raise core.ThemeError("MARKDOWN_CHANGED", "运行目录中的 paper.md 已被改动；重新 prepare 后再收口")
    source = context.sources[step["evidence_id"]]
    read_dir = core._safe_path(source["pack"], "readings", request["reading_directory"])
    record_path = read_dir / "result.json"
    record = _existing_record(record_path, request["binding"])
    if record is None:
        declared = output.get("source_page_count")
        expected_pages = request.get("page_count")
        if declared is not None and declared != expected_pages:
            raise core.ThemeError("THEME_READING_PAGE_COUNT_MISMATCH",
                                  "模型页数与已转换 Markdown 的页锚点数不一致",
                                  declared=declared, actual=expected_pages)
        try:
            reading = verify_reading(ReadingReceipt.from_output(output), markdown,
                                     _anchors_for(request))
        except GroundingError as exc:
            raise core.ThemeError(exc.code, str(exc), diagnostic=dict(exc.detail)) from exc
        if not reading.verified:
            raise core.ThemeError("THEME_READING_NOT_VERIFIED",
                                  "定向精读的引文覆盖率不足，未作为主题证据保存",
                                  reading=reading.as_dict())
        access = {
            "method": MARKDOWN_PREPARED,
            "source_pdf_sha256": request["source_pdf_sha256"],
            "markdown_sha256": request["markdown_sha256"],
            "parent_key": request["parent_key"],
            "page_count": request["page_count"],
            "converter_id": request["converter_id"],
            "converter_version": request["converter_version"],
            "reading": reading.as_dict(),
        }
        record = _write_record(record_path, request["binding"], output,
                               _execution(context, source_access=access))
    return pool.reading_reference(config, read_dir, record, source["record"],
                                  step["focus"], request["candidate"])


def _save_refinement(config, session, context, step, request, output) -> list[dict[str, Any]]:
    action, child = _find_child(session, step["theme_id"])
    _, refs = _focused_readings(config, session, action, child, context)
    directory = pool.root_path(
        config, f"candidates/{step['theme_id']}/versions/{session['change_id']}")
    binding = request["binding"]
    record = _existing_record(directory / "revision-result.json", binding)
    if record is None:
        # Non-empty body is part of the publication gate, not a post-hoc check.
        core._nonempty(output.get("revised_markdown"), "回填主题正文")
        record = _write_record(directory / "revision-result.json", binding, output,
                               _execution(context))
    body = core._nonempty(record["output"].get("revised_markdown"), "回填主题正文")
    core._publish(directory / "revised.md",
                  "<!-- CANDIDATE_REFINED; NOT CONFIRMED -->\n" + body
                  + runner_core._links(config, refs, directory,
                                       session.get("literature_root")))
    core._publish(directory / "manifest.json", core._json({
        "theme_id": step["theme_id"], "status": pool.ACTIVE, "formal_confirmation": None,
        "change_id": session["change_id"], "reason": action["reason"],
        "kind": action["kind"], "predecessors": action["theme_ids"], "readings": refs}))
    return refs


def _commit(config, session, context) -> dict[str, Any]:
    """Apply the planned actions and publish the registry."""

    saved: dict[str, Any] = {}
    reused = 0
    plan = session.get("plan") or []
    for action in plan:
        for child in action["themes"]:
            tid = child["theme_id"]
            _, refs = _focused_readings(config, session, action, child, context)
            reused += sum(1 for task in child["paper_tasks"] if task.get("reuse_reading_id"))
            directory = pool.root_path(
                config, f"candidates/{tid}/versions/{session['change_id']}")
            saved[tid] = {
                "directory": directory.relative_to(config.paths.themes_dir).as_posix(),
                "hashes": pool.file_hashes(directory, (
                    "initial.md", "revised.md", "plan.json", "manifest.json",
                    "revision-result.json")),
                "readings": refs,
            }
    next_state = pool.apply_actions(context.state, plan, saved,
                                    session["change_id"], context.binding)
    pool.commit(config, context.base, next_state, context.change_dir)
    summary: dict[str, Any] = {}
    runner_core._summary(config, next_state, summary)
    return {
        "themes": summary["themes"],
        "candidate_count": summary["candidate_count"],
        "refined_count": summary["refined_count"],
        "retired_count": summary["retired_count"],
        "updated_theme_count": len(saved),
        "reused_reading_count": reused,
        "action": "EVOLVED" if plan else "NO_CHANGE_NEEDED",
        "pool_status": summary["status"],
    }
