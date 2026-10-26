"""Wire protocol identifiers shared by every adapter.

These strings are written into generated artifacts and validated on read, so
they belong to the domain, not to any single provider module.
"""
from __future__ import annotations

GENERATION_PROTOCOL_VERSION = "evidence-card-generation-v3"

MULTI_AGENT_PROTOCOL_VERSION = "rough-card-multi-agent-v1"
LOCAL_PATH_PROTOCOL_VERSION = "rough-card-multi-agent-v2"
LEGACY_SINGLE_AGENT_PROTOCOL_VERSION = "rough-card-single-agent-v1"
SINGLE_AGENT_PROTOCOL_VERSION = "rough-card-single-agent-v2"

SUPPORTED_REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)

__all__ = [
    "GENERATION_PROTOCOL_VERSION",
    "LEGACY_SINGLE_AGENT_PROTOCOL_VERSION",
    "LOCAL_PATH_PROTOCOL_VERSION",
    "MULTI_AGENT_PROTOCOL_VERSION",
    "SINGLE_AGENT_PROTOCOL_VERSION",
    "SUPPORTED_REASONING_EFFORTS",
]
