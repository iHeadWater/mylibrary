from __future__ import annotations

import csv
import json
from pathlib import Path

from hydrolitagent.scholars.models import BatchResult, WebCandidate
from hydrolitagent.scholars.output import (
    FORM_HEADERS,
    write_form_summary,
    write_review_md,
    write_summary_json,
    write_web_candidates,
    write_works_by_person,
    write_works_csv,
)
from hydrolitagent.scholars.service import write_outputs

from scholars_fixtures import make_record, make_result


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.reader(stream))


def test_form_summary_headers_exact(tmp_path) -> None:
    path = tmp_path / "form.csv"
    write_form_summary(path, [make_result(works=(make_record(),))])
    rows = read_csv(path)
    assert rows[0] == FORM_HEADERS
    assert rows[1][3] == "1"
    assert rows[1][4] == "1"
    assert rows[1][5] == "待本人确认"


def test_unresolved_counts_blank_not_zero(tmp_path) -> None:
    path = tmp_path / "form.csv"
    result = make_result(
        status="ambiguous",
        identity_status="ambiguous",
        message="找到多个可能作者",
    )
    write_form_summary(path, [result])
    rows = read_csv(path)
    assert rows[1][3] == ""
    assert rows[1][4] == ""
    assert "待人工确认" in rows[1][6]


def test_bom_is_written(tmp_path) -> None:
    path = tmp_path / "form.csv"
    write_form_summary(path, [make_result()])
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_works_csv_booleans_and_detail_fields(tmp_path) -> None:
    path = tmp_path / "works.csv"
    result = make_result(
        works=(
            make_record(work_id="W1", is_retracted=True),
            make_record(work_id="W2", author_position="middle", is_corresponding=False),
        )
    )
    write_works_csv(path, [result])
    rows = read_csv(path)
    header = rows[0]
    first = dict(zip(header, rows[1]))
    second = dict(zip(header, rows[2]))
    assert first["是否第一作者"] == "是"
    assert first["是否撤稿"] == "是"
    assert first["计数原因"] == "第一作者"
    assert second["是否通讯作者"] == "否"
    assert second["计数原因"] == "未计入"
    assert "作者列表" in header
    assert "本人署名" in header


def test_summary_json_does_not_leak_api_key(tmp_path) -> None:
    path = tmp_path / "summary.json"
    batch = BatchResult(
        people=(make_result(),),
        generated_at="2026-10-26T00:00:00+00:00",
        config={"openalex": {"api_key": "secret"}},
    )
    write_summary_json(path, batch)
    text = path.read_text(encoding="utf-8")
    assert "secret" not in text
    assert json.loads(text)["schema_version"] == 1


def test_review_mentions_retraction_and_self_check_disclaimer(tmp_path) -> None:
    path = tmp_path / "review.md"
    result = make_result(works=(make_record(work_id="W1", is_retracted=True),))
    batch = BatchResult(people=(result,), generated_at="2026-10-26T00:00:00+00:00", config={})
    write_review_md(path, batch)
    text = path.read_text(encoding="utf-8")
    assert "撤稿论文" in text
    assert "自查列未由程序填写" in text


def test_write_outputs_creates_all_files(tmp_path) -> None:
    result = make_result(works=(make_record(),))
    batch = BatchResult(people=(result,), generated_at="2026-10-26T00:00:00+00:00", config={})
    outputs = write_outputs(batch, tmp_path)
    for key in (
        "form_summary_csv",
        "summary_audit_csv",
        "works_csv",
        "works_by_person_md",
        "summary_json",
        "review_md",
    ):
        assert key in outputs
        assert (tmp_path / Path(outputs[key]).name).is_file()


def test_works_by_person_lists_everything_and_reconciles(tmp_path) -> None:
    path = tmp_path / "works_by_person.md"
    result = make_result(
        works=(
            make_record(work_id="W1", title="计入论文", author_position="first"),
            make_record(
                work_id="W2",
                title="未计入论文",
                author_position="middle",
                is_corresponding=False,
            ),
        )
    )
    batch = BatchResult(people=(result,), generated_at="2026-10-26T00:00:00+00:00", config={})
    write_works_by_person(path, batch)
    text = path.read_text(encoding="utf-8")
    assert "计入论文" in text
    assert "未计入论文" in text
    assert "计入 1 篇" in text
    assert "与汇总一致" in text


def test_web_candidates_csv(tmp_path) -> None:
    path = tmp_path / "web.csv"
    write_web_candidates(
        path,
        [WebCandidate(person_name="张三", title="中文论文", year=2023, url="https://example.com")],
    )
    rows = read_csv(path)
    assert rows[1][1] == "中文论文"
    assert rows[1][6] == "low"
