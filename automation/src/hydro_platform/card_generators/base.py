from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class CardGeneratorAdapter(Protocol):
    """Runtime boundary shared by supported evidence-card generators."""

    def preflight(self) -> dict[str, Any]:
        """Check whether the configured generator can be used safely."""

        ...

    def smoke_test(self) -> dict[str, Any]:
        """Run one bounded model call without domain data or repository writes."""

        ...

    def generate(
        self,
        prompt: str,
        *,
        working_directory: Path,
        source_pdf_path: Path,
        zotero_parent_key: str,
        output_schema_path: Path,
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout_seconds: float | None = None,
        run_label: str | None = None,
    ) -> dict[str, Any]:
        """Run one isolated model role without writing the repository."""

        ...
