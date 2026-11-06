"""What makes a theme page readable, checked by code instead of trusted.

A theme page is read by a person, not by a program. The failure this module
guards against is not a wrong number -- grounding already covers that -- it is a
page that is technically complete and unreadable: the workflow's own vocabulary
(`evidence_id`, `EV-` ids, 「逐项关联」) leaking into the prose, a document that
opens with revision bookkeeping instead of a finding, and paragraphs built out
of five parenthetical citations that cut every clause in half (#33).

Every rule here is objective and cheap: a token list, a heading depth, a length
of the lead paragraph, a per-paragraph citation count. Nothing judges the
science. A rejection is worded so the same model can fix it in one round.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from hydrolitagent.cards.domain.violations import Violation

# The lead paragraph has to carry a finding, not a label. Eighty characters is
# shorter than any useful summary and longer than 「本候选……（v2）」.
MIN_LEAD_CHARS = 80
# The entry is an entry, not the first third of the article. Kept generous: a
# three-paragraph opening on a dense topic runs long, and rejecting a good entry
# over a couple of characters costs a whole model call.
MAX_LEAD_CHARS = 900
# A reader who does not already know the field must be able to start here, so
# the opening speaks about the phenomenon, not about the vocabulary.
LEAD_TERMS = ("RF", "SF", "OVD", "级联", "共因", "容量失效", "归因", "口径")
# A theme name is a signpost, not a paper subtitle.
MAX_TITLE_CHARS = 30
# Three parenthetical years in one paragraph is already dense; more turns prose
# into a citation list.
MAX_CITATIONS_PER_PARAGRAPH = 3
# ``####`` and deeper means the answer is tabulating, not writing.
MAX_HEADING_LEVEL = 3

# Openings that turn a finding into a change log: the prompt forbids them and a
# reader does not want them.
_BOOKKEEPING = ("修订名称", "范围界定", "本候选", "经本轮精读")

_MACHINE_TOKENS = (
    "evidence_id",
    "逐项关联",
    "【原文】",
    "【推理】",
    "paper_tasks",
    "reuse_reading_id",
)
_EVIDENCE_ID = re.compile(r"EV-[A-Z0-9]{4,}")
_CITATION = re.compile(r"（\s*\d{4}[a-z]?\s*）")
_HEADING = re.compile(r"^(#{1,6})\s+\S")
_TERM = {term: re.compile(rf"(?<![A-Za-z]){term}(?![A-Za-z])" if term.isascii()
                          else re.escape(term)) for term in LEAD_TERMS}
_QUESTION = "？"


@dataclass(frozen=True)
class ProseAudit:
    """A prose review shaped like a reading audit, so one repair loop serves both."""

    violations: tuple[Violation, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)
    # Present so the shared repair planner can ask for them without branching.
    reading: None = None
    coverage: None = None


def review(output: Any) -> ProseAudit:
    """Check a refinement answer: readable prose plus a non-empty audit record."""

    if not isinstance(output, Mapping):
        return ProseAudit((Violation(
            "THEME_PROSE_MISSING", "revised_markdown", "答案不是 JSON 对象"),))

    violations: list[Violation] = []
    body = output.get("revised_markdown")
    audit = output.get("audit_markdown")
    if not isinstance(audit, str) or not audit.strip():
        violations.append(Violation(
            "THEME_PROSE_MISSING_AUDIT", "audit_markdown",
            "审计记录为空；修订对照、证据归属与来源对应要单独写在这个字段里",
        ))
    if not isinstance(body, str) or not body.strip():
        violations.append(Violation(
            "THEME_PROSE_MISSING", "revised_markdown", "主题正文为空"))
        return ProseAudit(tuple(violations))
    violations.extend(_review_body(body))
    return ProseAudit(tuple(violations))


def _review_body(body: str) -> list[Violation]:
    found: list[Violation] = []

    for token in _MACHINE_TOKENS:
        if token in body:
            found.append(Violation(
                "THEME_PROSE_MACHINE_TOKEN", "revised_markdown",
                f"正文出现了工作流字样「{token}」；它只属于审计记录，正文要用人话说",
            ))
    leaked = sorted(set(_EVIDENCE_ID.findall(body)))
    if leaked:
        found.append(Violation(
            "THEME_PROSE_MACHINE_TOKEN", "revised_markdown",
            "正文出现了证据编号 " + "、".join(leaked[:3]) + "；请改成「作者（年）」",
        ))

    lines = body.splitlines()
    heading_levels = [
        len(match.group(1)) for line in lines if (match := _HEADING.match(line))
    ]
    if heading_levels and max(heading_levels) > MAX_HEADING_LEVEL:
        found.append(Violation(
            "THEME_PROSE_HEADING_DEPTH", "revised_markdown",
            f"小标题最多三级，出现了 {max(heading_levels)} 级；层级一多就又成了清单",
        ))

    lead = _lead_paragraph(lines)
    opening = next((token for token in _BOOKKEEPING if token in lead), None)
    if len(lead.strip()) < MIN_LEAD_CHARS or opening is not None:
        found.append(Violation(
            "THEME_PROSE_NO_SUMMARY", "revised_markdown",
            (
                f"开头的「{opening}」是修订记录，不是内容：第一段要直接说清这个主题在问什么、"
                "最硬的结论、最大的不确定"
            ) if opening is not None else (
                f"正文第一个小标题之前应有至少 {MIN_LEAD_CHARS} 字的开头段落，"
                "说清这个主题在问什么、最硬的结论、最大的不确定"
            ),
            expected=f"≥{MIN_LEAD_CHARS} 字的摘要段",
            actual=f"{len(lead.strip())} 字",
        ))

    found.extend(_review_lead(lead))

    for number, paragraph in enumerate(_paragraphs(lines), start=1):
        count = len(_CITATION.findall(paragraph))
        if count > MAX_CITATIONS_PER_PARAGRAPH:
            found.append(Violation(
                "THEME_PROSE_CITATION_DENSE", "revised_markdown",
                f"第 {number} 段有 {count} 处括号引用，超过 {MAX_CITATIONS_PER_PARAGRAPH} 处；"
                "同一篇只用一次「作者（年）」，其余改成行文",
                actual=str(count),
            ))
            break
    return found


def _review_lead(lead: str) -> list[Violation]:
    """The entry: plain words, one concrete number, and short."""

    found: list[Violation] = []
    jargon = sorted(term for term, pattern in _TERM.items() if pattern.search(lead))
    if jargon:
        found.append(Violation(
            "THEME_PROSE_LEAD_JARGON", "revised_markdown",
            "开头段用了只有本领域才懂的词（" + "、".join(jargon) + "）；"
            "先用日常语言说清现象，术语留到分节里再解释",
            actual="、".join(jargon),
        ))
    if not any(char.isdigit() for char in lead):
        found.append(Violation(
            "THEME_PROSE_LEAD_NO_EXAMPLE", "revised_markdown",
            "开头段没有具体例子：给一组材料里的数字（哪个灾害、什么统计、差多少），"
            "读者才抓得住这个主题在说什么",
        ))
    if len(lead) > MAX_LEAD_CHARS:
        found.append(Violation(
            "THEME_PROSE_LEAD_TOO_LONG", "revised_markdown",
            f"开头段 {len(lead)} 字，超过 {MAX_LEAD_CHARS} 字；入口要短，"
            "细节放进后面的分节",
            expected=f"≤{MAX_LEAD_CHARS} 字",
            actual=f"{len(lead)} 字",
        ))
    return found


def _lead_paragraph(lines: list[str]) -> str:
    """Everything before the first heading, without comments or blank lines."""

    keep: list[str] = []
    for line in lines:
        if _HEADING.match(line):
            break
        if line.startswith("<!--") or line.strip() == "---":
            continue
        keep.append(line)
    return "\n".join(keep)


def _paragraphs(lines: list[str]):
    block: list[str] = []
    for line in lines:
        if not line.strip():
            if block:
                yield "\n".join(block)
                block = []
            continue
        if _HEADING.match(line):
            if block:
                yield "\n".join(block)
                block = []
            continue
        block.append(line)
    if block:
        yield "\n".join(block)


def review_candidate(output: Any) -> ProseAudit:
    """The discovery answer: every candidate is a question, not a field survey.

    A theme built from a field label ("infrastructure cascade risk") can only be
    written as an inventory. A theme built from a question can be answered, so
    the candidate has to state it, and the name has to fit on a signpost.
    """

    if not isinstance(output, Mapping):
        return ProseAudit((Violation("THEME_PROSE_MISSING", "actions", "答案不是 JSON 对象"),))
    actions = output.get("actions")
    if not isinstance(actions, list):
        return ProseAudit()
    found: list[Violation] = []
    for index, action in enumerate(actions):
        if not isinstance(action, Mapping):
            continue
        themes = action.get("themes")
        if not isinstance(themes, list):
            continue
        for position, theme in enumerate(themes):
            if not isinstance(theme, Mapping):
                continue
            path = f"actions[{index}].themes[{position}]"
            title = theme.get("title")
            if isinstance(title, str):
                if len(title) > MAX_TITLE_CHARS or "：" in title or ":" in title:
                    found.append(Violation(
                        "THEME_TITLE_NOT_HUMAN", path + ".title",
                        f"主题名要能当路标：不超过 {MAX_TITLE_CHARS} 字、不要用冒号堆副标题",
                        actual=title[:60],
                    ))
            candidate = theme.get("candidate_markdown")
            if isinstance(candidate, str) and _QUESTION not in candidate[:400]:
                found.append(Violation(
                    "THEME_QUESTION_MISSING", path + ".candidate_markdown",
                    "候选正文的前 400 字里要用一句问句写明这个主题要回答什么；"
                    "没有可回答的问题，就只是把一个领域列成了名录",
                ))
    return ProseAudit(tuple(found))


__all__ = [
    "LEAD_TERMS",
    "MAX_CITATIONS_PER_PARAGRAPH",
    "MAX_HEADING_LEVEL",
    "MIN_LEAD_CHARS",
    "ProseAudit",
    "review",
]
