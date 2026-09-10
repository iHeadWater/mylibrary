#!/usr/bin/env python3
"""Create a traceable hydrology literature-to-theme workflow run."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = {"small_sample", "large_corpus", "hybrid"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--intended-use", default="")
    parser.add_argument("--route", choices=sorted(ROUTES), required=True)
    parser.add_argument("--as-of-date", default=str(date.today()))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    template = (ROOT / "assets" / "workflow-run-template.md").read_text(encoding="utf-8-sig")
    values = {
        "WORKFLOW_REF": args.workflow_ref,
        "TITLE": args.title,
        "QUESTION": args.question,
        "INTENDED_USE": args.intended_use,
        "ROUTE": args.route,
        "AS_OF_DATE": args.as_of_date,
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value.replace('"', '\\"'))

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.rstrip() + "\n", encoding="utf-8")
    print(target)
    print(f"route={args.route}")
    print("NOTICE: draft structure created; complete route evidence and run validation before handoff")


if __name__ == "__main__":
    main()
