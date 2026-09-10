"""Deterministic teacher-facing progress, not AI appraisal or performance scoring."""
from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from hydro_platform.activity import (
    ActivityError, canonical, clean, load_ledger, now_text, read_record, safe_path, saved_cards, write_record,
)
from hydro_platform.publication import atomic_text, text_hash
from hydro_platform.tasks import PipelineRunLock, load_task_registry


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def _code(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z0-9_]{1,100}", value) else "UNKNOWN"


def _latest_run(config):
    latest, at = None, None
    for path in (config.paths.logs_dir / "pipeline-runs").glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            stamp = _time(record.get("finished_at"))
            if record.get("status") == "ALREADY_RUNNING":
                continue
            if record.get("operation") != "run_once" or record.get("group_id") != config.zotero.group_id or stamp is None:
                continue
            if at is None or stamp > at:
                latest, at = record, stamp
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return latest


def _md(value):
    value = html.escape(clean(value) or "未知", quote=False)
    for char in "\\`*_{}[]()#|!":
        value = value.replace(char, "\\" + char)
    return value


def _actor(actor):
    if actor.get("kind") == "SYSTEM":
        return actor.get("member_id") or "系统"
    if actor.get("kind") == "ZOTERO_USER":
        return actor.get("display_name") or actor.get("username") or f"Zotero用户{actor.get('zotero_user_id')}"
    return "未知贡献者"


def _markdown(report):
    counts = report["today_counts"]
    offset = datetime.fromisoformat("2000-01-01T00:00:00" + report["utc_offset"]).tzinfo
    def display_time(value):
        stamp = _time(value)
        return stamp.astimezone(offset).strftime("%Y-%m-%d %H:%M:%S") if stamp else "未知"
    status_labels = {"COMPLETED": "已完成", "COMPLETED_WITH_PENDING": "本轮已结束，仍有等待或延后项",
                     "COMPLETED_WITH_BLOCKERS": "已结束，存在阻塞", "FAILED": "失败",
                     "CANCELLED": "已中止", "UNKNOWN": "未取得运行记录"}
    status = report["last_run"]["status"]
    lines = [f"# 科研平台每日进度 · {report['date']}", "", f"报告生成时间：{display_time(report['generated_at'])}；以下时间均为 UTC{report['utc_offset']}。",
             "", f"本日新发现论文：{counts.get('PAPER_ADDED', 0)}；新发现 PDF：{counts.get('PDF_ADDED', 0)}；新确认卡片完成：{counts.get('CARD_COMPLETED', 0)}。",
             f"当前有效粗卡：{report['valid_card_count']}；待处理/等待/阻塞事项：{len(report['open_items'])}。",
             "", "## 运行状态", "",
             f"最近统一运行：{_md(status_labels.get(status, status))}；结束时间：{display_time(report['last_run'].get('finished_at'))}。",
             f"本日是否有统一运行记录：{'是' if report['run_observed_today'] else '否，不能仅因本日报已生成就认定自动化正在运行'}。",
             f"任务清单存在：{'是' if report['task_registry_exists'] else '否，待 recover 重建'}；账本已启用：{'是' if report['ledger_initialized'] else '否，未建立贡献基线'}。",
             f"系统异常代码：{_md('，'.join(report['system_issues']) or '当前记录未报告')}。",
             f"最近一轮主题处理：{_md(report['theme_summary']['status'])}；候选数：{report['theme_summary']['candidate_count']}；已回填数：{report['theme_summary']['refined_count']}（不是正式主题审批）。",
             "", "## 本日关键事件", ""]
    if report["events"]:
        lines.extend(["| 行为 | 文献 | 贡献者/执行者 | 首次观测时间 |", "|---|---|---|---|"])
        labels = {"PAPER_ADDED": "发现新增论文", "PDF_ADDED": "发现新增/补充PDF", "CARD_COMPLETED": "确认卡片已完成", "TASK_BLOCKED": "发现处理阻塞"}
        for event in report["events"]:
            lines.append(f"| {_md(labels.get(event['type'], event['type']))} | {_md(event['title'])}（{_md(event['parent_key'])}） | {_md(_actor(event['actor']))} | {display_time(event['observed_at'])} |")
    else:
        lines.append("本日没有新关键事件；首次启用前的历史文献不计入当日贡献。")
    lines.extend(["", "## 当前待处理与阻塞", ""])
    if report["open_items"]:
        lines.extend(["| 文献 | 当前状态 | 原因代码 |", "|---|---|---|"])
        for item in report["open_items"]:
            lines.append(f"| {_md(item.get('title'))}（{_md(item.get('parent_key'))}） | {_md(item['state'])} | {_md(item['reason_code'])} |")
    else:
        lines.append("在当前可读取的任务和证据包记录中没有发现待处理事项；不代表已实时扫描 Zotero。")
    lines.extend(["", "## 解释边界", "",
        "- 事件按系统首次观测日期统计，不把发现日期冒充文献实际入库日期；原发生时间保存在 JSON 中。",
        "- CARD_COMPLETED 表示首次确认卡片已保存，可能来自草稿恢复；不代表本日新调用了模型。",
        "- 没有身份元数据时记录未知，不用论文作者、当前登录账号或最后修改者代替新增者。",
        "- 只用于掌握进度和发现阻塞，不是个人排名，也不是卡片或主题科学质量评价。",
        "- 本命令不访问 Zotero、不调用模型；任务与最近运行记录可能滞后。实际每日计划状态请用 schedule-status 查询。", ""])
    return "\n".join(lines)


def daily_report(config, *, run_report=None, now=None):
    moment = now or datetime.now(timezone.utc)
    stamp = now_text(moment)
    offset = config.activity_reporting.utc_offset_minutes
    local_zone = timezone(timedelta(minutes=offset))
    day = moment.astimezone(local_zone).date().isoformat()
    prefix = ("+" if offset >= 0 else "-") + f"{abs(offset)//60:02d}:{abs(offset)%60:02d}"
    paths = config.paths
    with PipelineRunLock(paths.lock_file.with_name(paths.lock_file.name + ".activity")):
        _, ledger = load_ledger(config)
        registry = load_task_registry(paths.tasks_file, config.zotero.group_id)
        cards, card_issues = saved_cards(config)
        events = []
        for event in (ledger or {}).get("events", {}).values():
            observed = _time(event.get("observed_at"))
            if observed is None:
                raise ActivityError("ACTIVITY_TIME_INVALID", "事件观测时间无效；未重写账本")
            if observed.astimezone(local_zone).date().isoformat() == day:
                events.append(event)
        events.sort(key=lambda item: (item["observed_at"], item["event_id"]))
        latest = run_report if run_report is not None else _latest_run(config)
        if latest is not None and latest.get("group_id") != config.zotero.group_id:
            raise ActivityError("REPORT_GROUP_MISMATCH", "运行报告不属于目标共享库")
        open_items = {}
        for key, task in registry["tasks"].items():
            if task.get("state") not in {"COMPLETED", "REMOVED"}:
                open_items[key] = {"parent_key": key, "title": clean(task.get("title")),
                                   "state": _code(task.get("state")), "reason_code": _code(task.get("reason_code"))}
            elif task.get("state") == "COMPLETED" and key not in cards:
                open_items[key] = {"parent_key": key, "title": clean(task.get("title")), "state": "BLOCKED",
                                   "reason_code": "COMPLETED_CARD_UNAVAILABLE"}
        for item in (latest or {}).get("items", []):
            if item.get("status") in {"FAILED", "BLOCKED", "WAITING", "DEFERRED"}:
                key = item.get("parent_key")
                task = registry["tasks"].get(key, {})
                # A later completed task supersedes an older run's failure.
                modified, finished = _time(task.get("updated_at")), _time((latest or {}).get("finished_at"))
                if task.get("state") == "COMPLETED" and modified and finished and modified > finished:
                    continue
                open_items[key] = {"parent_key": key, "title": clean(item.get("title")),
                    "state": _code(item["status"]), "reason_code": _code(item.get("reason_code") or item.get("error", {}).get("code"))}
        for issue in card_issues:
            key = issue["parent_key"]
            open_items[key] = {**issue, "state": "BLOCKED", "title": clean(registry["tasks"].get(key, {}).get("title"))}
        run_at = _time((latest or {}).get("finished_at"))
        theme = (latest or {}).get("theme_pipeline", {})
        theme_counts = {name: theme[name] if type(theme.get(name)) is int else "未知" for name in ("candidate_count", "refined_count")}
        report = {"schema_version": 1, "group_id": config.zotero.group_id, "date": day, "utc_offset": prefix,
                  "generated_at": stamp, "today_counts": dict(Counter(e["type"] for e in events)), "events": events,
                  "ledger_initialized": ledger is not None, "task_registry_exists": paths.tasks_file.exists(),
                  "task_registry_updated_at": registry.get("updated_at"), "valid_card_count": len(cards),
                  "task_state_counts": dict(Counter(_code(task.get("state")) for task in registry["tasks"].values())),
                  "open_items": [open_items[k] for k in sorted(open_items, key=lambda key: str(key))],
                  "last_run": {"status": _code((latest or {}).get("status")), "finished_at": (latest or {}).get("finished_at"),
                               "error_code": _code((latest or {}).get("error", {}).get("code")) if (latest or {}).get("error") else None},
                  "system_issues": ([_code(latest["error"].get("code"))] if (latest or {}).get("error") else []) +
                      [_code(row.get("code")) for row in (latest or {}).get("activity_reporting", {}).get("errors", [])],
                  "theme_summary": {"status": _code(theme.get("status")), **theme_counts},
                  "run_observed_today": bool(run_at and run_at.astimezone(local_zone).date().isoformat() == day)}
        root = paths.reports_dir
        record_path, md_path = safe_path(root, "daily", day + ".json"), safe_path(root, "daily", day + ".md")
        previous = read_record(record_path)
        existing = md_path.read_text(encoding="utf-8") if md_path.exists() else None
        if previous is not None and previous.get("report", {}).get("group_id") != config.zotero.group_id:
            raise ActivityError("REPORT_GROUP_MISMATCH", "已有日报属于其他共享库，不覆盖")
        accepted = {text_hash(previous["markdown"]), previous.get("previous_markdown_sha256")} if previous else set()
        if existing is not None and text_hash(existing) not in accepted:
            raise ActivityError("DAILY_REPORT_EDITED", "日报已有人工修改或缺少配套记录；保留文件，不覆盖")
        markdown = _markdown(report)
        # JSON is the durable record. A crash before Markdown can be repaired without AI.
        write_record(record_path, {"report": report, "markdown": markdown,
                     "previous_markdown_sha256": text_hash(existing) if existing is not None else None})
        atomic_text(md_path, markdown)
    return {"schema_version": 1, "ok": True, "operation": "daily_report", "date": day,
            "today_counts": report["today_counts"], "open_item_count": len(open_items),
            "valid_card_count": len(cards), "last_run": report["last_run"], "model_call_count": 0,
            "zotero_accessed": False, "git_modified": False, "report_path": str(md_path), "record_path": str(record_path)}
