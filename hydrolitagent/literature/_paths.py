"""Path helpers for the literature CLI subpackage.

Replaces dailyinfo's `paths.py` (which resolved relative to the dailyinfo
repo root). In mylibrary, the project root is three levels up from this file:
    hydrolitagent/literature/_paths.py  →  mylibrary/
"""

from pathlib import Path

# mylibrary repo root: <repo>/hydrolitagent/literature/_paths.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Runtime workspace for literature CLI outputs (bilibili covers, podcast dirs).
# Kept in mylibrary/outputs to match the existing outputs/ convention.
OUTPUT_ROOT = PROJECT_ROOT / "outputs"

# NotebookLM CLI home for zotero-notebooklm orchestration.
NOTEBOOKLM_HOME = PROJECT_ROOT / ".tmp" / "notebooklm"
