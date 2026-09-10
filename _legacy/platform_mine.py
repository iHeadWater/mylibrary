#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from hydro_miner.config import load_config
from hydro_miner.enrich import enrich_records
from hydro_miner.extract_excel import export_sheets, read_workbook
from hydro_miner.filtering import filter_records
from hydro_miner.manual import apply_manual_records
from hydro_miner.normalize import normalize_records
from hydro_miner.writers import write_all_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine hydrology platform research outputs.")
    parser.add_argument("--config", default="configs/platform.toml", help="Path to TOML config.")
    parser.add_argument("--enrich", action="store_true", help="Enable scholarly API enrichment for papers.")
    parser.add_argument("--output-dir", help="Override output directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.output_dir:
        output_dir = Path(args.output_dir)
        config.output_dir = output_dir if output_dir.is_absolute() else (config.repo_root / output_dir).resolve()

    sheets = []
    missing = []
    for source in config.input_files:
        if not source.exists():
            missing.append(str(source))
            continue
        sheets.extend(read_workbook(source))

    manifest = export_sheets(sheets, config.output_dir)
    records = normalize_records(sheets, config)
    main_records, review_records, excluded = filter_records(records, config)
    main_records, review_records, excluded = apply_manual_records(main_records, review_records, excluded, config)

    if args.enrich or config.enrichment.enabled:
        enrich_records([*main_records, *review_records], config.enrichment)

    outputs = write_all_outputs(main_records, review_records, excluded, config, manifest)

    print(f"Loaded sheets: {len(sheets)}")
    print(f"Normalized records: {len(records)}")
    print(f"Main records: {len(main_records)}")
    print(f"Review records: {len(review_records)}")
    print(f"Excluded records: {len(excluded)}")
    if missing:
        print("Missing input files:")
        for path in missing:
            print(f"- {path}")
    print("Outputs:")
    for path in outputs.values():
        print(path)


if __name__ == "__main__":
    main()
