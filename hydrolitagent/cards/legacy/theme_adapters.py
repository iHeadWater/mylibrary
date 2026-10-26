"""Factories for the historical Codex theme adapters.

``themes._run_legacy`` is the only caller. It exists so migration fixtures and
already-published legacy batches can still be produced and replayed; no current
command selects it. Keeping these factories here means the live theme workflow
holds no provider name at module level or in a function body.
"""
from __future__ import annotations


def build_legacy_text_adapter(config, *, progress=None):
    """Build the legacy Codex text adapter."""

    from hydrolitagent.cards.card_generators.codex_text import CodexTextAdapter

    return CodexTextAdapter(config, progress=progress)


def build_legacy_pdf_adapter(config, *, progress=None):
    """Build the legacy Codex local-PDF adapter."""

    from hydrolitagent.cards.card_generators.codex_local_pdf import CodexLocalPdfAdapter

    return CodexLocalPdfAdapter(config, progress=progress)


__all__ = ["build_legacy_pdf_adapter", "build_legacy_text_adapter"]
