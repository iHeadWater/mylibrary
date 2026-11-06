"""Send a rejected focused reading back with what it missed.

A reading is accepted only when every quote resolves inside the paper and enough
body pages carry evidence (``domain.grounding``). Both failures are an
*incomplete* answer, not an undecidable one: the program knows which pages still
lack evidence and the prompt already lists the identifiers that exist there. So
instead of ending the run, the same model is asked once more with exactly that
list.

The threshold never moves. A repair round can only add evidence; it can not
lower ``min_coverage``, relax the canary echo or accept an invented quote. That
distinction is the point: an answer that covers half a paper is rejected either
way, and a run whose other themes were finished should not be thrown away
because one reading stopped early (#33).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

# One repair round is one extra model call, so the cap is small on purpose. It
# matches the subject-card path: a model that cannot cover the paper in five
# answers will not cover it in a sixth.
MAX_REPAIR_ROUNDS = 5
DEFAULT_REPAIR_ROUNDS = 3

# Transport failures answer nothing, so they are retried instead of repaired and
# do not spend a repair round. The codes match ``application.card_workflow``:
# the same runner produces them on both paths.
RETRYABLE_RUNNER_CODES = frozenset({
    "RUNNER_OUTPUT_INVALID",          # truncated, wrapped in prose, or not JSON
    "MARKDOWN_RUNNER_OUTPUT_INVALID",
    "RUNNER_CONNECTION_FAILED",
    "RUNNER_IO_ERROR",
})

# A violation an answer can fix by answering again. Everything else -- a digest
# mismatch, a changed PDF -- describes the input, not the answer: asking again
# would only produce the same rejection with a fresh call's cost.
FIXABLE_ANSWER_CODES = frozenset({
    # a focused reading
    "INCOMPLETE_MARKDOWN_READ",       # canaries not echoed: the full text was not read
    "QUOTE_NOT_FOUND",                # no quotable location, or a quote outside the paper
    "ANCHOR_MISMATCH",                # the quote exists, the page label is wrong
    "QUOTE_TOO_WEAK",                 # too short to support the statement
    "CARD_SENTENCE_ID_UNKNOWN",       # cited an identifier the paper does not contain
    "CARD_SENTENCE_IDS_INVALID",      # identifiers were not a list of strings
    "CARD_SENTENCE_IDS_CROSS_PAGE",   # one location spanning two pages
    # the theme prose itself (``domain.theme_prose``)
    "THEME_PROSE_MISSING",
    "THEME_PROSE_MISSING_AUDIT",
    "THEME_PROSE_MACHINE_TOKEN",
    "THEME_PROSE_HEADING_DEPTH",
    "THEME_PROSE_NO_SUMMARY",
    "THEME_PROSE_CITATION_DENSE",
    "THEME_PROSE_LEAD_JARGON",
    "THEME_PROSE_LEAD_NO_EXAMPLE",
    "THEME_PROSE_LEAD_TOO_LONG",
    "THEME_TITLE_NOT_HUMAN",
    "THEME_QUESTION_MISSING",
})

# Kept for callers that name the reading case explicitly.
FIXABLE_READING_CODES = FIXABLE_ANSWER_CODES

# What to change, in words a model can act on. The message says what is wrong;
# this says what to do, because a citation error can be fixed either by citing
# or by deleting, and only the model knows which statement survives.
_REPAIR_NOTES: dict[str, str] = {
    "CARD_SENTENCE_ID_UNKNOWN": (
        "句子编号必须逐字取自提示词里的“可引用的句子编号”。某一页如果标着没有可引用的句子，"
        "就说明这页只有图、不能引用：删掉这条证据，不要按页码编一个编号。"
    ),
    "CARD_SENTENCE_IDS_INVALID": (
        "sentence_ids 必须是非空字符串数组，元素形如 P3-S004；不要把整段话当编号提交。"
    ),
    "CARD_SENTENCE_IDS_CROSS_PAGE": (
        "同一处证据只能引用同一页的编号；跨了两页就拆成两条，各自标注自己的页码。"
    ),
    "INCOMPLETE_MARKDOWN_READ": (
        "reading_receipt.canaries_seen 必须回显提示词里出现的全部完整性 canary，"
        "这是“读到了全文”的唯一凭证；缺一个都不能通过。"
    ),
    "QUOTE_NOT_FOUND": (
        "每条证据都要有一种指向原文的方式：句子编号，或者能在 paper.md 里逐字找到的引文。"
        "找不到的引文不要改写后继续用——要么换成真实存在的句子，要么删掉这条证据。"
    ),
    "ANCHOR_MISMATCH": (
        "引文必须真的落在你标注的那一页上；页码写错时，改页码，不要改引文。"
    ),
    "QUOTE_TOO_WEAK": (
        "引文太短，撑不住一条判断；换成一整句能独立读懂的原文。"
    ),
    "THEME_PROSE_MISSING": (
        "revised_markdown 不能为空；它是给人读的主题正文。"
    ),
    "THEME_PROSE_MISSING_AUDIT": (
        "audit_markdown 不能为空：与初版的修订对照、原文/推理/不确定的证据归属、"
        "判断与来源的对应都写在这里，不要塞回正文。"
    ),
    "THEME_PROSE_MACHINE_TOKEN": (
        "正文里不要出现 evidence_id、EV- 编号、【原文】/【推理】标记或「逐项关联」；"
        "改成「作者（年）」并用人话说明，这些工作流字样只进审计记录。"
    ),
    "THEME_PROSE_HEADING_DEPTH": (
        "小标题最多三级；层级再深就变成清单了，把内容并回去。"
    ),
    "THEME_PROSE_NO_SUMMARY": (
        "开头先给一段 150–250 字的摘要（放在第一个小标题之前）：在问什么、最硬的结论、"
        "最大的不确定。不要用「修订名称」「范围界定」开头。"
    ),
    "THEME_PROSE_CITATION_DENSE": (
        "一段最多 3 处括号引用。同一篇文献只在首次出现时写「作者（年）」，"
        "之后的句子直接说事，不要每个分句后面挂一次括号。"
    ),
    "THEME_PROSE_LEAD_JARGON": (
        "开头段不要用 RF、SF、OVD、级联、共因、容量失效、归因、口径 这类词；"
        "先用日常语言说清现象，术语留到分节里第一次出现时再用一句话解释。"
    ),
    "THEME_PROSE_LEAD_NO_EXAMPLE": (
        "开头段要给一个材料里的具体例子，带数字：哪个灾害、什么统计、两个数差多少。"
        "没有例子，读者不知道这个主题在说什么。"
    ),
    "THEME_PROSE_LEAD_TOO_LONG": (
        "开头段要短（≤600 字，最好 3 段以内）。它只负责把读者带进门，细节放进分节。"
    ),
    "THEME_TITLE_NOT_HUMAN": (
        "主题名不超过 30 字，不要用冒号堆副标题；写成一句能当路标的话，"
        "例如「灾害造成的服务中断有多少越出受灾范围」。"
    ),
    "THEME_QUESTION_MISSING": (
        "候选正文的前 400 字里要用一句问句写明这个主题要回答什么。"
        "如果这几篇文献凑不出一个可回答的问题，就不要建这个主题。"
    ),
}


@dataclass(frozen=True)
class RepairRequest:
    """One more question, built from what the program rejected."""

    violations: tuple[dict[str, Any], ...] = ()
    coverage: dict[str, Any] | None = None

    @property
    def missing_pages(self) -> tuple[int, ...]:
        return tuple((self.coverage or {}).get("missing_pages") or ())


def repair_request(audit: Any) -> RepairRequest | None:
    """What to send back, or ``None`` when another answer cannot help.

    Returns ``None`` in two different situations on purpose: the answer already
    passes (nothing to repair), or it failed for a reason the model cannot fix
    (the caller then reports the failure as before).
    """

    violations = tuple(violation.as_dict() for violation in audit.violations)
    if violations:
        if any(item.get("code") not in FIXABLE_ANSWER_CODES for item in violations):
            return None
        return RepairRequest(violations, _coverage_dict(audit))
    reading = getattr(audit, "reading", None)
    if reading is not None and not reading.verified:
        # No violation to point at: every quote is right and there are simply
        # too few pages. Only the coverage block can carry that.
        return RepairRequest((), _coverage_dict(audit))
    return None


def _coverage_dict(audit: Any) -> dict[str, Any] | None:
    coverage = getattr(audit, "coverage", None)
    return coverage.as_dict() if coverage is not None else None


def repair_prompt(
    base: str,
    previous: Mapping[str, Any],
    request: RepairRequest,
    *,
    round_number: int,
    max_rounds: int,
    subject: str = "精读",
) -> str:
    """The same task again: previous answer, what was rejected, what to add."""

    lines = [
        base.rstrip(),
        "",
        f"## 上一次的{subject}被拒绝（第 {round_number}/{max_rounds} 次修正）",
        "下面是你的上一份回答。它没有被接受，原因在下一节；修正时保留已经合格的部分。",
        "```json",
        json.dumps(previous, ensure_ascii=False, indent=1, default=str),
        "```",
    ]
    if request.violations:
        lines += [
            "",
            f"## 校验发现的问题（共 {len(request.violations)} 处）",
            "".join(_render(item) + "\n" for item in request.violations).rstrip(),
        ]
        notes = [_REPAIR_NOTES[code] for code in _REPAIR_NOTES
                 if any(item.get("code") == code for item in request.violations)]
        if notes:
            lines += ["", "## 修复要点", "".join(f"- {note}\n" for note in notes).rstrip()]
    coverage = request.coverage
    if coverage and not coverage.get("satisfied", True):
        covered = coverage.get("covered_pages") or []
        missing = coverage.get("missing_pages") or []
        lines += [
            "",
            "## 引文覆盖不足",
            (
                f"- 已覆盖 {len(covered)} 页，需要 {coverage.get('required_pages')} 页"
                f"（阈值 {coverage.get('min_coverage')}，正文页共 {len(covered) + len(missing)} 页）"
            ),
            f"- 尚未覆盖的页面：{', '.join(str(page) for page in missing)}",
            "- 为上面每一页各补一条证据：从 paper.numbered.md 里选这一页真实存在的句子编号，"
            "写进对应陈述的 source_locations.sentence_ids。",
            "- 不要把已有编号改标成别页，也不要为了凑页数重复引用同一句；一页一条能支撑正文判断的即可。",
        ]
    lines += ["", "## 修复规则"]
    if subject == "精读":
        lines += [
            "- 只补上面列出的缺页与问题；已经通过校验的证据保持原样。",
            "- 编号只能逐字取自提示词里“可引用的句子编号”这份清单。",
            "- 每篇论文都必须读完整篇，不能只读与问题直接相关的段落；"
            "覆盖率门槛不会因为这次修正而降低。",
        ]
    else:
        lines += [
            "- 只改上面列出的问题；已经合格的部分保持原样。",
            "- revised_markdown 与 audit_markdown 都要重新给出完整内容，不要只给改动片段。",
            "- 不要为了通过校验删掉实质判断；宁可写短，也不要把结论删空。",
        ]
    lines.append("- 仍然只输出一个 JSON 对象，字段与原来完全一致。")
    return "\n".join(lines)


def retry_prompt(base: str, code: str, message: str) -> str:
    """The same task again, after a call that returned nothing usable.

    There is no previous answer to correct, so this says only what went wrong
    and that the requirements did not change.
    """

    return "\n".join([
        base.rstrip(),
        "",
        "## 上一次调用没有拿到可用的回答",
        f"- 失败原因：{code}：{message}",
        "- 这是同一份任务的再次作答，不是新任务：仍然按上面的全部要求输出。",
        "- 只输出一个 JSON 对象，不要加解释文字或其它结构。",
    ])


def _render(item: Mapping[str, Any]) -> str:
    parts = []
    if item.get("expected") is not None:
        parts.append(f"期望 {item['expected']}")
    if item.get("actual") is not None:
        parts.append(f"实际 {item['actual']}")
    detail = f"（{'；'.join(parts)}）" if parts else ""
    return f"- [{item.get('code')}] {item.get('path')}：{item.get('message')}{detail}"


__all__ = [
    "DEFAULT_REPAIR_ROUNDS",
    "FIXABLE_READING_CODES",
    "MAX_REPAIR_ROUNDS",
    "RETRYABLE_RUNNER_CODES",
    "RepairRequest",
    "repair_prompt",
    "repair_request",
    "retry_prompt",
]
