from __future__ import annotations

import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from hydro_platform.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
