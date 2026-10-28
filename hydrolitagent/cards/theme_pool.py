"""Persistent candidate identities and immutable revisions, independent of runs.

The registry is the single publication point. Failed work stays in changes/ and
cannot retire a parent until every replacement has been saved successfully.
"""
from __future__ import annotations

import copy
import html
import json
import re
from pathlib import Path

from hydrolitagent.cards import themes as core
from hydrolitagent.cards.domain.source_access import (
    LOCAL_PDF_PATH,
    MARKDOWN_PREPARED,
    is_accepted_method,
    source_access_acceptable,
)
from hydrolitagent.cards.publication import atomic_text, text_hash

PROTOCOL = "unified-theme-pool-v1"
ACTIVE = "CANDIDATE_REFINED"
RETIRED = "SUPERSEDED"


def _fail(code, message, **details):
    raise core.ThemeError(code, message, **details)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _wrap(record):
    return {"record": record, "sha256": core._digest(record)}


def _unwrap(path):
    wrapped = _read(path)
    record = wrapped["record"]
    if core._digest(record) != wrapped["sha256"]:
        _fail("THEME_POOL_CONFLICT", "共享记录指纹不符；保留文件，不重新生成", path=str(path))
    return record


def root_path(config, value):
    if not isinstance(value, str) or Path(value).is_absolute() or ".." in Path(value).parts:
        _fail("THEME_POOL_PATH_INVALID", "主题池中的相对路径无效")
    return core._safe_path(config.paths.themes_dir, value)


def reading_path(config, reference):
    if reference.get("root") != "evidence_packs":
        _fail("THEME_READING_REFERENCE_INVALID", "精读引用必须属于统一证据包")
    value = reference["directory"]
    if not isinstance(value, str) or Path(value).is_absolute() or ".." in Path(value).parts:
        _fail("THEME_POOL_PATH_INVALID", "精读目录必须是证据包内的相对路径")
    return core._safe_path(config.paths.evidence_packs_dir, value)


def file_hashes(directory, names):
    return {name: text_hash((directory / name).read_text(encoding="utf-8")) for name in names}


def check_files(directory, hashes):
    for name, expected in hashes.items():
        if name not in {"initial.md", "revised.md", "plan.json", "manifest.json",
                        "revision-result.json", "reading.md", "result.json"}:
            _fail("THEME_POOL_PATH_INVALID", "共享记录包含未知文件名")
        path = core._safe_path(directory, name)
        if not path.is_file() or text_hash(path.read_text(encoding="utf-8")) != expected:
            _fail("THEME_FILE_CONFLICT", "已有主题或精读被修改/缺失；不覆盖、不重跑", path=str(path))


def validate_reading(record, source):
    """Accept a Markdown-grounded reading or a historical PDF-reading record.

    New readings carry ``method=markdown_prepared`` with a program-computed
    ``reading`` block; legacy records carry ``method=local_pdf_path`` with the
    old process flags. Both are validated, but a new artifact is never written
    with a legacy method. The on-disk shape of an old record is not rewritten:
    the theme pool's hashes depend on those bytes.
    """

    body = core._nonempty(record["output"].get("reading_markdown"), "定向精读正文")
    access = record["execution"].get("source_access") or {}
    method = access.get("method")
    if not is_accepted_method(method, policy="current"):
        _fail("THEME_READING_PROCESS_INVALID", "精读缺少可识别的来源阅读记录")
    if method == MARKDOWN_PREPARED:
        # One owner for the receipt contract: the same check the single-paper
        # card path applies, bound to this source's PDF and parent key.
        if not source_access_acceptable(
                access, expected_sha256=source["pdf_sha256"],
                expected_parent_key=source["parent_key"]):
            _fail("THEME_READING_PROCESS_INVALID", "精读缺少与论文匹配的 Markdown 接地记录")
    elif (record["execution"].get("ephemeral") is not True
            or access.get("source_sha256") != source["pdf_sha256"]
            or access.get("parent_key") != source["parent_key"]
            or access.get("method") != LOCAL_PDF_PATH
            or access.get("source_identity_verified") is not True
            or access.get("source_unchanged") is not True
            or access.get("model_reading_report_accepted") is not True):
        _fail("THEME_READING_PROCESS_INVALID", "精读缺少匹配原始PDF的流程记录")
    if record["binding"].get("source") != source:
        _fail("THEME_READING_REFERENCE_INVALID", "精读输入来源与引用不一致")
    return body


def normalize_reading_markdown(text):
    """Turn an escaped line break into a real one.

    A runner that JSON-encodes its Markdown twice returns ``\\\\n`` (two
    backslashes and an ``n``) where the artifact needs a newline. Only that
    doubled form is rewritten: LaTeX commands (``\\\\nabla``) and single
    backslash escapes stay exactly as the model wrote them.
    """

    return text.replace("\\\\r\\\\n", "\n").replace("\\\\n", "\n")


def reading_reference(config, directory, record, source, focus, context):
    body = normalize_reading_markdown(validate_reading(record, source))
    expected = "<!-- AI theme-focused reading; not independently verified -->\n" + body
    core._publish(core._safe_path(directory, "reading.md"), expected)
    return {"reading_id": "RD-" + core._digest(record), "root": "evidence_packs",
            "directory": directory.relative_to(config.paths.evidence_packs_dir).as_posix(),
            "source": source, "focus": focus, "context": context,
            "result_sha256": core._digest(record),
            "hashes": file_hashes(directory, ("reading.md", "result.json"))}


def check_reading(config, ref):
    directory = reading_path(config, ref)
    check_files(directory, ref["hashes"])
    record = _unwrap(directory / "result.json")
    if core._digest(record) != ref["result_sha256"] or ref["reading_id"] != "RD-" + core._digest(record):
        _fail("THEME_READING_REFERENCE_INVALID", "精读来源引用与保存结果不符")
    return validate_reading(record, ref["source"])


def _empty(config):
    return {"schema_version": 1, "protocol_version": PROTOCOL,
            "group_id": config.zotero.group_id, "themes": {}, "last_input": None,
            "observed_sources": [], "generation": 0, "last_change_id": None,
            "index_sha256": None, "previous_index_sha256": None}


def index_text(config, state):
    def theme_link(tid):
        return f"[{tid}](<{state['themes'][tid]['current']['directory']}/revised.md>)"
    lines = ["# 统一主题池\n",
             "主题编号独立于运行批次。候选可自动更新、合并、拆分；正式主题不自动修改。\n",
             "## 当前主题\n"]
    for tid, entry in sorted(state["themes"].items()):
        if entry["status"] == RETIRED:
            continue
        ref = entry["current"]
        label = html.escape(entry["title"].replace("\n", " "), quote=False)
        for token in ("\\", "[", "]", "*", "_", chr(96)):
            label = label.replace(token, "\\" + token)
        lines.append(f"- {tid} · {entry['status']} · [{label}](<{ref['directory']}/revised.md>)")
        if entry["predecessors"]:
            lines.append("  - 来源主题：" + "、".join(theme_link(t) for t in entry["predecessors"]))
        if len(entry["history"]) > 1:
            lines.append("  - 历史版本：" + " · ".join(
                f"[{i}](<{r['directory']}/revised.md>)" for i, r in enumerate(entry["history"], 1)))
    lines.append("\n## 已合并或拆分的历史主题\n")
    for tid, entry in sorted(state["themes"].items()):
        if entry["status"] == RETIRED:
            lines.append(f"- [{tid}](<{entry['current']['directory']}/revised.md>) → "
                         + "、".join(theme_link(t) for t in entry["successors"]))
    lines.append("\n每次变更的理由与版本关系保存在 _registry.json 和 changes/；不以固定正文格式判断科学质量。\n")
    return "\n".join(lines)


def check_index(config, state):
    path = root_path(config, "index.md")
    if path.exists():
        actual = text_hash(path.read_text(encoding="utf-8"))
        permitted = {state.get("index_sha256"), state.get("previous_index_sha256")}
        if actual not in permitted:
            _fail("THEME_FILE_CONFLICT", "统一主题入口被人工修改，保留该文件", path=str(path))


def render_index(config, state):
    check_index(config, state)
    path = root_path(config, "index.md")
    body = index_text(config, state)
    if text_hash(body) != state["index_sha256"]:
        _fail("THEME_POOL_CONFLICT", "主题入口与注册表记录不一致")
    if not path.exists() or path.read_text(encoding="utf-8") != body:
        atomic_text(path, body)


def load(config):
    path = root_path(config, "_registry.json")
    if not path.exists():
        # Recover only a complete, unbranched chain of prepared publications.
        # This is read-only; migrate(apply=True) repairs the pointer under the lock.
        commits = [_unwrap(root_path(config, p.relative_to(config.paths.themes_dir).as_posix()))
                   for p in root_path(config, "changes").glob("*/commit.json")]
        if not commits:
            return None
        commits.sort(key=lambda s: s["generation"])
        previous = None
        for number, candidate in enumerate(commits, 1):
            if (candidate["generation"] != number or candidate.get("previous_registry_sha256")
                    != (core._digest(previous) if previous is not None else None)):
                _fail("THEME_POOL_REGISTRY_MISSING", "注册表缺失且历史链不完整或有分支；保留记录，不重新生成主题")
            previous = candidate
        state = previous
    else:
        state = _unwrap(path)
    if (state.get("schema_version") != 1 or state.get("protocol_version") != PROTOCOL
            or state.get("group_id") != config.zotero.group_id or not isinstance(state.get("themes"), dict)):
        _fail("THEME_POOL_CONFLICT", "主题池版本或共享库不匹配")
    for tid, entry in state["themes"].items():
        if not re.fullmatch(r"TH-[A-Za-z0-9-]+", tid) or entry["theme_id"] != tid:
            _fail("THEME_POOL_CONFLICT", "主题编号无效")
        if entry["status"] not in {ACTIVE, RETIRED, "FORMAL"} or entry["current"] not in entry["history"]:
            _fail("THEME_POOL_CONFLICT", "主题状态或历史版本无效")
        for ref in entry["history"]:
            check_files(root_path(config, ref["directory"]), ref["hashes"])
            for reading in ref["readings"]:
                check_reading(config, reading)
        for related in entry["predecessors"] + entry["successors"]:
            if related not in state["themes"]:
                _fail("THEME_POOL_CONFLICT", "主题演化关系指向不存在的主题")
    check_index(config, state)
    return state


def commit(config, base, next_state, change_dir):
    """Caller holds the theme lock. Immutable commit first, registry last."""
    next_state["generation"] = (base or {}).get("generation", 0) + 1
    next_state["previous_registry_sha256"] = core._digest(base) if base is not None else None
    next_state["previous_index_sha256"] = (base or {}).get("index_sha256")
    next_state["index_sha256"] = text_hash(index_text(config, next_state))
    current = load(config)
    if current != base:
        _fail("THEME_POOL_CHANGED", "处理期间主题池发生变化；保留结果，不覆盖")
    check_index(config, base or _empty(config))
    core._publish(change_dir / "commit.json", core._json(_wrap(next_state)))
    atomic_text(root_path(config, "_registry.json"), core._json(_wrap(next_state)))
    render_index(config, next_state)
    return next_state


def migrate(config, binding, *, apply):
    """Adopt completed legacy results without moving, rewriting, or re-reading."""
    existing = load(config)
    if existing is not None:
        if apply:
            if not root_path(config, "_registry.json").exists():
                atomic_text(root_path(config, "_registry.json"), core._json(_wrap(existing)))
            render_index(config, existing)
        return existing, 0
    state = _empty(config)
    compatible = []
    legacy = root_path(config, "candidates")
    for batch in sorted(legacy.glob("BATCH-*")):
        batch = root_path(config, batch.relative_to(config.paths.themes_dir).as_posix())
        if not (batch / "completion.json").is_file():
            continue
        inputs = _read(batch / "inputs.json")
        if inputs.get("group_id") != config.zotero.group_id:
            continue
        completion = _read(batch / "completion.json")
        discovery = _unwrap(batch / "discovery-result.json")
        if discovery["binding"] != inputs:
            _fail("THEME_POOL_MIGRATION_CONFLICT", "旧批次来源与发现结果不匹配")
        compatible.append(inputs)
        for tid in completion["theme_ids"]:
            if not isinstance(tid, str) or not re.fullmatch(r"TH-[A-Za-z0-9-]+", tid):
                _fail("THEME_POOL_MIGRATION_CONFLICT", "旧主题编号不合法")
            directory = core._safe_path(batch, tid)
            manifest, plan = _read(directory / "manifest.json"), _read(directory / "plan.json")
            if manifest["theme_id"] != tid or plan["theme_id"] != tid or tid in state["themes"]:
                _fail("THEME_POOL_MIGRATION_CONFLICT", "旧主题身份冲突，不任意选择")
            check_files(directory, {"initial.md": manifest["initial_sha256"],
                                    "revised.md": manifest["revised_sha256"]})
            revision = _unwrap(directory / "revision-result.json")
            refs = []
            for r in manifest["reading_references"]:
                # Resolve historical relative links only within the configured evidence root.
                old_read = (directory / r["path"]).resolve()
                if not old_read.is_relative_to(config.paths.evidence_packs_dir.resolve()):
                    _fail("THEME_POOL_PATH_INVALID", "旧精读引用越出证据包")
                read_dir = core._safe_path(config.paths.evidence_packs_dir,
                    old_read.parent.relative_to(config.paths.evidence_packs_dir).as_posix())
                rec = _unwrap(read_dir / "result.json")
                meta = _read(read_dir / "manifest.json")
                if (core._digest(rec) != r["result_sha256"] or meta["source"]["evidence_id"] != r["evidence_id"]
                        or rec["binding"]["source"] != meta["source"]):
                    _fail("THEME_POOL_MIGRATION_CONFLICT", "旧精读来源或指纹不一致")
                # read-only validation: do not repair/write any legacy artifact.
                body = validate_reading(rec, meta["source"])
                if (text_hash(body) != meta["reading_sha256"] or
                        old_read.read_text(encoding="utf-8") !=
                        "<!-- AI theme-focused reading; not independently verified -->\n" + body):
                    _fail("THEME_FILE_CONFLICT", "旧精读正文被修改，迁移停止")
                refs.append({"reading_id": "RD-" + core._digest(rec), "root": "evidence_packs",
                    "directory": read_dir.relative_to(config.paths.evidence_packs_dir).as_posix(),
                    "source": meta["source"], "focus": meta["focus"],
                    "context": plan["candidate_markdown"], "result_sha256": core._digest(rec),
                    "hashes": file_hashes(read_dir, ("reading.md", "result.json"))})
            ref = {"directory": directory.relative_to(config.paths.themes_dir).as_posix(),
                   "hashes": file_hashes(directory, ("initial.md", "revised.md", "plan.json",
                                                     "manifest.json", "revision-result.json")), "readings": refs}
            if revision["binding"]["theme_id"] != tid:
                _fail("THEME_POOL_MIGRATION_CONFLICT", "旧回填结果主题身份不匹配")
            state["themes"][tid] = {"theme_id": tid, "title": plan["title"],
                "status": "FORMAL" if manifest.get("formal_confirmation") is not None else ACTIVE,
                "formal_confirmation": manifest.get("formal_confirmation"),
                "predecessors": [], "successors": [], "current": ref, "history": [ref],
                "reason": "从已有完成批次接入统一主题池；保留原编号、正文和来源，不重新调用模型"}
    count = len(state["themes"])
    if not count and not compatible:
        return state, 0
    # One fully current legacy run is already a valid starting knowledge state.
    # Multiple historical runs must be considered jointly, not selected by date.
    if len(compatible) == 1:
        old = compatible[0]
        # ``pdf_reading_prompt_sha256`` belongs to the historical PDF-reading
        # batch. It is deliberately absent from the compared keys: the current
        # pipeline does not read a PDF, and a migrated pool must not look stale
        # for a prompt it will never run.
        keys = ("group_id", "sources", "research_goal", "model", "reasoning_effort")
        old_assets = {k: v for k, v in binding["assets"].items() if k in old["assets"]}
        if all(old.get(k) == binding.get(k) for k in keys) and old_assets == old["assets"]:
            state["last_input"] = core._digest(binding)
            state["observed_sources"] = binding["sources"]
    if apply:
        change_id = "IMPORT-" + core._digest(state)[:24]
        state["last_change_id"] = change_id
        commit(config, None, state, root_path(config, "changes/" + change_id))
    return state, count


def reading_catalog(config, state):
    catalog = {}
    for entry in state["themes"].values():
        for version in entry["history"]:
            for ref in version["readings"]:
                body = check_reading(config, ref)
                catalog.setdefault(ref["reading_id"], {**ref, "markdown": body})
    return catalog


def plan_actions(output, state, sources, change_id, catalog):
    """Validate routing, lineage and publication rights, never scientific prose."""
    core._nonempty(output.get("problem_clusters_markdown"), "问题簇与变更说明")
    actions = output.get("actions")
    if not isinstance(actions, list):
        _fail("THEME_ROUTE_INVALID", "缺少主题池变更清单")
    planned, used = [], set()
    for number, raw in enumerate(actions):
        if not isinstance(raw, dict):
            _fail("THEME_ROUTE_INVALID", "主题池操作必须是对象")
        kind, parents, children = raw.get("kind"), raw.get("theme_ids"), raw.get("themes")
        if (kind not in {"CREATE", "UPDATE", "MERGE", "SPLIT"} or not isinstance(parents, list)
                or not all(isinstance(p, str) for p in parents) or len(set(parents)) != len(parents)
                or not isinstance(children, list)):
            _fail("THEME_ROUTE_INVALID", "主题池操作或来源编号无效")
        core._nonempty(raw.get("reason"), "主题变更原因")
        valid_shape = ((kind == "CREATE" and len(parents) == 0 and len(children) == 1)
            or (kind == "UPDATE" and len(parents) == 1 and len(children) == 1)
            or (kind == "MERGE" and len(parents) >= 2 and len(children) == 1)
            or (kind == "SPLIT" and len(parents) == 1 and len(children) >= 2))
        if not valid_shape:
            _fail("THEME_ROUTE_INVALID", "合并/拆分/更新操作的输入输出数量不匹配")
        for parent in parents:
            entry = state["themes"].get(parent)
            if (entry is None or entry["status"] != ACTIVE or entry.get("formal_confirmation") is not None
                    or parent in used):
                _fail("THEME_PARENT_PROTECTED", "只能修改当前候选；正式、历史或重复操作的主题受保护", theme_id=parent)
            used.add(parent)
        built = []
        for index, child in enumerate(children):
            normalized = core._discovery({"problem_clusters_markdown": "routing", "themes": [child]}, sources)[0]
            tasks = {}
            for task in child["paper_tasks"]:
                eid = task["evidence_id"]
                reuse = task.get("reuse_reading_id")
                if reuse is not None and not isinstance(reuse, str):
                    _fail("THEME_REUSE_INVALID", "精读复用编号必须是文本或null")
                if reuse:
                    ref = catalog.get(reuse)
                    if ref is None or ref["source"] != sources[eid]["record"]:
                        _fail("THEME_REUSE_INVALID", "请求复用的精读不存在或来源版本不同")
                    core._nonempty(task.get("reuse_reason"), "精读复用理由")
                if eid in tasks and tasks[eid].get("reuse_reading_id") != reuse:
                    _fail("THEME_REUSE_INVALID", "同篇精读路由的复用选择互相矛盾")
                tasks[eid] = {"reuse_reading_id": reuse, "reuse_reason": task.get("reuse_reason")}
            for task in normalized["paper_tasks"]:
                task.update(tasks[task["evidence_id"]])
            tid = parents[0] if kind == "UPDATE" else "TH-" + core._digest(
                {"change": change_id, "action": number, "child": index, "content": normalized})[:24]
            if kind != "UPDATE" and tid in state["themes"]:
                _fail("THEME_ID_CONFLICT", "新主题编号与已存在主题冲突")
            built.append({**normalized, "theme_id": tid})
        planned.append({"kind": kind, "theme_ids": parents, "reason": raw["reason"], "themes": built})
    return planned


def apply_actions(base, actions, saved, change_id, binding):
    state = copy.deepcopy(base)
    for action in actions:
        children = [c["theme_id"] for c in action["themes"]]
        for child in action["themes"]:
            tid = child["theme_id"]
            ref = saved[tid]
            old = state["themes"].get(tid)
            state["themes"][tid] = {"theme_id": tid, "title": child["title"], "status": ACTIVE,
                "formal_confirmation": None, "predecessors": old["predecessors"] if old else action["theme_ids"],
                "successors": [], "current": ref, "history": (old["history"] if old else []) + [ref],
                "reason": action["reason"]}
        if action["kind"] in {"MERGE", "SPLIT"}:
            for parent in action["theme_ids"]:
                state["themes"][parent].update(status=RETIRED, successors=children)
    state.update(last_input=core._digest(binding), observed_sources=binding["sources"], last_change_id=change_id)
    return state
