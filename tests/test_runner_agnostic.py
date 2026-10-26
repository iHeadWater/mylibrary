"""The same prepared paper must produce the same draft through any runner.

This is the acceptance test for "runner-agnostic": one ``PreparedPaper`` and one
prompt go into a scripted runner and into a fake HTTP runner, and the resulting
drafts must be identical after removing the fields that are *about the runner*
rather than about the paper:

* ``created_at`` / ``draft_id`` / ``usage`` -- per-run metadata;
* ``provenance.runner_id`` / ``process_audit.runner_id`` -- the runner identity;
* ``provenance.model`` and ``process_audit.duration_seconds`` -- runner facts;
* ``provenance.combined_prompt_sha256`` -- the prompt embeds this run's id, so
  the hash differs between *any* two runs, not just between runners.

Everything else, including the grounding receipt, the source identity and the
prompt hashes, has to match. If a shared layer ever grew a provider branch, one
of these fields would drift.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from hydrolitagent.cards.adapters.pdf.pymupdf_converter import PymupdfConverter
from hydrolitagent.cards.adapters.runners.openai_compatible import (
    OpenAICompatibleRunner,
)
from hydrolitagent.cards.adapters.storage.paper_store import PaperStore
from hydrolitagent.cards.application.card_workflow import generate_markdown_card_draft
from hydrolitagent.cards.domain.source_access import MARKDOWN_PREPARED

# ``app_config`` is a fixture defined in the workflow test module; importing it
# makes it available here without duplicating the asset wiring.
from test_markdown_workflow import (  # noqa: F401 - imported fixture
    WorkspaceRunner,
    _record,
    _write_pdf,
    app_config,
    grounded_output,
)


class _CapturingApiRunner(OpenAICompatibleRunner):
    """Remembers the request so the fake endpoint can answer from the paper."""

    request = None

    def run(self, request):
        self.request = request
        return super().run(request)


def _draft(result) -> dict:
    assert result["ok"], result
    paths = sorted(Path(result["literature_root"]).rglob("draft.json"))
    assert len(paths) == 1, paths
    return json.loads(paths[0].read_text(encoding="utf-8"))


def _normalize(draft: dict) -> dict:
    data = deepcopy(draft)
    for key in ("created_at", "draft_id", "usage"):
        data.pop(key, None)
    data["provenance"].pop("runner_id", None)
    data["provenance"].pop("model", None)
    data["provenance"].pop("combined_prompt_sha256", None)
    data["process_audit"].pop("runner_id", None)
    data["process_audit"].pop("duration_seconds", None)
    return data


def test_the_same_prepared_paper_yields_the_same_draft_for_each_runner(
    app_config, tmp_path
):
    pdf = _write_pdf(tmp_path / "paper.pdf")
    record = _record(pdf)
    store = PaperStore(tmp_path / "cache")

    scripted_result = generate_markdown_card_draft(
        app_config,
        record,
        converter=PymupdfConverter(),
        store=store,
        runner=WorkspaceRunner(grounded_output),
        output_root=tmp_path / "literature-scripted",
    )

    holder: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        # Answer from the paper the runner actually staged, exactly like the
        # scripted runner does, so the comparison is about the pipeline.
        answer = grounded_output(holder["runner"].request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(answer, ensure_ascii=False),
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            },
        )

    api = _CapturingApiRunner(
        base_url="https://api.example.test/v1",
        api_key="sk-test-key-123456",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    # ``run`` stores the request before it issues the HTTP call.
    holder["runner"] = api
    api_result = generate_markdown_card_draft(
        app_config,
        record,
        converter=PymupdfConverter(),
        store=store,
        runner=api,
        output_root=tmp_path / "literature-api",
    )

    scripted_draft = _draft(scripted_result)
    api_draft = _draft(api_result)

    assert scripted_draft["source_access"]["method"] == MARKDOWN_PREPARED
    assert api_draft["source_access"]["method"] == MARKDOWN_PREPARED
    assert scripted_draft["source_access"]["reading"]["verified"] is True
    assert api_draft["source_access"]["reading"]["verified"] is True

    assert scripted_draft["provenance"]["runner_id"] == "scripted"
    assert api_draft["provenance"]["runner_id"] == "openai_compatible"
    assert api_draft["usage"]["total_tokens"] == 150

    assert _normalize(api_draft) == _normalize(scripted_draft)


if __name__ == "__main__":  # pragma: no cover - manual invocation convenience
    raise SystemExit(pytest.main([__file__]))
