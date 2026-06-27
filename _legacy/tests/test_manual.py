from __future__ import annotations

from pathlib import Path

from hydro_miner.config import load_config
from hydro_miner.manual import apply_manual_records
from hydro_miner.models import Record, SourceRef
from hydro_miner.writers import record_to_dict, write_all_outputs


BASE_CONFIG = Path(__file__).resolve().parents[1] / "configs/platform.toml"


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
        matched_people=["韩鹏飞"],
        dates=[],
        date=None,
        status="",
        venue_or_type="",
        identifier="",
        summary="",
        track="待判断",
        source=SourceRef("book.xlsx", "sheet", 1),
        raw_text=f"{title} 韩鹏飞",
        review_flags=["track_unclear", "platform_relevance_needs_review", "year_only_date_needs_review"],
    )


def test_include_override_promotes_review_record_and_sets_track(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        """
[include_overrides.keep]
kind = "project"
title = "辽宁省水源地水质监测与预报预警"
track = "预警/预测"
decision_reason = "confirmed relevant"
added_at = "2026-05-20"
""",
    )
    record = make_record("辽宁省水源地水质监测与预报预警")

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
title = "吕恒-交叉人才培养经费"
decision_reason = "not science writing material"
source_note = "manual test"
added_at = "2026-05-20"
""",
    )
    record = make_record("吕恒-交叉人才培养经费")

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
[supplemental_records.video]
kind = "paper"
title = "Video-Based Rainfall Opportunistic Sensing in Hydrology: A Light-weight Machine Learning Approach"
people = ["李昱", "金勇成"]
status = "在审"
track = "监测"
summary = "CIEGA-NET video rainfall sensing."
decision_reason = "manual supplement"
added_at = "2026-05-20"
""",
    )

    main, review, excluded = apply_manual_records([], [], [], config)

    assert not review
    assert not excluded
    assert main[0].matched_people == ["李昱", "金勇成"]
    assert main[0].manual_decision == "supplemental"
    assert main[0].track == "监测"


def test_manual_metadata_is_written_to_outputs(tmp_path: Path) -> None:
    attachment = tmp_path / "patent.pdf"
    config = make_config(
        tmp_path,
        f"""
[supplemental_records.wang]
kind = "paper"
title = "王泽 WRR 视觉水位解译论文（题名待确认）"
people = ["王泽"]
date = "2025-01-01"
status = "已发表"
venue_or_type = "Water Resources Research"
identifier = "10.1029/2025WR042686"
track = "监测"
summary = "SAM and SOFI water level interpretation."
evidence_links = ["https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2025WR042686"]
review_flags = ["title_needs_confirmation"]
decision_reason = "manual paper supplement"
added_at = "2026-05-20"

[supplemental_records.pdf_patent]
kind = "patent"
title = "补充材料专利证书（题名待确认）"
people = ["张弛"]
status = "授权/证书"
track = "待判断"
attachment = "{attachment}"
review_flags = ["title_needs_confirmation"]
decision_reason = "manual patent supplement"
added_at = "2026-05-20"
""",
    )

    main, review, excluded = apply_manual_records([], [], [], config)
    outputs = write_all_outputs(main, review, excluded, config, [])
    records_text = outputs["records_jsonl"].read_text(encoding="utf-8")
    materials_text = outputs["materials"].read_text(encoding="utf-8")
    paper = next(record for record in main if record.kind == "paper")
    patent = next(record for record in main if record.kind == "patent")

    assert record_to_dict(paper)["identifier"] == "10.1029/2025WR042686"
    assert record_to_dict(patent)["attachment"] == str(attachment)
    assert "10.1029/2025WR042686" in records_text
    assert "人工补充" in materials_text
    assert str(attachment) in materials_text
