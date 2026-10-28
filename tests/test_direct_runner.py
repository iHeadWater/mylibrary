"""Behaviour of the ``direct`` runner, driven by ``httpx.MockTransport``.

No network, no key, no model: every assertion is about the request the runner
builds and the result it returns. The ``direct`` executor is one
``/chat/completions`` call (DeepSeek by default), so the contract can be tested
exactly like any other port.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import httpx
import pytest

from hydrolitagent.cards.adapters.runners.direct import (
    CHUNKED_READING,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    JSON_SCHEMA_UNSUPPORTED,
    VISUAL_CONTENT_NOT_REVIEWED,
    DirectRunner,
    estimate_tokens,
    plan_chunks,
)
from hydrolitagent.cards.domain.paper import (
    MARKDOWN_FILENAME,
    PageAnchor,
    PreparedPaper,
    SourceIdentity,
)
from hydrolitagent.cards.ports.runner import CardRunRequest

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["card_body_markdown"],
    "properties": {"card_body_markdown": {"type": "string"}},
}

ANSWER = {
    "schema_version": 2,
    "card_body_markdown": "# Fixture card\n\nF001: fixture result.\n",
    "visual_content_status": "NOT_PRESENT",
}

API_KEY = "sk-test-key-123456"

PAGE_BODIES = [
    (
        "Rainfall-runoff processes in small catchments are controlled by soil moisture "
        "and storm intensity over three seasons."
    ),
    (
        "We calibrated a bucket model against three seasons of field observations in "
        "two catchments and compared it with a regression baseline."
    ),
]


# --------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------


def make_document(page_bodies: list[str]) -> tuple[str, tuple[PageAnchor, ...]]:
    """Build a page-anchored Markdown document the way the converter does."""

    blocks = [
        (
            f"<!-- page: {page} -->\n"
            f"<!-- reading-canary: c-{page:08x} -->\n"
            f"# Page {page}\n\n"
            f"{body}\n\n"
        )
        for page, body in enumerate(page_bodies, start=1)
    ]
    markdown = "".join(blocks)
    anchors = []
    offset = 0
    for page, block in enumerate(blocks, start=1):
        anchors.append(
            PageAnchor(
                page=page,
                char_start=offset,
                char_end=offset + len(block),
                heading=f"Page {page}",
                role="body",
                canary=f"c-{page:08x}",
            )
        )
        offset += len(block)
    return markdown, tuple(anchors)


MARKDOWN, ANCHORS = make_document(PAGE_BODIES)


def prepared(
    tmp_path: Path,
    markdown: str = MARKDOWN,
    anchors: tuple[PageAnchor, ...] = ANCHORS,
) -> PreparedPaper:
    store = tmp_path / "store"
    store.mkdir(parents=True, exist_ok=True)
    markdown_path = store / MARKDOWN_FILENAME
    markdown_path.write_text(markdown, encoding="utf-8")
    return PreparedPaper(
        source=SourceIdentity(
            pdf_sha256="a" * 64,
            size_bytes=len(markdown),
            page_count=len(anchors),
            parent_key="PARENT01",
            attachment_key="ATTACH01",
        ),
        markdown_path=markdown_path,
        markdown_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        manifest_path=store / "manifest.json",
        page_anchors=anchors,
        figures=(),
        converter_id="pymupdf",
        converter_version="test",
        text_coverage=1.0,
        warnings=(),
    )


def request_for(
    tmp_path: Path,
    *,
    markdown: str = MARKDOWN,
    anchors: tuple[PageAnchor, ...] = ANCHORS,
    reading_mode: str = "inline",
    model: str | None = None,
) -> CardRunRequest:
    paper = prepared(tmp_path, markdown, anchors)
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    (workspace / MARKDOWN_FILENAME).write_text(markdown, encoding="utf-8")
    return CardRunRequest(
        run_id="run-direct",
        paper=paper,
        prompt="请按 schema 生成主体卡草稿。",
        output_schema=OUTPUT_SCHEMA,
        workspace=workspace,
        timeout_seconds=5,
        model=model,
        reading_mode=reading_mode,  # type: ignore[arg-type]
    )


def completion(content: object, *, usage: dict | None = None) -> httpx.Response:
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(content, ensure_ascii=False),
                }
            }
        ]
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


class FakeEndpoint:
    """Transport that records payloads and delegates to a handler."""

    def __init__(self, handler):
        self.handler = handler
        self.payloads: list[dict] = []
        self.urls: list[str] = []
        self.headers: list[dict] = []
        self.transport = httpx.MockTransport(self)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.payloads.append(payload)
        self.urls.append(str(request.url))
        self.headers.append(dict(request.headers))
        return self.handler(request, payload, len(self.payloads))


def sequence(*responses):
    remaining = list(responses)

    def handler(request, payload, index):
        item = remaining.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return handler


@pytest.fixture(autouse=True)
def _clean_direct_environment(monkeypatch):
    """A developer's own key or endpoint must not decide what a test observes."""

    for name in (
        "DEEPSEEK_API_KEY",
        "DIRECT_LLM_API_KEY",
        "DIRECT_LLM_BASE_URL",
        "DIRECT_LLM_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def runner(endpoint: FakeEndpoint, **overrides) -> DirectRunner:
    options = {
        "base_url": "https://api.example.test/v1",
        "api_key": API_KEY,
        "model": "test-model",
        "max_input_tokens": 200_000,
        "max_output_tokens": 4_000,
        "transport": endpoint.transport,
    }
    options.update(overrides)
    return DirectRunner(**options)


# --------------------------------------------------------------------------------------
# single call
# --------------------------------------------------------------------------------------


def test_single_call_inlines_the_markdown_and_asks_for_the_schema(tmp_path):
    endpoint = FakeEndpoint(
        sequence(
            completion(
                ANSWER,
                usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
            )
        )
    )
    request = request_for(tmp_path)

    result = runner(endpoint).run(request)

    assert result.ok, result.error
    assert result.output == ANSWER
    assert result.model_invoked is True
    assert result.model == "test-model"
    assert result.usage == {
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "total_tokens": 150,
    }
    assert result.warnings == ()
    assert endpoint.urls == ["https://api.example.test/v1/chat/completions"]
    assert endpoint.headers[0]["authorization"] == f"Bearer {API_KEY}"

    payload = endpoint.payloads[0]
    assert payload["model"] == "test-model"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["schema"] == OUTPUT_SCHEMA
    user_message = payload["messages"][1]["content"]
    assert MARKDOWN in user_message
    assert request.paper.markdown_sha256 in user_message
    assert "c-00000001" in user_message and "c-00000002" in user_message

    saved = Path(result.unvalidated_output_path)
    assert saved == request.workspace / "response.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == ANSWER


def test_schema_rejection_falls_back_once_and_records_a_warning(tmp_path):
    endpoint = FakeEndpoint(
        sequence(
            httpx.Response(400, json={"error": {"message": "response_format unsupported"}}),
            completion(ANSWER),
        )
    )

    result = runner(endpoint).run(request_for(tmp_path))

    assert result.ok, result.error
    assert JSON_SCHEMA_UNSUPPORTED in result.warnings
    assert len(endpoint.payloads) == 2
    assert "response_format" in endpoint.payloads[0]
    assert "response_format" not in endpoint.payloads[1]


def test_code_fenced_json_is_accepted(tmp_path):
    fenced = "```json\n" + json.dumps(ANSWER) + "\n```"
    endpoint = FakeEndpoint(
        sequence(httpx.Response(200, json={"choices": [{"message": {"content": fenced}}]}))
    )

    result = runner(endpoint).run(request_for(tmp_path))

    assert result.ok
    assert result.output == ANSWER


def test_invalid_json_is_a_structured_failure(tmp_path):
    endpoint = FakeEndpoint(
        sequence(httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}))
    )

    result = runner(endpoint).run(request_for(tmp_path))

    assert result.ok is False
    assert result.error.code == "RUNNER_OUTPUT_INVALID"


# --------------------------------------------------------------------------------------
# failure mapping
# --------------------------------------------------------------------------------------


def test_auth_failure_is_structured_and_never_echoes_the_key(tmp_path):
    endpoint = FakeEndpoint(
        sequence(httpx.Response(401, json={"error": {"message": f"invalid key {API_KEY}"}}))
    )

    result = runner(endpoint).run(request_for(tmp_path))

    assert result.ok is False
    assert result.error.code == "RUNNER_AUTH_FAILED"
    assert result.model_invoked is True
    rendered = json.dumps(
        {"message": result.error.message, "detail": result.error.detail}, ensure_ascii=False
    )
    assert API_KEY not in rendered
    assert "<redacted>" in rendered


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (429, "RUNNER_RATE_LIMITED"),
        (500, "RUNNER_UPSTREAM_ERROR"),
        (418, "RUNNER_REQUEST_REJECTED"),
    ],
)
def test_http_statuses_map_to_runner_codes(tmp_path, status, code):
    endpoint = FakeEndpoint(sequence(httpx.Response(status, json={"error": "nope"})))

    result = runner(endpoint).run(request_for(tmp_path))

    assert result.ok is False
    assert result.error.code == code


def test_timeout_is_not_retried(tmp_path):
    endpoint = FakeEndpoint(sequence(httpx.ReadTimeout("timed out")))

    result = runner(endpoint).run(request_for(tmp_path))

    assert result.ok is False
    assert result.error.code == "RUNNER_TIMEOUT"
    assert len(endpoint.payloads) == 1


def test_connection_failure_is_structured(tmp_path):
    endpoint = FakeEndpoint(sequence(httpx.ConnectError("connection refused")))

    result = runner(endpoint).run(request_for(tmp_path))

    assert result.ok is False
    assert result.error.code == "RUNNER_CONNECTION_FAILED"


def test_missing_key_never_calls_the_endpoint_and_names_the_fix(tmp_path):
    endpoint = FakeEndpoint(sequence(completion(ANSWER)))

    result = runner(endpoint, api_key="").run(request_for(tmp_path))

    assert result.ok is False
    assert result.error.code == "RUNNER_NOT_CONFIGURED"
    assert result.model_invoked is False
    assert endpoint.payloads == []
    assert "DEEPSEEK_API_KEY" in result.error.message
    assert "in_session" in result.error.message


def test_defaults_target_deepseek(tmp_path):
    endpoint = FakeEndpoint(sequence(completion(ANSWER)))

    result = DirectRunner(api_key=API_KEY, transport=endpoint.transport).run(
        request_for(tmp_path)
    )

    assert result.ok, result.error
    assert endpoint.urls == [DEFAULT_BASE_URL + "/chat/completions"]
    assert endpoint.payloads[0]["model"] == DEFAULT_MODEL == "deepseek-chat"
    assert result.model == DEFAULT_MODEL


def test_direct_llm_environment_overrides_the_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("DIRECT_LLM_BASE_URL", "https://proxy.example.test/v1")
    monkeypatch.setenv("DIRECT_LLM_MODEL", "another-model")
    monkeypatch.setenv("DIRECT_LLM_API_KEY", "sk-env-key-123456")
    endpoint = FakeEndpoint(sequence(completion(ANSWER)))

    result = DirectRunner(transport=endpoint.transport).run(request_for(tmp_path))

    assert result.ok, result.error
    assert endpoint.urls == ["https://proxy.example.test/v1/chat/completions"]
    assert endpoint.payloads[0]["model"] == "another-model"
    assert endpoint.headers[0]["authorization"] == "Bearer sk-env-key-123456"


def test_tampered_workspace_is_rejected_before_any_call(tmp_path):
    request = request_for(tmp_path)
    (request.workspace / MARKDOWN_FILENAME).write_text("tampered", encoding="utf-8")
    endpoint = FakeEndpoint(sequence(completion(ANSWER)))

    result = runner(endpoint).run(request)

    assert result.ok is False
    assert result.error.code == "MARKDOWN_WORKSPACE_INVALID"
    assert endpoint.payloads == []


# --------------------------------------------------------------------------------------
# token budget and chunking
# --------------------------------------------------------------------------------------


def test_estimate_tokens_counts_cjk_per_character():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("中文") == 2
    assert estimate_tokens("中文abcd") == 3


def test_plan_chunks_covers_every_character_without_truncation():
    markdown = "".join(
        f"<!-- page: {page} -->\n" + ("Rainfall and runoff. " * 40) for page in range(1, 6)
    )
    boundaries = [match.start() for match in re.finditer(r"<!-- page: ", markdown)]
    anchors = tuple(
        PageAnchor(
            page=index + 1,
            char_start=start,
            char_end=(
                boundaries[index + 1] if index + 1 < len(boundaries) else len(markdown)
            ),
            heading=None,
            role="body",
            canary=None,
        )
        for index, start in enumerate(boundaries)
    )

    chunks = plan_chunks(markdown, anchors, budget=200)

    assert len(chunks) > 1
    rebuilt = "".join(markdown[start:end] for start, end in chunks)
    assert rebuilt == markdown
    # No piece is allowed to balloon past the budget by more than one character.
    assert all(estimate_tokens(markdown[start:end]) <= 201 for start, end in chunks)


def _chunk_handler(final_answer: dict, observed: list[str]):
    def handler(request, payload, index):
        schema_name = payload["response_format"]["json_schema"]["name"]
        if schema_name == "paper_chunk_notes":
            text = payload["messages"][1]["content"]
            canaries = re.findall(
                r"<!--\s*reading-canary:\s*(c-[0-9a-f]{8})\s*-->", text
            )
            observed.extend(canaries)
            quote = next(
                line.strip()
                for line in text.splitlines()
                if len(line.strip()) >= 40 and not line.strip().startswith(("#", "<!--"))
            )
            return completion(
                {
                    "notes": "本段要点：土壤湿度与暴雨强度控制产流。",
                    "canaries_seen": canaries,
                    "source_locations": [
                        {
                            "quote": quote,
                            "pdf_page": 1,
                            "section": None,
                            "figure": None,
                            "table": None,
                        }
                    ],
                },
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
        return completion(
            final_answer,
            usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        )

    return handler


def test_oversized_paper_is_read_in_page_chunks_not_truncated(tmp_path):
    # ~3000 characters of body: several times the forced 256-token chunk budget.
    bodies = [
        (
            f"Segment {page}: rainfall and runoff observations number {page} "
            + "show the same response to soil moisture and storm intensity. " * 20
        )
        for page in range(1, 5)
    ]
    markdown, anchors = make_document(bodies)
    observed: list[str] = []
    endpoint = FakeEndpoint(_chunk_handler(ANSWER, observed))

    result = runner(endpoint, max_input_tokens=600, max_output_tokens=300).run(
        request_for(tmp_path, markdown=markdown, anchors=anchors)
    )

    assert result.ok, result.error
    chunk_payloads = [
        payload
        for payload in endpoint.payloads
        if payload["response_format"]["json_schema"]["name"] == "paper_chunk_notes"
    ]
    final_payload = endpoint.payloads[-1]
    assert len(chunk_payloads) > 1
    assert CHUNKED_READING in result.warnings

    # Every page reached some chunk: no page (and no tail) was dropped.
    chunk_text = "\n".join(payload["messages"][1]["content"] for payload in chunk_payloads)
    for page in range(1, 5):
        assert f"Segment {page}:" in chunk_text

    # The final call synthesises; it is not expected to hold the whole paper.
    final_user = final_payload["messages"][1]["content"]
    assert markdown not in final_user
    assert "分块阅读记录" in final_user
    # The synthesis works from the deterministic page/heading outline.
    assert '"outline"' in final_user
    assert "Page 1" in final_user

    assert result.output["card_body_markdown"] == ANSWER["card_body_markdown"]
    # Quotes collected per chunk survive a final answer that omitted them.
    assert result.output["source_locations"]
    assert {"prompt_tokens", "completion_tokens", "total_tokens"} <= set(result.usage)
    assert result.usage["total_tokens"] >= 15 * 2 + 10


# --------------------------------------------------------------------------------------
# vision is declared, not assumed
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        {**ANSWER, "visual_content_status": "REVIEWED"},
        {
            **ANSWER,
            "machine_fields": {"findings": [{"figure": "Fig. 2", "statement": "x"}]},
        },
    ],
)
def test_text_only_runner_never_claims_to_have_seen_a_figure(tmp_path, answer):
    endpoint = FakeEndpoint(sequence(completion(answer)))

    result = runner(endpoint).run(request_for(tmp_path))

    assert result.ok
    assert result.output["visual_content_status"] == "NOT_REVIEWED"
    assert VISUAL_CONTENT_NOT_REVIEWED in result.warnings


def test_no_figure_mention_keeps_the_honest_not_present_status(tmp_path):
    endpoint = FakeEndpoint(sequence(completion(ANSWER)))

    result = runner(endpoint).run(request_for(tmp_path))

    assert result.ok
    assert result.output["visual_content_status"] == "NOT_PRESENT"
    assert result.warnings == ()


def test_unreadable_stays_fail_closed_even_when_figures_are_mentioned(tmp_path):
    """The runner must not turn "I could not read it" into an accepted state."""

    answer = {
        **ANSWER,
        "visual_content_status": "UNREADABLE",
        "machine_fields": {"findings": [{"figure": "Fig. 2", "statement": "x"}]},
    }
    endpoint = FakeEndpoint(sequence(completion(answer)))

    result = runner(endpoint).run(request_for(tmp_path))

    assert result.ok
    assert result.output["visual_content_status"] == "UNREADABLE"
    assert VISUAL_CONTENT_NOT_REVIEWED not in result.warnings


# --------------------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------------------


def test_diagnostics_redact_paths_and_keys():
    from hydrolitagent.cards.adapters.runners.diagnostics import (
        sanitize_diagnostic_text,
    )

    redacted = sanitize_diagnostic_text(
        r"failed to read C:\Users\owen\papers\x.pdf with sk-live-12345678"
    )
    assert "%USERPROFILE%\\papers" in redacted
    assert "sk-live-12345678" not in redacted


def test_doctor_reports_missing_key_with_an_actionable_fix():
    missing = DirectRunner(api_key="").doctor()
    assert missing.available is False
    assert "DEEPSEEK_API_KEY" in missing.detail
    assert missing.fix and "DEEPSEEK_API_KEY" in missing.fix
    assert "in_session" in missing.fix

    ready = DirectRunner(
        base_url="https://api.example.test/v1", api_key=API_KEY, model="test-model"
    ).doctor()
    assert ready.available is True
    assert API_KEY not in ready.detail


if __name__ == "__main__":  # pragma: no cover - manual invocation convenience
    raise SystemExit(pytest.main([__file__]))
