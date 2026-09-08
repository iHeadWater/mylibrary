"""One provider invocation; automated contracts are not scientific verification."""
from __future__ import annotations

import hashlib
import re
import time
from copy import deepcopy

from hydro_platform.config import SINGLE_AGENT_PROTOCOL_VERSION
from hydro_platform.progress import report_progress
from hydro_platform.source_access import source_access_acceptable


def validate_attribution(body):
    """Check machine-readable attribution, not whether statements are true."""
    if not isinstance(body, str):
        raise ValueError("缺少 Markdown 正文")
    for line in body.splitlines():
        # Reporting the paper's own human-labeling/review method is not a task for our users.
        if "【原文陈述】" in line or "【原文转述】" in line:
            continue
        if re.search(r"(?<!不)需要.{0,12}(?:人工|导师|学生|研究者).{0,12}(?:核验|复核|确认|审核)"
                     r"|(?:请|待|交由|必须|(?<!无)需(?!要)).{0,12}(?:人工|导师|学生|研究者).{0,12}(?:核验|复核|确认|审核)", line):
            raise ValueError("粗卡不得转交人工核验任务；请客观记录信息边界")
    if re.search(r"^-\s*(?:本人.*复查|独立检查)\s*[:：]", body, re.M):
        raise ValueError("单 Agent 卡片不得包含人工或独立检查字段")
    claims_section = re.search(r"^## 声明—原文证据对应表\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    if not claims_section:
        raise ValueError("缺少声明—原文证据对应表")
    claims = []
    for line in claims_section[1].splitlines():
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if cells and re.fullmatch(r"C\d+", cells[0]):
            if (len(cells) != 7 or any(not c for c in cells)
                or not cells[2].startswith(("【原文陈述】", "【原文转述】"))):
                raise ValueError("声明行必须保留七列并标明原文陈述/转述及来源位置")
            claims.append(cells[0])
    if not claims or len(claims) != len(set(claims)):
        raise ValueError("声明表为空或存在重复 C 编号")
    for heading, marker in (("AI 推理", "【AI 推理】"), ("信息边界", "【信息边界】")):
        section = re.search(r"^## " + heading + r"\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
        if not section or marker not in section[1]:
            raise ValueError("缺少独立的 " + heading + " 内容与性质标记")
    references = set(re.findall(r"\bC\d+\b", body))
    if references - set(claims):
        raise ValueError("卡片引用了不存在的 C 编号")
    return {"claim_count": len(claims)}


class SingleAgentCardGeneratorAdapter:
    def __init__(self, delegate, *, progress=None):
        self.delegate, self.progress = delegate, progress

    def preflight(self, **kwargs):
        return {**self.delegate.preflight(**kwargs),
                "workflow_mode": "single_agent", "workflow_protocol_version": SINGLE_AGENT_PROTOCOL_VERSION}

    def smoke_test(self):
        return self.delegate.smoke_test()

    def generate(self, prompt, **kwargs):
        started = time.monotonic()
        report_progress(self.progress, "role_started", role="card_writer", index=1, total=1)
        result = self.delegate.generate(prompt, **{**kwargs, "run_label": "card_writer"})
        if not result.get("ok"):
            return result
        try:
            # The provider rechecks source immutability; bind this audit to that exact PDF.
            with kwargs["source_pdf_path"].open("rb") as source_stream:
                digest = hashlib.file_digest(source_stream, "sha256").hexdigest()
            access = result.get("source_access")
            if (not source_access_acceptable(access, expected_sha256=digest,
                                             expected_parent_key=kwargs["zotero_parent_key"])
                or access.get("method") != "local_pdf_path" or result.get("ephemeral") is not True):
                raise ValueError("单 Agent 来源身份、阅读记录或会话隔离不符合协议")
            output = result.get("output")
            if not isinstance(output, dict):
                raise ValueError("模型输出不是 JSON 对象")
            metrics = validate_attribution(output.get("card_body_markdown"))
        except (ValueError, OSError) as exc:
            return {**result, "ok": False,
                    "error": {"code": "SINGLE_CARD_CONTRACT_FAILED", "message": str(exc) if isinstance(exc, ValueError) else "校验时无法读取原始 PDF"},
                    "diagnostic": {"stage": "single_card_contract", "protocol_version": SINGLE_AGENT_PROTOCOL_VERSION,
                                   "draft_path": result.get("draft_path")}}
        report = {"protocol_version": SINGLE_AGENT_PROTOCOL_VERSION, "status": "STRUCTURE_VALIDATED",
                  "completed_role_count": 1, "required_roles": ["card_writer"],
                  "gates": {"isolated_session": True, "source_identity": True,
                            "reading_report_accepted": True, "attribution_contract": True,
                            "independent_review": False, "scientific_correctness_verified": False},
                  **metrics}
        audit = {"schema_version": 1, "source_pdf_sha256": digest, "quality_report": report,
                 "roles": {"card_writer": {"output": deepcopy(result["output"]),
                           "execution": {"isolated": True, "source_access": deepcopy(access),
                                         "model": result.get("configured_model"),
                                         "reasoning_effort": result.get("configured_reasoning_effort"),
                                         "elapsed_seconds": round(time.monotonic() - started, 2),
                                         "usage": result.get("usage"),
                                         "reading_prompt_version": result.get("reading_prompt_version"),
                                         "reading_prompt_sha256": result.get("reading_prompt_sha256"),
                                         "warnings": result.get("warnings", [])}}},
                 "scope": "结构及归因格式校验；阅读范围由模型报告，不代表独立全文、图表理解或科学正确性验证"}
        report_progress(self.progress, "role_completed", role="card_writer")
        report_progress(self.progress, "workflow_completed")
        return {**result, "workflow": report, "quality_audit": audit}
