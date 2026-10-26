"""产物写出：汇总 CSV（可导出为机构表格）、审计 CSV、论文明细 CSV、JSON、复核 Markdown。"""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .models import BatchResult, PersonResult, WebCandidate
from .errors import OutputError

FORM_HEADERS = [
    "序号",
    "所属研究所",
    "姓名",
    "2021年以来本人发表的论文数量",
    "其中本人作为第一通讯作者的论文数量（如论文无通讯作者，则以第一作者计算）",
    "自查是否存在问题",
    "如自查涉及问题请补充",
]

AUDIT_HEADERS = [
    *FORM_HEADERS,
    "OpenAlexID",
    "ORCID",
    "匹配状态",
    "撤稿数",
    "不含撤稿论文数",
    "数据来源",
    "复核标记",
]

WORKS_HEADERS = [
    "序号",
    "姓名",
    "所属研究所",
    "OpenAlexID",
    "WorkID",
    "DOI",
    "标题",
    "年份",
    "发表日期",
    "类型",
    "期刊/会议",
    "本人署名",
    "作者序号",
    "作者总数",
    "作者列表",
    "作者位置",
    "是否第一作者",
    "是否通讯作者",
    "是否计入第一通讯作者",
    "计数原因",
    "是否撤稿",
    "本人单位",
    "单位匹配",
    "复核标记",
    "合并的重复条目",
    "数据来源",
    "OpenAlex URL",
]


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except Exception as exc:  # noqa: BLE001
        raise OutputError(f"写入失败：{path}：{exc}") from exc
    finally:
        try:
            Path(temp).unlink(missing_ok=True)
        except OSError:
            pass


def _csv_text(headers: list[str], rows: Iterable[list[Any]], *, bom: bool = False) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if value is None else str(value) for value in row])
    text = buffer.getvalue()
    return ("﻿" + text) if bom else text


def _yes_no(value: bool) -> str:
    return "是" if value else "否"


def _counts(result: PersonResult) -> tuple[str, str]:
    if result.status != "ok" or not result.identity.resolved:
        return "", ""
    return str(result.stats.paper_count), str(result.stats.first_or_corresponding_count)


def _review_note(result: PersonResult) -> str:
    if result.query.self_check_note:
        return result.query.self_check_note
    if result.status != "ok" or not result.identity.resolved:
        reason = result.error or result.identity.message or result.status
        return f"待人工确认：{reason}"
    return ""


def form_rows(results: Iterable[PersonResult]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for position, result in enumerate(results, start=1):
        paper_count, first_count = _counts(result)
        rows.append(
            [
                result.query.index or position,
                result.query.institute,
                result.query.name,
                paper_count,
                first_count,
                result.query.self_check,
                _review_note(result),
            ]
        )
    return rows


def audit_rows(results: Iterable[PersonResult]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for position, result in enumerate(results, start=1):
        paper_count, first_count = _counts(result)
        rows.append(
            [
                result.query.index or position,
                result.query.institute,
                result.query.name,
                paper_count,
                first_count,
                result.query.self_check,
                _review_note(result),
                "|".join(result.identity.author_ids),
                result.identity.candidate.orcid if result.identity.candidate else result.query.orcid,
                result.identity.status,
                result.stats.retracted_count if result.status == "ok" else "",
                result.stats.paper_count_excluding_retracted if result.status == "ok" else "",
                (
                    "openalex+manual"
                    if any(work.source == "manual" for work in result.works)
                    else "openalex"
                ),
                "；".join(result.review_flags),
            ]
        )
    return rows


def works_rows(results: Iterable[PersonResult]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    position = 0
    for result in results:
        for work in result.works:
            position += 1
            rows.append(
                [
                    position,
                    result.query.name,
                    result.query.institute,
                    work.author_id,
                    work.work_id,
                    work.doi,
                    work.title,
                    work.year or "",
                    work.publication_date,
                    work.work_type,
                    work.venue,
                    work.byline_name,
                    work.author_index or "",
                    work.author_count or "",
                    "、".join(work.authors),
                    work.author_position,
                    _yes_no(work.is_first_author),
                    _yes_no(work.is_corresponding),
                    _yes_no(work.counts_for_form),
                    COUNT_REASON_LABEL.get(work.count_reason, work.count_reason),
                    _yes_no(work.is_retracted),
                    "|".join(work.author_institutions),
                    _yes_no(work.institution_matched),
                    "；".join(work.flags),
                    "|".join(work.duplicate_ids),
                    work.source,
                    work.url,
                ]
            )
    return rows


def write_form_summary(path: Path, results: Iterable[PersonResult]) -> None:
    atomic_write_text(path, _csv_text(FORM_HEADERS, form_rows(results), bom=True))


def write_summary_audit(path: Path, results: Iterable[PersonResult]) -> None:
    atomic_write_text(path, _csv_text(AUDIT_HEADERS, audit_rows(results), bom=True))


def write_works_csv(path: Path, results: Iterable[PersonResult]) -> None:
    atomic_write_text(path, _csv_text(WORKS_HEADERS, works_rows(results), bom=True))


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize(item)
            for key, item in value.items()
            if str(key).casefold() not in {"api_key", "apikey"}
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value


COUNT_REASON_LABEL = {
    "first": "第一作者",
    "corresponding": "通讯作者",
    "both": "第一+通讯",
    "none": "未计入",
}


def write_works_by_person(path: Path, batch: BatchResult) -> None:
    """按人分组的可读明细，列出全部检索结果（含未计入）。"""
    lines: list[str] = [
        "# 论文明细清单",
        "",
        f"- 生成时间：{batch.generated_at}",
        "- 本清单列出全部检索结果（含未计入），用于逐篇校核汇总数字。",
        "- 计数原因：第一作者 / 通讯作者 / 第一+通讯 / 未计入。",
        "",
    ]
    for index, person in enumerate(batch.people, start=1):
        title = f"## {person.query.index or index}. {person.query.name}"
        if person.query.institute:
            title += f"（{person.query.institute}）"
        lines.extend([title, ""])
        lines.append(
            f"- 身份：{person.identity.status}；作者 ID："
            + ("、".join(person.identity.author_ids) or "-")
        )
        if person.identity.candidate and person.identity.candidate.display_name:
            lines.append(
                f"- OpenAlex：{person.identity.candidate.display_name}"
                f"（{person.identity.candidate.works_count} 篇，置信度 {person.identity.confidence or '-'}）"
            )
        if person.identity.message:
            lines.append(f"- 说明：{person.identity.message}")
        if person.error:
            lines.append(f"- 错误：{person.error}")
        if person.status == "ok":
            lines.append(
                f"- 汇总：论文 {person.stats.paper_count}；第一/通讯 {person.stats.first_or_corresponding_count}；"
                f"第一作者 {person.stats.first_author_count}；通讯作者 {person.stats.corresponding_author_count}；"
                f"撤稿 {person.stats.retracted_count}"
            )
        lines.append("")

        if not person.works:
            if person.status == "ok":
                lines.append("_没有检索到论文。_")
            else:
                lines.append("_身份未确认或查询失败，未生成论文清单；候选/原因见 `review.md`。_")
            lines.append("")
            continue

        works = sorted(
            person.works,
            key=lambda work: (work.publication_date or "", work.title),
            reverse=True,
        )
        rows: list[list[str]] = []
        for position, work in enumerate(works, start=1):
            rows.append(
                [
                    str(position),
                    work.title,
                    str(work.year or ""),
                    work.venue or "-",
                    work.byline_name or "-",
                    f"{work.author_index or '-'}/{work.author_count or '-'}",
                    work.author_position or "-",
                    _yes_no(work.is_first_author),
                    _yes_no(work.is_corresponding),
                    _yes_no(work.counts_for_form),
                    COUNT_REASON_LABEL.get(work.count_reason, work.count_reason),
                    _yes_no(work.is_retracted),
                    work.doi or "-",
                    "；".join(work.flags) or "-",
                ]
            )
        lines.extend(
            markdown_table(
                [
                    "#",
                    "标题",
                    "年份",
                    "期刊/会议",
                    "本人署名",
                    "作者序号/总数",
                    "位次",
                    "第一",
                    "通讯",
                    "计入",
                    "计数原因",
                    "撤稿",
                    "DOI",
                    "复核标记",
                ],
                rows,
            )
        )
        counted = sum(1 for work in works if work.counts_for_form)
        mismatches: list[str] = []
        if len(works) != person.stats.paper_count:
            mismatches.append(
                f"清单 {len(works)} 篇 ≠ 汇总论文 {person.stats.paper_count}"
            )
        if counted != person.stats.first_or_corresponding_count:
            mismatches.append(
                f"计入 {counted} 篇 ≠ 汇总第一/通讯 {person.stats.first_or_corresponding_count}"
            )
        lines.append("")
        if mismatches:
            lines.append("> ⚠ " + "；".join(mismatches) + "。请核对「复核标记」列。")
        else:
            lines.append(f"> 对账：清单 {len(works)} 篇，计入 {counted} 篇，与汇总一致。")
        lines.append("")

    atomic_write_text(path, "\n".join(lines))


def write_summary_json(path: Path, batch: BatchResult, *, schema_version: int = 1) -> None:
    payload = {
        "schema_version": schema_version,
        "ok": batch.ok,
        "operation": "scholars_batch",
        "status": "complete" if batch.ok else "partial",
        "generated_at": batch.generated_at,
        "config": _sanitize(batch.config),
        "totals": batch.totals(),
        "people": [person.to_dict() for person in batch.people],
        "outputs": batch.outputs,
    }
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def markdown_cell(value: str) -> str:
    text = (value or "").replace("|", r"\|")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "<br>") or "-"


def markdown_table(headers: list[str], rows: Iterable[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(markdown_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(markdown_cell(cell) for cell in row) + " |")
    return lines


def _candidate_rows(result: PersonResult) -> list[list[str]]:
    rows = []
    for candidate in result.identity.candidates:
        rows.append(
            [
                candidate.openalex_id,
                candidate.display_name,
                str(candidate.works_count),
                candidate.orcid,
                "、".join(candidate.institutions[:3]),
                str(candidate.score),
                "、".join(candidate.flags),
                candidate.url,
            ]
        )
    return rows


def write_review_md(path: Path, batch: BatchResult) -> None:
    lines: list[str] = [
        "# 论文统计 — 复核清单",
        "",
        f"- 生成时间：{batch.generated_at}",
        f"- 单位：{batch.config.get('identity', {}).get('institution_name', '')}"
        f"（{batch.config.get('identity', {}).get('institution_id', '')}）",
        f"- 时间窗口：{batch.config.get('query', {}).get('from_date', '')} 起",
        f"- 作品类型：{', '.join(batch.config.get('query', {}).get('work_types', []))}",
        "",
        "> 若启用了中文库网页检索，候选见同目录 `web_candidates.csv`，默认不计入统计。",
        "> 逐篇校核请看同目录 `works_by_person.md`（按人分组，含未计入论文）与 `works.csv`。",
        "",
        "## 总览",
        "",
        *markdown_table(
            ["序号", "姓名", "研究所", "身份状态", "论文数", "第一/通讯数", "撤稿数", "复核标记"],
            [
                [
                    str(person.query.index or index + 1),
                    person.query.name,
                    person.query.institute,
                    person.identity.status,
                    str(person.stats.paper_count) if person.status == "ok" else "-",
                    str(person.stats.first_or_corresponding_count) if person.status == "ok" else "-",
                    str(person.stats.retracted_count) if person.status == "ok" else "-",
                    "；".join(person.review_flags) or "-",
                ]
                for index, person in enumerate(batch.people)
            ],
        ),
        "",
    ]

    for person in batch.people:
        lines.extend([f"## {person.query.name}", ""])
        lines.append(
            f"- 身份：{person.identity.status}；作者 ID："
            + ("、".join(person.identity.author_ids) or "-")
        )
        if person.identity.candidate and person.identity.candidate.display_name:
            lines.append(
                f"- OpenAlex：{person.identity.candidate.display_name}"
                f"（{person.identity.candidate.works_count} 篇，置信度 {person.identity.confidence or '-'}）"
            )
        if person.identity.message:
            lines.append(f"- 说明：{person.identity.message}")
        if person.error:
            lines.append(f"- 错误：{person.error}")
        if person.status == "ok":
            lines.append(
                f"- 计数：论文 {person.stats.paper_count}；第一/通讯 {person.stats.first_or_corresponding_count}；"
                f"第一作者 {person.stats.first_author_count}；通讯作者 {person.stats.corresponding_author_count}；"
                f"撤稿 {person.stats.retracted_count}；不含撤稿论文数 {person.stats.paper_count_excluding_retracted}"
            )
        if person.review_flags:
            lines.append("- 复核标记：" + "；".join(person.review_flags))
        lines.append("")

        retracted = [work for work in person.works if work.is_retracted]
        if retracted:
            lines.extend(["### 撤稿论文", ""])
            lines.extend(
                markdown_table(
                    ["标题", "DOI", "年份", "OpenAlex"],
                    [[work.title, work.doi or "-", str(work.year or ""), work.url] for work in retracted],
                )
            )
            lines.append("")

        missing_corr = [
            work
            for work in person.works
            if "corresponding_info_missing_nonfirst" in work.flags
        ]
        if missing_corr:
            lines.extend(["### 通讯作者信息缺失（非第一作者，未计入）", ""])
            lines.extend(
                markdown_table(
                    ["标题", "作者位置", "DOI"],
                    [[work.title, work.author_position, work.doi or "-"] for work in missing_corr],
                )
            )
            lines.append("")

        if person.identity.candidates and person.identity.status != "resolved":
            lines.extend(["### 候选作者（需人工选择）", ""])
            lines.extend(
                markdown_table(
                    ["OpenAlexID", "姓名", "作品数", "ORCID", "单位", "评分", "标记", "链接"],
                    _candidate_rows(person),
                )
            )
            lines.append("")

    lines.extend(
        [
            "## 局限",
            "",
            "- OpenAlex 对中文期刊覆盖有限；中文文献请用网页检索候选或人工补充清单确认后再计入。",
            "- OpenAlex 的作者消歧可能拆分或合并；同名多候选时工具不会自动选择。",
            "- 共同第一作者无法从 OpenAlex 字段识别；共同通讯作者可识别。",
            "- `is_corresponding=false` 可能代表「无通讯作者」或「OpenAlex 未提取」，这类论文进入复核而非猜测。",
            "",
        ]
    )
    atomic_write_text(path, "\n".join(lines))


def write_web_candidates(path: Path, candidates: Iterable[WebCandidate]) -> None:
    headers = ["姓名", "标题", "作者", "来源", "年份", "URL", "置信度", "状态"]
    rows = [
        [
            candidate.person_name,
            candidate.title,
            "、".join(candidate.authors),
            candidate.source,
            candidate.year or "",
            candidate.url,
            candidate.confidence,
            candidate.status,
        ]
        for candidate in candidates
    ]
    atomic_write_text(path, _csv_text(headers, rows, bom=True))
