from __future__ import annotations

from pathlib import Path

from hydro_miner.config import load_config
from hydro_miner.manual import apply_manual_records
from hydro_miner.models import Record, SourceRef
from hydro_miner.writers import record_to_dict, write_all_outputs


BASE_CONFIG = Path(__file__).resolve().parents[1] / "configs/platform.toml.example"


def make_config(tmp_path: Path, text: str):
    config = load_config(BASE_CONFIG)
    config.manual_records_path = tmp_path / "manual_records.toml"
    config.output_dir = tmp_path / "outputs"
    config.manual_records_path.write_text(text, encoding="utf-8")
    return config


def make_record(title: str, kind: str = "project") -> Record:
    return Record(
        kind=kind,
        title=title,
        people=[],
        matched_people=["张三"],
        dates=[],
        date=None,
        status="",
        venue_or_type="",
        identifier="",
        summary="",
        track="待判断",
        source=SourceRef("book.xlsx", "sheet", 1),
        raw_text=f"{title} 张三",
        review_flags=["track_unclear", "platform_relevance_needs_review", "year_only_date_needs_review"],
    )


def test_include_override_promotes_review_record_and_sets_track(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        """
[include_overrides.keep]
kind = "project"
title = "示例项目 A"
track = "预警/预测"
decision_reason = "confirmed relevant"
added_at = "2026-05-20"
""",
    )
    record = make_record("示例项目 A")

    main, review, excluded = apply_manual_records([], [record], [], config)

    assert not review
    assert not excluded
    assert main[0].track == "预警/预测"
    assert main[0].manual_decision == "include"
    assert main[0].decision_reason == "confirmed relevant"
    assert main[0].review_flags == ["year_only_date_needs_review"]


def test_exclude_override_removes_review_record_and_records_reason(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        """
[exclude_overrides.drop]
kind = "project"
title = "张三-人才培养经费"
decision_reason = "not science writing material"
source_note = "manual test"
added_at = "2026-05-20"
""",
    )
    record = make_record("张三-人才培养经费")

    main, review, excluded = apply_manual_records([], [record], [], config)

    assert not main
    assert not review
    assert len(excluded) == 1
    assert excluded[0].reason == "manual_excluded_for_science_writing"
    assert excluded[0].decision_reason == "not science writing material"


def test_supplemental_record_bypasses_allowlist(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        """
[supplemental_records.patent]
kind = "patent"
title = "一种视频测雨方法"
people = ["李四", "王五"]
status = "受理"
track = "监测"
summary = "Video rainfall sensing patent."
decision_reason = "manual supplement"
added_at = "2026-05-20"
""",
    )

    main, review, excluded = apply_manual_records([], [], [], config)

    assert not review
    assert not excluded
    assert main[0].matched_people == ["李四", "王五"]
    assert main[0].manual_decision == "supplemental"
    assert main[0].track == "监测"


def test_manual_metadata_is_written_to_outputs(tmp_path: Path) -> None:
    attachment = tmp_path / "patent.pdf"
    config = make_config(
        tmp_path,
        f"""
[supplemental_records.pdf_patent]
kind = "patent"
title = "补充材料专利证书（题名待确认）"
people = ["张三"]
status = "授权/证书"
track = "待判断"
identifier = "ZL2025000001"
attachment = "{attachment.as_posix()}"
review_flags = ["title_needs_confirmation"]
decision_reason = "manual patent supplement"
added_at = "2026-05-20"
""",
    )

    main, review, excluded = apply_manual_records([], [], [], config)
    outputs = write_all_outputs(main, review, excluded, config, [])
    records_text = outputs["records_jsonl"].read_text(encoding="utf-8")
    materials_text = outputs["materials"].read_text(encoding="utf-8")
    patent = next(record for record in main if record.kind == "patent")

    assert record_to_dict(patent)["identifier"] == "ZL2025000001"
    assert record_to_dict(patent)["attachment"] == str(attachment)
    assert "ZL2025000001" in records_text
    assert "人工补充" in materials_text
    assert str(attachment) in materials_text
