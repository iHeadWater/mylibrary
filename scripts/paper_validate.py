"""Validate local extraction artifacts without AI clients or model configuration."""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "hydro-platform/automation/src")]
from hydro_platform.card_validation import ValidationAssets, validate_subject_card_file


def main(argv=None):
    parser = argparse.ArgumentParser(description="本地校验主体卡，输出可追踪的 PASS/FAIL 记录")
    parser.add_argument("--draft", required=True)
    parser.add_argument("--paper-input", required=True)
    parser.add_argument("--assets-root", help="另一份 hydro-platform 规则资产目录")
    parser.add_argument("--report-dir", default=os.environ.get("HYDRO_PLATFORM_VALIDATION_REPORT_DIR"),
                        help="默认在草稿旁追加保存；可用环境变量覆盖")
    args = parser.parse_args(argv)
    result = validate_subject_card_file(ValidationAssets.from_root(args.assets_root),
                                       args.draft, args.paper_input, report_dir=args.report_dir)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
