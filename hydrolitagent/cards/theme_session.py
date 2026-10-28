"""Step-by-step, file-based session protocol for the unified theme pool.

``themes-run`` performs discovery, one focused reading per (theme, paper) and a
refinement per candidate in a single process, asking a ``CardRunner`` for each
answer. That is the right shape for the ``direct`` runner, but the ``in_session``
executor is an agent the platform does not call. For that case the same three
kinds of step are exposed as files instead:

    cards run prepare --theme --run-dir DIR   -> state.json, request.json,
                                                 output.schema.json (+ paper.md)
    <agent>                                   -> DIR/response.json
    cards run finalize --theme --run-dir DIR  -> verify, save, stage the next step

Every answer is checked with the rules the one-shot run applies:
``theme_pool.plan_actions`` for discovery, ``domain.grounding`` (digest,
canaries, verbatim quotes, page anchors, coverage) for a focused reading, and
the same non-empty check for a refinement. The saved artifacts use the same
layout and fingerprints as a direct run, so the theme pool's immutable revision
chain, its ``_registry.json`` hash chain and ``<themes>/index.md`` are unchanged.

The platform never invokes a model here: ``model_invoked`` is always false and
``model_call_count`` stays at zero. A step is only marked complete in
``state.json`` after its artifacts validate, so a crash between publication and
the state write is retried instead of skipped, and replaying the same answer is
a no-op rather than a second change.

Step material and artifact saving live in :mod:`theme_session_steps`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from hydrolitagent.cards import theme_pool as pool
from hydrolitagent.cards import theme_pool_runner as runner_core
from hydrolitagent.cards import themes as core
from hydrolitagent.cards.domain.reading import GroundingError
from hydrolitagent.cards.evidence_packages import EvidencePackageError
from hydrolitagent.cards.pdf_delivery import PdfDeliveryError
from hydrolitagent.cards.pdf_gate import PdfGateError
from hydrolitagent.cards.publication import atomic_text
from hydrolitagent.cards.tasks import TaskStoreError
from hydrolitagent.cards.theme_session_steps import (
    INSTRUCTIONS_FILENAME,
    KIND_DISCOVERY,
    KIND_READING,
    KIND_REFINEMENT,
    REQUEST_FILENAME,
    RESPONSE_FILENAME,
    RESPONSES_DIRNAME,
    SCHEMA_FILENAME,
    SESSION_PROTOCOL,
    STATE_FILENAME,
    STATE_SCHEMA_VERSION,
    _commit,
    _current_step,
    _discovery_step,
    _NEXT_ACTION,
    _next_step,
    _now,
    _open_context,
    _read_json,
    _read_request,
    _remaining_steps,
    _reopen_context,
    _save_discovery,
    _save_reading,
    _save_refinement,
    _step_index,
    _steps_from_plan,
    _write_step,
)
from hydrolitagent.cards.zotero import ZoteroApiError


def _base_result(operation: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": operation,
        "ok": False,
        "status": "FAILED",
        "protocol_version": pool.PROTOCOL,
        "session_protocol": SESSION_PROTOCOL,
        "model_invoked": False,
        "model_call_count": 0,
    }


def _load_state(run_dir) -> dict[str, Any] | None:
    path = Path(run_dir) / STATE_FILENAME
    if not path.is_file():
        return None
    state = _read_json(path)
    if (not isinstance(state, dict)
            or state.get("schema_version") != STATE_SCHEMA_VERSION
            or state.get("session_protocol") != SESSION_PROTOCOL):
        raise core.ThemeError(
            "THEME_SESSION_STATE_INVALID",
            "state.json 版本不符；请重新运行 cards run prepare --theme",
        )
    return state


def _write_state(run_dir, session) -> None:
    session["updated_at"] = _now()
    atomic_text(Path(run_dir) / STATE_FILENAME, core._json(session))


def _archive_path(run_dir, step_id: str) -> Path:
    # Step ids contain ``:``, which is illegal in a Windows file name.
    return Path(run_dir) / RESPONSES_DIRNAME / (step_id.replace(":", "__") + ".json")


def _archive_response(run_dir, step_id: str, raw: str) -> Path:
    path = _archive_path(run_dir, step_id)
    atomic_text(path, raw)
    return path


# --------------------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------------------


def _new_session(config, context, run_dir, literature_root) -> dict[str, Any]:
    core._publish(context.change_dir / "inputs.json",
                  core._json({"base_registry": context.base, "input": context.binding}))
    steps = [_discovery_step()]
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "session_protocol": SESSION_PROTOCOL,
        "protocol_version": pool.PROTOCOL,
        "run_id": uuid4().hex[:16],
        "run_dir": str(run_dir),
        "change_id": context.change_id,
        "change_path": str(context.change_dir),
        "literature_root": str(literature_root) if literature_root is not None else None,
        "binding": context.binding,
        "binding_digest": core._digest(context.binding),
        "base_digest": core._digest(context.base),
        "model": context.cg.model,
        "reasoning_effort": context.cg.reasoning_effort,
        "timeout_seconds": context.cg.generation_timeout_seconds,
        "sources": context.binding["sources"],
        "steps": steps,
        "steps_known": False,
        "plan": None,
        "completed": [],
        "reading_refs": {},
        "step": steps[0]["id"],
        "step_index": 0,
        "remaining_steps": [],
        "response_file": RESPONSE_FILENAME,
        "last_result": None,
        "status": "AWAITING_SESSION_OUTPUT",
    }


def _sync_step_fields(session, step) -> None:
    session["step"] = step["id"]
    session["step_index"] = _step_index(session, step)
    session["remaining_steps"] = _remaining_steps(session, step)
    session["status"] = "AWAITING_SESSION_OUTPUT"
    session["next_action"] = _NEXT_ACTION[step["kind"]]


def _public(session) -> dict[str, Any]:
    step = _current_step(session)
    run_dir = Path(session["run_dir"])
    return {
        "status": "AWAITING_SESSION_OUTPUT",
        "run_id": session.get("run_id"),
        "run_dir": str(run_dir),
        "state_path": str(run_dir / STATE_FILENAME),
        "request_path": str(run_dir / REQUEST_FILENAME),
        "schema_path": str(run_dir / SCHEMA_FILENAME),
        "instructions_path": str(run_dir / INSTRUCTIONS_FILENAME),
        "response_file": RESPONSE_FILENAME,
        "change_id": session["change_id"],
        "step": step["id"],
        "step_kind": step["kind"],
        "step_index": _step_index(session, step),
        "steps_known": bool(session.get("steps_known")),
        "remaining_steps": _remaining_steps(session, step),
        "next_action": _NEXT_ACTION[step["kind"]],
    }


def prepare_theme_session(config, *, run_dir, literature_root=None,
                          delivery_preparer=None, pipeline=None) -> dict:
    """Write the first unfinished theme step into ``run_dir``; never calls a model."""

    result = _base_result("theme_session_prepare")
    run_dir = Path(run_dir)
    try:
        context, source_report, imported = _open_context(
            config, literature_root, migrate_imports=True)
        result.update(
            pool_path=str(config.paths.themes_dir),
            index_path=str(config.paths.themes_dir / "index.md"),
            imported_theme_count=imported,
            source_count=len(context.sources) if context is not None else 0,
            **source_report,
        )
        if context is None:
            result.update(ok=True, status="NO_ROUGH_CARDS", next_action=None,
                          note="没有可用的来源草稿或证据包；不写运行目录、不调用模型")
            return result
        if context.state["last_input"] == core._digest(context.binding):
            # This exact input is already committed: there is nothing left to do.
            summary: dict[str, Any] = {}
            runner_core._summary(config, context.state, summary)
            refs = {r["reading_id"] for e in context.state["themes"].values()
                    if e["status"] == pool.ACTIVE for r in e["current"]["readings"]}
            result.update(
                ok=True, status="UNCHANGED", action="UNCHANGED", next_action=None,
                run_dir=None, step=None, step_kind=None, step_index=None,
                steps_known=False, remaining_steps=[], response_file=None,
                candidate_count=summary["candidate_count"],
                refined_count=summary["refined_count"],
                themes=summary["themes"],
                reused_reading_count=len(refs),
                reused_step_count=1 + len(refs) + summary["candidate_count"],
            )
            return result

        session = _load_state(run_dir)
        matching = (session is not None
                    and session.get("change_id") == context.change_id
                    and core._digest(session.get("binding")) == core._digest(context.binding))
        if matching:
            step = (_next_step(session) if session.get("steps_known")
                    else _current_step(session))
            if step is None:
                raise core.ThemeError(
                    "THEME_SESSION_STATE_INVALID",
                    "所有步骤都已完成但主题池尚未提交；请重新运行 cards run prepare --theme",
                )
            session["run_dir"] = str(run_dir)
            session["step"] = step["id"]
            _write_step(config, run_dir, session, step, context, pipeline, delivery_preparer)
            _sync_step_fields(session, step)
            _write_state(run_dir, session)
            return {**result, "ok": True, "resumed": True, **_public(session)}

        session = _new_session(config, context, run_dir, literature_root)
        step = _current_step(session)
        _write_step(config, run_dir, session, step, context, pipeline, delivery_preparer)
        _sync_step_fields(session, step)
        _write_state(run_dir, session)
        return {**result, "ok": True, "resumed": False, **_public(session)}
    except core.ThemeError as exc:
        result.update(error={"code": exc.code, "message": str(exc), **exc.details})
    except GroundingError as exc:
        result.update(error={"code": exc.code, "message": str(exc),
                             "diagnostic": dict(exc.detail)})
    except (EvidencePackageError, PdfDeliveryError, PdfGateError, TaskStoreError,
            ZoteroApiError) as exc:
        result.update(error={"code": getattr(exc, "code", "THEME_SOURCE_UNAVAILABLE"),
                             "message": str(exc)})
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result.update(error={"code": "THEME_LOCAL_ERROR",
                             "message": "文件、配置或步骤记录不可读取；已完成结果保留，不覆盖",
                             "exception_type": type(exc).__name__})
    return result


def _finish_step(run_dir, session, step, raw: str, from_archive: bool,
                 public: dict[str, Any]) -> dict[str, Any]:
    """Consume the accepted answer, then record the advance.

    The archive is written before ``response.json`` is removed and before
    ``state.json`` changes, so a crash in between is recoverable: the next
    finalize finds the archived answer for the same step and retries the advance.
    """

    if not from_archive:
        _archive_response(run_dir, step["id"], raw)
        (Path(run_dir) / RESPONSE_FILENAME).unlink(missing_ok=True)
    _write_state(run_dir, session)
    return public


def _result_fields(session) -> dict[str, Any]:
    """Fields repeated by every finalize outcome, before the step advances."""

    step = _current_step(session)
    return {
        "run_id": session.get("run_id"),
        "run_dir": session.get("run_dir"),
        "change_id": session["change_id"],
        "step": step["id"],
        "step_kind": step["kind"],
        "step_index": _step_index(session, step),
        "response_file": RESPONSE_FILENAME,
    }


def finalize_theme_session(config, *, run_dir, literature_root=None,
                           delivery_preparer=None, pipeline=None) -> dict:
    """Read ``response.json`` for the current step, verify it, and advance."""

    result = _base_result("theme_session_finalize")
    run_dir = Path(run_dir)
    try:
        session = _load_state(run_dir)
        if session is None:
            raise core.ThemeError(
                "THEME_SESSION_STATE_MISSING",
                f"运行目录没有 {STATE_FILENAME}；请先执行 cards run prepare --theme",
            )
        session["run_dir"] = str(run_dir)
        if session.get("status") == "COMPLETED" and session.get("last_result"):
            # The pool was already committed for this session; re-report it
            # instead of demanding a further step that does not exist.
            return {**session["last_result"], "replayed": True, "run_dir": str(run_dir)}
        root = literature_root if literature_root is not None else session.get("literature_root")
        context = _reopen_context(config, session, root)
        result.update(_result_fields(session))

        step = _current_step(session)
        request = _read_request(run_dir)
        if request is None or request.get("step") != step["id"]:
            # A crash between staging the next request and writing state.json
            # leaves the two disagreeing. Rebuild this step's request instead of
            # demanding a fresh prepare: the material is derived, not user data.
            _write_step(config, run_dir, session, step, context, pipeline, delivery_preparer)
            request = _read_request(run_dir)
        if request is None or request.get("step") != step["id"]:
            raise core.ThemeError(
                "THEME_SESSION_STATE_INVALID",
                "request.json 与 state.json 的当前步骤不一致；请重新运行 prepare",
            )
        response_path = run_dir / RESPONSE_FILENAME
        archive_path = _archive_path(run_dir, step["id"])
        if response_path.is_file():
            raw = response_path.read_text(encoding="utf-8")
            from_archive = False
        elif archive_path.is_file():
            # The answer was archived but the state write did not land; replaying
            # it is safe because every artifact below is content-addressed.
            raw = archive_path.read_text(encoding="utf-8")
            from_archive = True
        elif session.get("last_result"):
            # No new answer: finalize was called twice for the same completed
            # step. Re-report that outcome instead of applying anything again.
            return {**session["last_result"], "replayed": True, "run_dir": str(run_dir)}
        else:
            raise core.ThemeError(
                "IN_SESSION_RESPONSE_MISSING",
                f"还没有 {RESPONSE_FILENAME}；agent 写完后再次执行 finalize",
            )
        try:
            output = json.loads(raw)
        except ValueError as exc:
            raise core.ThemeError("IN_SESSION_RESPONSE_INVALID",
                                  f"{RESPONSE_FILENAME} 不是有效 JSON") from exc
        if not isinstance(output, dict):
            raise core.ThemeError("IN_SESSION_RESPONSE_INVALID",
                                  f"{RESPONSE_FILENAME} 必须是 JSON 对象")
        outcome = _result_fields(session)

        if step["kind"] == KIND_DISCOVERY:
            plan = _save_discovery(config, session, context, request, output)
            session["plan"] = plan
            session["steps"] = [_discovery_step(), *_steps_from_plan(plan)]
            session["steps_known"] = True
        elif step["kind"] == KIND_READING:
            ref = _save_reading(config, run_dir, session, context, step, request, output)
            session.setdefault("reading_refs", {})[step["id"]] = ref
        else:
            _save_refinement(config, session, context, step, request, output)

        completed = list(session.get("completed") or ())
        if step["id"] not in completed:
            completed.append(step["id"])
        session["completed"] = completed

        next_step = _next_step(session)
        if next_step is None:
            summary = _commit(config, session, context)
            session["status"] = "COMPLETED"
            session["remaining_steps"] = []
            session["next_action"] = None
            outcome.update(ok=True, status="COMPLETED", next_step=None,
                           remaining_steps=[], next_action=None,
                           steps_known=True, steps_total=len(session["steps"]),
                           **summary)
            public = {**result, **outcome}
            session["last_result"] = public
            return _finish_step(run_dir, session, step, raw, from_archive, public)

        # Move the pointer before staging, because staging writes the next
        # request; a staging failure is retried because state.json is untouched.
        session["step"] = next_step["id"]
        _write_step(config, run_dir, session, next_step, context, pipeline, delivery_preparer)
        session["step_index"] = _step_index(session, next_step)
        session["remaining_steps"] = _remaining_steps(session, next_step)
        session["status"] = "NEXT_STEP_READY"
        session["next_action"] = _NEXT_ACTION[next_step["kind"]]
        outcome.update(ok=True, status="NEXT_STEP_READY", next_step=next_step["id"],
                       next_step_kind=next_step["kind"],
                       remaining_steps=session["remaining_steps"],
                       next_action=session["next_action"], steps_known=True,
                       steps_total=len(session["steps"]))
        public = {**result, **outcome}
        session["last_result"] = public
        return _finish_step(run_dir, session, step, raw, from_archive, public)
    except core.ThemeError as exc:
        result.update(error={"code": exc.code, "message": str(exc), **exc.details})
    except GroundingError as exc:
        result.update(error={"code": exc.code, "message": str(exc),
                             "diagnostic": dict(exc.detail)})
    except (EvidencePackageError, PdfDeliveryError, PdfGateError, TaskStoreError,
            ZoteroApiError) as exc:
        result.update(error={"code": getattr(exc, "code", "THEME_SOURCE_UNAVAILABLE"),
                             "message": str(exc)})
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result.update(error={"code": "THEME_LOCAL_ERROR",
                             "message": "文件、配置或步骤记录不可读取；已完成结果保留，不覆盖",
                             "exception_type": type(exc).__name__})
    result["status"] = "FAILED"
    return result


def theme_session_run_dir(config) -> Path:
    """Default run directory for ``themes-run --ai-provider in_session``.

    Stable on purpose: rerunning the command resumes the unfinished step instead
    of starting a second, competing session.
    """

    from hydrolitagent.cards.application.workspace import runtime_dir

    return Path(runtime_dir(config)) / "theme-session"


__all__ = [
    "INSTRUCTIONS_FILENAME",
    "KIND_DISCOVERY",
    "KIND_READING",
    "KIND_REFINEMENT",
    "REQUEST_FILENAME",
    "RESPONSE_FILENAME",
    "SCHEMA_FILENAME",
    "SESSION_PROTOCOL",
    "STATE_FILENAME",
    "finalize_theme_session",
    "prepare_theme_session",
    "theme_session_run_dir",
]
