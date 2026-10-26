"""Codex CLI runner subpackage.

Split out of ``card_generators/codex_cli.py`` in stage 1.6. The old module keeps
working as a re-export shim; new code should import from here.

Layout:

* ``constants`` -- smoke probe strings and allow-lists
* ``common``    -- tiny shared helpers (timestamp, check rows, file digest)
* ``process``   -- subprocess runners and their type aliases
* ``events``    -- JSONL decoding, failure classification, usage extraction
* ``receipts``  -- legacy bound-PDF MCP receipt interpretation
* ``preflight`` -- executable/version/login/PDF-reader dependency checks
* ``smoke``     -- the single tiny model probe
* ``adapter``   -- ``CodexCliAdapter`` wiring and record builders
* ``proxy``     -- re-export of the existing proxy helpers
"""
from __future__ import annotations

from hydrolitagent.cards.adapters.runners.codex.adapter import CodexCliAdapter
from hydrolitagent.cards.adapters.runners.codex.common import (
    _check,
    _now,
    _sha256_file,
)
from hydrolitagent.cards.adapters.runners.codex.constants import (
    DISALLOWED_GENERATION_ITEM_TYPES,
    DISALLOWED_SMOKE_ITEM_TYPES,
    SMOKE_TEST_EXPECTED_TEXT,
    SMOKE_TEST_PROMPT,
    SMOKE_TEST_VERSION,
    USAGE_FIELDS,
)
from hydrolitagent.cards.adapters.runners.codex.events import (
    _classify_exec_failure,
    _combined_output,
    _last_agent_message,
    _parse_jsonl,
    _terminal_failure_events,
    _unexpected_item_types,
    _usage,
)
from hydrolitagent.cards.adapters.runners.codex.preflight import run_preflight
from hydrolitagent.cards.adapters.runners.codex.process import (
    CommandRunner,
    ExecutableFinder,
    PromptRunner,
    _run_command,
    _run_prompt_command,
)
from hydrolitagent.cards.adapters.runners.codex.proxy import (
    LOCAL_BYPASS,
    PROXY_VARIABLES,
    codex_proxy_environment,
    proxy_bypass,
    proxy_summary,
)
from hydrolitagent.cards.adapters.runners.codex.receipts import (
    _pdf_access_diagnostic,
    _source_pdf_access_from_receipt,
)
from hydrolitagent.cards.adapters.runners.codex.smoke import (
    build_smoke_failure,
    run_smoke_test,
)

__all__ = [
    "DISALLOWED_GENERATION_ITEM_TYPES",
    "DISALLOWED_SMOKE_ITEM_TYPES",
    "LOCAL_BYPASS",
    "PROXY_VARIABLES",
    "SMOKE_TEST_EXPECTED_TEXT",
    "SMOKE_TEST_PROMPT",
    "SMOKE_TEST_VERSION",
    "USAGE_FIELDS",
    "CodexCliAdapter",
    "CommandRunner",
    "ExecutableFinder",
    "PromptRunner",
    "build_smoke_failure",
    "codex_proxy_environment",
    "proxy_bypass",
    "proxy_summary",
    "run_preflight",
    "run_smoke_test",
    "_check",
    "_classify_exec_failure",
    "_combined_output",
    "_last_agent_message",
    "_now",
    "_parse_jsonl",
    "_pdf_access_diagnostic",
    "_run_command",
    "_run_prompt_command",
    "_sha256_file",
    "_source_pdf_access_from_receipt",
    "_terminal_failure_events",
    "_unexpected_item_types",
    "_usage",
]
