"""Download a paper PDF by DOI or arXiv id, with browser automation.

Thin CLI shell: the download logic lives in
``hydrolitagent/literature/download_pdf.py`` (curl-first sources, metadata,
setup check, orchestration) and ``hydrolitagent/literature/download_browser.py``
(paywalled publisher flows). This script only parses arguments and forwards to
``download_pdf.download_paper`` so the documented entry point keeps working with
the same flags and exit codes:

Usage:
  uv run python scripts/download_paper.py --doi 10.1029/2026GL125188
  uv run python scripts/download_paper.py --doi 10.1016/j.jhydrol.2026.136272 --sync
  uv run python scripts/download_paper.py --arxiv 2608.18495 --sync
  uv run python scripts/download_paper.py --doi 10.1038/s43017-026-00819-6 --resolve-only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 包已并入 hydrolitagent，加仓库根即可导入（与 paper_input.py / paper_validate.py 同款薄壳）。
sys.path[:0] = [str(ROOT)]

from hydrolitagent.literature.download_pdf import (  # noqa: E402
    DEFAULT_OUT,
    download_paper,
    setup_check,
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Download a paper PDF by DOI or arXiv id, with browser automation."
    )
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--doi", help="Paper DOI, e.g. 10.1029/2026GL125188")
    g.add_argument("--arxiv", help="arXiv id, e.g. 2608.18495")
    g.add_argument("--title",
                   help="Paper title; resolved to a DOI via Crossref (refuses "
                        "ambiguous matches and lists the candidates instead)")
    ap.add_argument("--setup-check", action="store_true",
                    help="Verify .env / Zotero API / GDrive dir, print next steps")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory")
    ap.add_argument("--resolve-only", action="store_true", help="Show metadata and exit")
    ap.add_argument("--sync", action="store_true", help="Sync to Zotero after download")
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    if args.setup_check:
        return setup_check()
    if not (args.doi or args.arxiv or args.title):
        ap.error("one of --doi / --arxiv / --title / --setup-check is required")

    return download_paper(
        doi=args.doi,
        arxiv=args.arxiv,
        out_dir=args.out,
        sync=args.sync,
        resolve_only=args.resolve_only,
        title=args.title,
    )


if __name__ == "__main__":
    sys.exit(main())
