"""Windowless Task Scheduler entry point; no dependency on the desktop conversation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from hydro_platform.config import load_config
from hydro_platform.publication import atomic_text
from hydro_platform.scheduled import scheduled_tick


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--probe-token")
    args = parser.parse_args()
    config = load_config(args.config, require_group=True)
    if args.probe_token:
        import re
        if not re.fullmatch(r"[0-9a-f]{32}", args.probe_token):
            raise ValueError("invalid probe token")
        path = config.paths.runtime_dir / "schedule-probes" / (args.probe_token + ".json")
        # Fixed no-model branch used only by the explicit scheduler integration drill.
        atomic_text(path, json.dumps({"ok": True, "probe_token": args.probe_token,
                                    "model_call_count": 0, "python": sys.executable}))
        return 0
    result = scheduled_tick(config)
    if result.get("pipeline_invoked") or not result["ok"]:
        atomic_text(config.paths.runtime_dir / "scheduler-last-result.json", json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
