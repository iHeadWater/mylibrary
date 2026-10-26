from __future__ import annotations

from datetime import date
from pathlib import Path

from hydro_miner.config import load_config
from hydro_miner.filtering import dedupe, filter_records, match_people, score_track
from hydro_miner.models import Record, SourceRef
from hydro_miner.normalize import dates_in_text, excel_serial_to_date, title_for


CONFIG = load_config(Path(__file__).resolve().parents[1] / "configs/platform.toml.example")


def make_record(raw_text: str, kind: str = "patent", title: str = "Test") -> Record:
    dates = dates_in_text(raw_text)
    return Record(
        kind=kind,
        title=title,
        people=[],
        matched_people=[],
        dates=dates,
        date=dates[-1] if dates else None,
        status="",
        venue_or_type="",
        identifier="",
        summary="",
        track="待判断",
        source=SourceRef("book.xlsx", "sheet", 1),
        raw_text=raw_text,
    )


def test_aliases_match_same_person() -> None:
    for alias in ["张三", "Zhang San", "San Zhang"]:
        assert match_people(f"{alias} urban flood", CONFIG) == ["张三"]


def test_dates_parse_excel_serial_and_text() -> None:
    assert excel_serial_to_date(45828) == date(2025, 6, 20)
    assert date(2025, 6, 20) in dates_in_text("授权日 2025-06-20")


def test_track_keywords_are_config_driven() -> None:
    record = make_record("张三 耦合物理机制与深度学习的流域洪水预报方法研究 2026")
    track, scores, flags = score_track(record, CONFIG)
    assert track == "预警/预测"
    assert not flags
    assert scores["预警/预测"] > 0


def test_allowlist_filter_excludes_unmatched_people() -> None:
    record = make_record("陈十 深度学习 流域洪水预报 2026", title="No allowlisted person")
    main, review, excluded = filter_records([record], CONFIG)
    assert not main
    assert not review
    assert excluded[0].reason == "no_allowlisted_person"


def test_old_published_record_does_not_bypass_date() -> None:
    record = make_record("张三 水文预报 已发表 2022", title="Old record")
    main, review, excluded = filter_records([record], CONFIG)
    assert not main
    assert not review
    assert excluded[0].reason == "outside_time_rule"


def test_dedupe_by_identifier() -> None:
    one = make_record("张三 水文预报 2026 10.1234/abc", title="A")
    two = make_record("张三 水文预报 2026 10.1234/abc", title="A copy")
    one.identifier = "10.1234/abc"
    two.identifier = "10.1234/abc"
    result = dedupe([one, two])
    assert len(result) == 1
    assert len(result[0].duplicate_sources) == 1


def test_project_dedupe_prefers_title_when_identifier_differs() -> None:
    one = make_record(
        "张三 耦合物理机制与深度学习的流域洪水预报方法研究 2026",
        "project",
        "耦合物理机制与深度学习的流域洪水预报方法研究",
    )
    two = make_record(
        "张三 耦合物理机制与深度学习的流域洪水预报方法研究 2026",
        "project",
        "耦合物理机制与深度学习的流域洪水预报方法研究",
    )
    one.identifier = "8050025"
    two.identifier = "中国博士后科学基金会"
    result = dedupe([one, two])
    assert len(result) == 1
    assert "identifier_conflict_needs_review" in result[0].review_flags


def test_project_title_does_not_use_person_name() -> None:
    rule = CONFIG.record_types["project"]
    row = [
        "83",
        "1102-07120019",
        "国家自然科学基金",
        "青年科学基金",
        "耦合物理机制与深度学习的流域洪水预报方法研究",
        "张三",
        "52309010",
        "张三",
    ]
    assert title_for(row, " ".join(row), rule, CONFIG) == "耦合物理机制与深度学习的流域洪水预报方法研究"
