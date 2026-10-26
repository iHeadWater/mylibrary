"""Compatibility shim for the Codex CLI runner (stage 1.6).

The implementation now lives in
``hydrolitagent/cards/adapters/runners/codex/``. This module keeps every name
that existing callers import -- public names, underscore-prefixed helpers and
plain re-exports -- so ``codex_text``, ``codex_local_pdf`` and the tests keep
working without changes.

Do not add new behaviour here. Stage 6 deletes the shim once the remaining
callers import from the ``adapters.runners.codex`` package directly.
"""
from __future__ import annotations

from hydrolitagent.cards.adapters.runners.codex import (  # noqa: F401
    DISALLOWED_GENERATION_ITEM_TYPES,
    DISALLOWED_SMOKE_ITEM_TYPES,
    SMOKE_TEST_EXPECTED_TEXT,
    SMOKE_TEST_PROMPT,
    SMOKE_TEST_VERSION,
    USAGE_FIELDS,
    CodexCliAdapter,
    CommandRunner,
    ExecutableFinder,
    PromptRunner,
    _check,
    _classify_exec_failure,
    _combined_output,
    _last_agent_message,
    _now,
    _parse_jsonl,
    _pdf_access_diagnostic,
    _run_command,
    _run_prompt_command,
    _sha256_file,
    _source_pdf_access_from_receipt,
    _terminal_failure_events,
    _unexpected_item_types,
    _usage,
    codex_proxy_environment,
    proxy_summary,
)
from hydrolitagent.cards.adapters.runners.diagnostics import (  # noqa: F401
    event_diagnostic_parts as _event_diagnostic_parts,
    safe_exec_diagnostic as _safe_exec_diagnostic,
    sanitize_diagnostic_text as _sanitize_diagnostic_text,
    timeout_text as _timeout_text,
)
from hydrolitagent.cards.card_generators.connection_guard import (  # noqa: F401
    is_reconnect_event,
)
from hydrolitagent.cards.card_generators.streaming import (  # noqa: F401
    ExecutionStopped,
    run_streaming_prompt,
)
from hydrolitagent.cards.config import CardGeneratorConfig  # noqa: F401
from hydrolitagent.cards.domain.protocol import (  # noqa: F401
    GENERATION_PROTOCOL_VERSION,
)
from hydrolitagent.cards.domain.source_access import BOUND_LOCAL_PDF_MCP  # noqa: F401
from hydrolitagent.cards.infrastructure.toml import (  # noqa: F401
    toml_string as _toml_string,
    toml_string_map as _toml_string_map,
)
from hydrolitagent.cards.progress import ProgressCallback  # noqa: F401
