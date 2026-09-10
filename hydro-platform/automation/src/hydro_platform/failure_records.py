from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def save_failure_record(logs_dir: Path, command: str, item_key: str, result: dict[str, Any]) -> Path:
    """Persist only the already-redacted public failure, never raw CLI streams."""
    captured_at = datetime.now(timezone.utc)
    payload = {
        "schema_version": 1,
        "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
        "command": command,
        "item_key": item_key,
        "result": result,
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"generation-failure-{captured_at:%Y%m%dT%H%M%S}-{uuid4().hex}.json"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(serialized)
    return path
