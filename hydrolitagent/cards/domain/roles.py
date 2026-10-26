"""Card workflow role names.

These six roles are still required by the current ``local_path`` workflow
(``card_generation._validate_workflow_result``) and by configuration validation
(``config._validate_card_workflow``); they are not historical residue.
"""
from __future__ import annotations

REQUIRED_CARD_WORKFLOW_ROLES = (
    "fact_extractor_a",
    "fact_extractor_b",
    "fact_adjudicator",
    "critical_analyst",
    "card_synthesizer",
    "adversarial_reviewer",
)

__all__ = ["REQUIRED_CARD_WORKFLOW_ROLES"]
