from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from .config import AppConfig
from .models import ExcludedRecord, Record


def date_text(value: date | None) -> str:
    return value.isoformat() if value else ""


def source_text(record: Record) -> str:
    return "; ".join(source.label() for source in record.all_sources())


def record_to_dict(record: Record) -> dict[str, object]:
    return {
        "kind": record.kind,
        "title": record.title,
        "people": record.people,
        "matched_people": record.matched_people,
        "date": date_text(record.date),
        "dates": [d.isoformat() for d in record.dates],
        "status": record.status,
        "venue_or_type": record.venue_or_type,
        "identifier": record.identifier,
        "summary": record.summary,
        "track": record.track,
        "source": record.source.label(),
        "duplicate_sources": [source.label() for source in record.duplicate_sources],
        "evidence_links": record.evidence_links,
        "review_flags": record.review_flags,
        "track_scores": record.track_scores,
        "raw_text": record.raw_text,
        "manual_decision": record.manual_decision,
        "decision_reason": record.decision_reason,
        "attachment": record.attachment,
        "source_note": record.source_note,
        "added_at": record.added_at,
    }


def write_jsonl(records: list[Record], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record_to_dict(record), ensure_ascii=False) + "\n")


def write_records_csv(records: list[Record], path: Path) -> None:
    fields = [
        "kind",
        "track",
        "title",
        "matched_people",
        "date",
        "status",
        "venue_or_type",
        "identifier",
        "summary",
        "review_flags",
        "manual_decision",
        "decision_reason",
        "attachment",
        "source_note",
        "added_at",
        "source",
        "evidence_links",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "kind": record.kind,
                    "track": record.track,
                    "title": record.title,
                    "matched_people": "、".join(record.matched_people),
                    "date": date_text(record.date),
                    "status": record.status,
                    "venue_or_type": record.venue_or_type,
                    "identifier": record.identifier,
                    "summary": record.summary,
                    "review_flags": "、".join(record.review_flags),
                    "manual_decision": record.manual_decision,
                    "decision_reason": record.decision_reason,
                    "attachment": record.attachment,
                    "source_note": record.source_note,
                    "added_at": record.added_at,
                    "source": source_text(record),
                    "evidence_links": " ".join(record.evidence_links),
                }
            )


def write_excluded_csv(excluded: list[ExcludedRecord], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "reason",
                "kind",
                "source",
                "title",
                "raw_text",
                "decision_reason",
                "source_note",
                "added_at",
            ],
        )
        writer.writeheader()
        for item in excluded:
            writer.writerow(
                {
                    "reason": item.reason,
                    "kind": item.kind,
                    "source": item.source.label(),
                    "title": item.title,
                    "raw_text": item.raw_text,
                    "decision_reason": item.decision_reason,
                    "source_note": item.source_note,
                    "added_at": item.added_at,
                }
            )


def kind_label(kind: str) -> str:
    return {"paper": "论文", "patent": "专利", "project": "项目"}.get(kind, kind)


def compact_text(value: str, max_chars: int = 180) -> str:
    text = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def markdown_cell(value: str) -> str:
    text = value.replace("|", r"\|")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    return text or "-"


def markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["_暂无条目。_"]
    lines = [
        "| " + " | ".join(markdown_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(markdown_cell(cell) for cell in row) + " |")
    return lines


def time_status_text(record: Record) -> str:
    parts = []
    if record.date:
        parts.append(record.date.isoformat())
    if record.status:
        parts.append(record.status)
    return "；".join(parts) if parts else "待确认"


def venue_identifier_text(record: Record) -> str:
    parts = []
    if record.venue_or_type:
        parts.append(record.venue_or_type)
    if record.identifier:
        parts.append(record.identifier)
    return compact_text("；".join(parts), 90)


def material_text(record: Record, max_chars: int = 180) -> str:
    return compact_text(record.summary or record.raw_text, max_chars)


def source_short_text(record: Record) -> str:
    labels = []
    for source in record.all_sources():
        labels.append(f"{source.sheet} row {source.row}")
    return compact_text("；".join(labels), 90)


def manual_label(record: Record) -> str:
    labels = {
        "include": "人工确认纳入",
        "supplemental": "人工补充",
    }
    label = labels.get(record.manual_decision, record.manual_decision)
    parts = [part for part in [label, record.decision_reason, record.source_note] if part]
    return compact_text("；".join(parts), 120)


def attachment_link(path: str) -> str:
    if not path:
        return ""
    return f"[附件](<{path}>)"


def evidence_attachment_text(record: Record) -> str:
    parts = [*record.evidence_links]
    if record.attachment:
        parts.append(attachment_link(record.attachment))
    return compact_text("；".join(parts), 160)


def record_table(records: list[Record], *, include_track: bool = False, include_source: bool = False) -> list[str]:
    headers = ["类型", "题名", "相关人员", "时间/状态", "刊物/类型/编号", "可写内容", "证据/附件", "人工标识", "待确认"]
    if include_track:
        headers.insert(1, "主线")
    if include_source:
        headers.append("表格来源")

    rows = []
    for record in records:
        row = [
            kind_label(record.kind),
            record.title,
            "、".join(record.matched_people),
            time_status_text(record),
            venue_identifier_text(record),
            material_text(record),
            evidence_attachment_text(record),
            manual_label(record),
            "、".join(record.review_flags),
        ]
        if include_track:
            row.insert(1, record.track)
        if include_source:
            row.append(source_short_text(record))
        rows.append(row)
    return markdown_table(headers, rows)


def person_summary_table(records: list[Record], config: AppConfig) -> list[str]:
    grouped: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        for person in record.matched_people:
            grouped[person].append(record)

    rows = []
    ordered_people = [*config.people_allowlist]
    ordered_people.extend(sorted(person for person in grouped if person not in config.people_allowlist))
    for person in ordered_people:
        group = grouped.get(person, [])
        if not group:
            continue
        kind_counts = Counter(record.kind for record in group)
        track_counts = Counter(record.track for record in group)
        rows.append(
            [
                person,
                "，".join(f"{kind_label(kind)}{kind_counts[kind]}" for kind in ["paper", "patent", "project"] if kind_counts[kind]),
                "，".join(f"{track}{count}" for track, count in track_counts.items()),
                "；".join(compact_text(record.title, 36) for record in group[:5]),
            ]
        )
    return markdown_table(["人员", "成果数", "主线分布", "代表条目"], rows)


def status_summary(records: list[Record]) -> list[str]:
    kind_counts = Counter(record.kind for record in records)
    manual_counts = Counter(record.manual_decision for record in records if record.manual_decision)
    status_counts = Counter()
    for record in records:
        for term in ["已发表", "录用", "在审", "返修", "授权", "受理", "申请", "在研"]:
            if term in record.status or term in record.raw_text:
                status_counts[term] += 1
    lines = []
    for kind in ["paper", "patent", "project"]:
        if kind_counts[kind]:
            lines.append(f"- {kind_label(kind)}：{kind_counts[kind]}")
    if status_counts:
        lines.append("- 状态：" + "，".join(f"{key} {value}" for key, value in status_counts.items()))
    if manual_counts:
        labels = {"include": "人工确认纳入", "supplemental": "人工补充"}
        lines.append("- 人工处理：" + "，".join(f"{labels.get(key, key)} {value}" for key, value in manual_counts.items()))
    return lines


def contribution_sentence(track: str, records: list[Record], config: AppConfig) -> str:
    titles = "、".join(record.title for record in records[:3])
    if not records:
        return ""
    return (
        f"在{track}方向，平台已形成以{titles}等为代表的阶段性成果，"
        "为“数据感知—模拟预警—智能调控”链条提供了论文、专利和项目支撑。"
    )


def record_bullet(record: Record) -> list[str]:
    lines = [
        f"- **{record.title}**（{kind_label(record.kind)}；{record.status or '状态待确认'}；{date_text(record.date) or '时间待确认'}）"
    ]
    details = []
    if record.matched_people:
        details.append("相关人员：" + "、".join(record.matched_people))
    if record.venue_or_type:
        details.append("来源/类型：" + record.venue_or_type)
    if record.identifier:
        details.append("编号：" + record.identifier)
    details.append("证据：" + source_text(record))
    lines.append("  - " + "；".join(details))
    innovation = record.summary or record.raw_text[:220]
    lines.append(f"  - 创新点/内容：{innovation}")
    if record.review_flags:
        lines.append("  - 待确认：" + "、".join(record.review_flags))
    return lines


def write_materials_markdown(records: list[Record], review: list[Record], config: AppConfig, path: Path) -> None:
    lines = [
        "# 平台科研写作素材",
        "",
        f"- 平台：{config.platform_name}",
        "- 说明：本文件由配置化规则自动筛选生成，Markdown 侧重快速阅读和统稿，正式写入报告前仍需人工复核。",
        "- 使用建议：先看各主线成果表确定可写条目，再看按人员索引补齐老师线索；完整字段见 `records.csv`。",
        "",
        "## 总览",
        "",
        *status_summary(records),
        "",
    ]

    grouped: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        grouped[record.track].append(record)

    for track in [*config.tracks.keys(), "待判断"]:
        group = grouped.get(track, [])
        if not group:
            continue
        prompt = config.tracks.get(track).prompt if track in config.tracks else ""
        lines.extend([f"## {track}", "", contribution_sentence(track, group, config), ""])
        if prompt:
            lines.extend([f"- 写作提示：{prompt}", ""])
        lines.extend(["### 代表成果", ""])
        lines.extend(record_table(group, include_source=True))
        lines.append("")

    if records:
        lines.extend(["## 按人员索引", "", "用于快速看每位老师可贡献到哪条主线；同一成果涉及多人时会在多人名下重复计入。", ""])
        lines.extend(person_summary_table(records, config))
        lines.append("")

    if review:
        lines.extend(["## 待确认", "", "这些条目命中了人员和时间规则，但平台相关性、主线归类或字段完整性仍需要人工判断。", ""])
        lines.extend(record_table(review, include_track=True, include_source=True))
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_review_markdown(review: list[Record], path: Path) -> None:
    lines = ["# 待确认条目", "", "- 这些条目命中了人员和时间规则，但平台相关性或主线归类不够明确。", ""]
    lines.extend(record_table(review, include_track=True, include_source=True))
    path.write_text("\n".join(lines), encoding="utf-8")


def write_all_outputs(
    records: list[Record],
    review: list[Record],
    excluded: list[ExcludedRecord],
    config: AppConfig,
    manifest: list[dict[str, str]],
) -> dict[str, Path]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = config.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs = {
        "materials": config.output_dir / "平台科研写作素材.md",
        "records_jsonl": config.output_dir / "records.jsonl",
        "records_csv": config.output_dir / "records.csv",
        "review": config.output_dir / "review_queue.md",
        "excluded": config.output_dir / "excluded_records.csv",
        "manifest": manifest_path,
    }
    all_records = [*records, *review]
    write_materials_markdown(records, review, config, outputs["materials"])
    write_jsonl(all_records, outputs["records_jsonl"])
    write_records_csv(all_records, outputs["records_csv"])
    write_review_markdown(review, outputs["review"])
    write_excluded_csv(excluded, outputs["excluded"])
    return outputs
