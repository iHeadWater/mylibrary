"""A synthesis request has no paper: the prompt is the whole material.

The theme workflow needs a runner that can answer a text-only task (discovery,
refinement). ``CardRunRequest.paper`` is therefore optional. These tests pin the
contract from the runner side: nothing is staged as ``paper.md``, nothing is
verified as a reading, and the prompt is what the model receives.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from hydrolitagent.cards.adapters.runners.in_session import (
    AWAITING_SESSION_OUTPUT,
    RESPONSE_FILENAME,
    RUN_REQUEST_FILENAME,
    InSessionRunner,
)
from hydrolitagent.cards.adapters.runners.scripted import ScriptedRunner
from hydrolitagent.cards.adapters.runners.direct import DirectRunner
from hydrolitagent.cards.ports.runner import CardRunRequest

SCHEMA = {
    "type": "object",
    "required": ["actions"],
    "properties": {"actions": {"type": "array"}},
}
ANSWER = {"problem_clusters_markdown": "fixture", "actions": []}
PROMPT = "## 任务\n根据输入卡片规划候选主题。\n"


def text_request(workspace: Path, *, role: str = "theme_discovery") -> CardRunRequest:
    workspace.mkdir(parents=True, exist_ok=True)
    return CardRunRequest(
        run_id="run-text",
        paper=None,
        prompt=PROMPT,
        output_schema=SCHEMA,
        workspace=workspace,
        timeout_seconds=5,
        role=role,
    )


def test_direct_runner_sends_the_prompt_and_no_paper(tmp_path):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant",
                                     "content": json.dumps(ANSWER, ensure_ascii=False)}}],
        })

    runner = DirectRunner(
        base_url="https://api.example.test/v1",
        api_key="sk-test-key-123456",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    result = runner.run(text_request(tmp_path / "workspace"))

    assert result.ok, result.error
    assert result.output == ANSWER
    assert result.model_invoked is True
    user_content = seen[0]["messages"][-1]["content"]
    assert PROMPT in user_content
    assert "paper.md" not in user_content
    assert list((tmp_path / "workspace").glob("*.md")) == []
    assert (tmp_path / "workspace" / RESPONSE_FILENAME).is_file()


def test_in_session_stages_a_text_task_and_collects_the_answer(tmp_path):
    runner = InSessionRunner()
    run_dir = tmp_path / "run"
    request = text_request(run_dir, role="theme_synthesis")

    prepared = runner.prepare(request)
    assert prepared.page_count == 0
    assert prepared.canaries == ()
    assert not (run_dir / "paper.md").exists()
    payload = json.loads((run_dir / RUN_REQUEST_FILENAME).read_text(encoding="utf-8"))
    assert payload["mode"] == "text_only"
    assert payload["prompt"] == PROMPT
    assert payload["role"] == "theme_synthesis"

    pending = runner.run(request)
    assert not pending.ok
    assert pending.error.code == AWAITING_SESSION_OUTPUT

    (run_dir / RESPONSE_FILENAME).write_text(
        json.dumps(ANSWER, ensure_ascii=False), encoding="utf-8"
    )
    finalized = runner.finalize(run_dir, paper=None)
    assert finalized.ok, finalized.error
    assert finalized.output == ANSWER
    assert finalized.model_invoked is False


def test_scripted_runner_accepts_a_text_only_request(tmp_path):
    runner = ScriptedRunner(ANSWER)
    result = runner.run(text_request(tmp_path / "workspace"))
    assert result.ok
    assert result.output == ANSWER
    assert runner.requests[0].paper is None
