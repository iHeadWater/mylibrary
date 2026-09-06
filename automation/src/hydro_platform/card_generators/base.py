from __future__ import annotations

from typing import Any, Protocol


class CardGeneratorAdapter(Protocol):
    """Runtime boundary shared by supported evidence-card generators."""

    def preflight(self) -> dict[str, Any]:
        """Check whether the configured generator can be used safely."""

        ...

    def smoke_test(self) -> dict[str, Any]:
        """Run one bounded model call without domain data or repository writes."""

        ...
