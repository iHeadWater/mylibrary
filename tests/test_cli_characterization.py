"""Characterisation tests for the five public ``cards`` CLI contracts.

Stage 1 of the decoupling migration is not allowed to change any external
behaviour: same commands, same JSON fields, same exit codes. These tests pin the
*shape* of two machine-readable outputs (``ai-config`` and ``paper-input``)
rather than their full contents, so they stay stable across machines while
still failing if a field disappears.

``paper-input`` needs a local Zotero with the reference item; without it the test
skips instead of pretending to have checked anything.
"""

from __future__ import annotations

import json

import pytest

from hydrolitagent.cards import cli
from hydrolitagent.cards.config import DEFAULT_PIPELINE_MODE, ConfigError
from hydrolitagent.cards.paper_input_config import load_paper_input_config
from hydrolitagent.cards.zotero import ZoteroApiError, ZoteroClient

REFERENCE_ITEM_KEY = "AWDQIE8I"

AI_CONFIG_TOP_LEVEL_KEYS = {
    "ok",
    "operation",
    "ai",
    "literature_root",
    "credentials",
}
# Fields that survive every planned migration stage.
AI_CONFIG_AI_KEYS_REQUIRED = {
    "provider",
    "model",
    "executable",
    "reasoning_effort",
    "timeout_seconds",
}
# Documented upper bound. Stage 6a removed the Poppler fields and the PDF-reader
# overrides; any *new* field still fails this test until it is registered here.
AI_CONFIG_AI_KEYS_DOCUMENTED = AI_CONFIG_AI_KEYS_REQUIRED | {
    # Stage 3b: which single-paper pipeline the next run would take.
    "pipeline",
    # Stage 4a: runner registry alias, the ids it can build, and the HTTP
    # runner's token budgets. All additive; nothing above was removed.
    "runner",
    "runners",
    "runner_limits",
    "base_url",
    "max_input_tokens",
    "max_output_tokens",
}

# Keys every READY ``paper-input`` result carries. Optional keys (``candidates``,
# ``source_url``, ``pdf.fulltext_error``) are deliberately excluded: this test
# guards against removals, not against documented additions.
PAPER_INPUT_READY_KEYS = {
    "schema_version",
    "ok",
    "operation",
    "status",
    "reason_code",
    "message",
    "library",
    "requested_item_key",
    "item",
    "pdf_attachment_count",
    "pdf",
}
PAPER_INPUT_ITEM_KEYS = {
    "item_key",
    "item_type",
    "title",
    "creators",
    "date",
    "doi",
    "url",
    "child_count",
}
PAPER_INPUT_PDF_KEYS = {
    "attachment_key",
    "filename",
    "content_type",
    "link_mode",
    "parent_key",
    "file_size_bytes",
    "sha256",
    "local_path",
}


def _run_json(argv: list[str], capsys, *, expected_exit: int = 0) -> dict:
    """Invoke the CLI in-process and decode its JSON stdout."""

    code = cli.main(argv)
    captured = capsys.readouterr()
    assert captured.out.strip(), f"`cards {' '.join(argv)}` 没有输出 JSON（exit {code}）"
    assert code == expected_exit, f"`cards {' '.join(argv)}` 退出码 {code}，期望 {expected_exit}"
    return json.loads(captured.out)


def test_ai_config_json_contract(capsys, monkeypatch) -> None:
    """``ai-config --json`` keeps its top-level and ``ai`` field sets.

    The command must stay runnable without any machine configuration or model
    CLI, so it is invoked with defaults only.
    """

    monkeypatch.delenv("CARD_PIPELINE", raising=False)
    result = _run_json(["ai-config", "--json"], capsys)

    assert set(result) == AI_CONFIG_TOP_LEVEL_KEYS, (
        "ai-config 顶层字段发生变化："
        f"多了 {sorted(set(result) - AI_CONFIG_TOP_LEVEL_KEYS)}，"
        f"少了 {sorted(AI_CONFIG_TOP_LEVEL_KEYS - set(result))}"
    )
    assert result["ok"] is True
    assert result["operation"] == "ai_config"
    assert isinstance(result["ai"], dict), "ai 字段必须是对象"
    ai_keys = set(result["ai"])
    assert AI_CONFIG_AI_KEYS_REQUIRED <= ai_keys, (
        "ai-config 的 ai 字段减少："
        f"{sorted(AI_CONFIG_AI_KEYS_REQUIRED - ai_keys)}"
    )
    assert ai_keys <= AI_CONFIG_AI_KEYS_DOCUMENTED, (
        "ai-config 出现未登记的新字段："
        f"{sorted(ai_keys - AI_CONFIG_AI_KEYS_DOCUMENTED)}"
    )
    assert result["ai"]["pipeline"] == DEFAULT_PIPELINE_MODE == "markdown", (
        "ai-config 必须显示下一次单篇制卡实际使用的管线"
    )
    # Stage 4a: ``runner`` is an alias, ``runners`` comes from the registry and
    # ``runner_limits`` bounds the HTTP runner. All three are additive.
    assert result["ai"]["runner"] == result["ai"]["provider"]
    assert "codex" in result["ai"]["runners"]
    assert set(result["ai"]["runner_limits"]) == {
        "max_input_tokens",
        "max_output_tokens",
    }


def _zotero_local_api_available() -> bool:
    """True only when the local Zotero API answers a trivial read."""

    try:
        config = load_paper_input_config()
    except (ConfigError, OSError, ValueError):
        return False
    try:
        ZoteroClient(config.zotero).get_json("/api/users/0/items?limit=1")
    except ZoteroApiError:
        return False
    return True


def test_paper_input_json_contract(capsys) -> None:
    """``paper-input --user-library`` keeps its result field sets.

    Skips when the local Zotero API is unavailable or the reference item is not
    in this machine's personal library -- a missing fixture is not a contract
    regression, and the skip is visible in the test report.
    """

    if not _zotero_local_api_available():
        pytest.skip("本机 Zotero Local API 不可用；跳过 paper-input 契约快照")

    result = _run_json(
        ["paper-input", "--user-library", "--item-key", REFERENCE_ITEM_KEY, "--json"],
        capsys,
    )

    if not result.get("ok"):
        # ``ok: false`` here means this machine cannot reach a READY input
        # (item absent, PDF not synced, library locked). That is a fixture
        # limitation, not a contract regression; a real crash would have
        # failed at JSON decoding above.
        pytest.skip(
            f"参考条目 {REFERENCE_ITEM_KEY} 在本机未达到 READY（"
            f"{result.get('reason_code')}）；跳过契约快照"
        )

    assert result["operation"] == "paper_input"
    assert result["status"] == "READY"
    assert PAPER_INPUT_READY_KEYS <= set(result), (
        "paper-input 顶层字段减少："
        f"{sorted(PAPER_INPUT_READY_KEYS - set(result))}"
    )

    item = result["item"]
    assert isinstance(item, dict), "item 字段必须是对象"
    assert PAPER_INPUT_ITEM_KEYS <= set(item), (
        f"paper-input 的 item 字段减少：{sorted(PAPER_INPUT_ITEM_KEYS - set(item))}"
    )

    pdf = result["pdf"]
    assert isinstance(pdf, dict), "pdf 字段必须是对象"
    assert PAPER_INPUT_PDF_KEYS <= set(pdf), (
        f"paper-input 的 pdf 字段减少：{sorted(PAPER_INPUT_PDF_KEYS - set(pdf))}"
    )


if __name__ == "__main__":  # pragma: no cover - manual invocation convenience
    raise SystemExit(pytest.main([__file__]))
