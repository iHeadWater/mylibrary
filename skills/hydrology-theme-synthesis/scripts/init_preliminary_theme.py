#!/usr/bin/env python3
"""Create a screening-only preliminary hydrology theme."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = {"small_sample", "large_corpus", "hybrid"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preliminary-theme-ref", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--discovery-route", choices=sorted(ROUTES), required=True)
    parser.add_argument("--workflow-run-ref", action="append", default=[])
    parser.add_argument("--as-of-date", default=str(date.today()))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    template = (ROOT / "assets" / "preliminary-theme-template.md").read_text(encoding="utf-8-sig")
    values = {
        "PRELIMINARY_THEME_REF": args.preliminary_theme_ref,
        "TITLE": args.title,
        "DISCOVERY_ROUTE": args.discovery_route,
        "WORKFLOW_RUN_REFS": json.dumps(args.workflow_run_ref, ensure_ascii=False, separators=(",", ":")),
        "AS_OF_DATE": args.as_of_date,
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value.replace('"', '\\"') if key != "WORKFLOW_RUN_REFS" else value)

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.rstrip() + "\n", encoding="utf-8")
    print(target)
    print("NOTICE: preliminary theme is screening-only until a human decision creates an established theme")


if __name__ == "__main__":
    main()
