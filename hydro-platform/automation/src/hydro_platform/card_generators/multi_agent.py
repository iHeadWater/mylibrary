from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hydro_platform.card_generators.base import CardGeneratorAdapter
from hydro_platform.progress import ProgressCallback, report_progress
from hydro_platform.source_access import source_access_acceptable
from hydro_platform.config import (
    REQUIRED_CARD_WORKFLOW_ROLES,
    CardQualityWorkflowConfig,
    CardWorkflowRoleConfig,
    LOCAL_PATH_PROTOCOL_VERSION,
)


_PROMPT_VERSION_PATTERN = re.compile(
    r'^---\s*\r?\nprompt_version:\s*["\']([^"\']+)["\']\s*\r?\n---',
    re.MULTILINE,
)
_TEMPLATE_ID_PATTERN = re.compile(r'<evidence-card-template id="([^"]+)">')
_ACCEPTED_VISUAL_STATUSES = frozenset({"REVIEWED", "NOT_PRESENT"})
_REQUIRED_COVERAGE_AREAS = frozenset(
    {
        "research_question",
        "data",
        "method",
        "results",
        "visuals",
        "limitations",
        "negative_results",
    }
)
_REQUIRED_CHALLENGE_TYPES = frozenset(
    {
        "factual_support",
        "numerical_accuracy",
        "causal_language",
        "author_agent_boundary",
        "visual_interpretation",
    }
)


class _WorkflowAbort(RuntimeError):
    def __init__(self, result: dict[str, Any]):
        super().__init__(result.get("error", {}).get("message", "多 Agent 流程失败"))
        self.result = result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset(path: Path, *, kind: str) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"无法读取多 Agent {kind}：{path}") from exc
    if kind == "提示词":
        match = _PROMPT_VERSION_PATTERN.search(content)
        if match is None:
            raise ValueError(f"多 Agent 提示词缺少 prompt_version：{path}")
        version = match.group(1).strip()
    else:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"多 Agent 输出 schema 不是有效 JSON：{path}") from exc
        if not isinstance(parsed, dict) or parsed.get("type") != "object":
            raise ValueError(f"多 Agent 输出 schema 根节点必须是 object：{path}")
        version = "schema-v1"
    return {
        "path": str(path),
        "version": version,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
    }


def _usage_total(role_records: dict[str, dict[str, Any]]) -> dict[str, int] | None:
    totals: dict[str, int] = {}
    for record in role_records.values():
        usage = record.get("execution", {}).get("usage")
        if not isinstance(usage, dict):
            continue
        for name, value in usage.items():
            if isinstance(value, int) and not isinstance(value, bool):
                totals[name] = totals.get(name, 0) + value
    return totals or None


def _evidence_ok(evidence: Any, page_count: int) -> bool:
    if not isinstance(evidence, list) or not evidence:
        return False
    for item in evidence:
        if not isinstance(item, dict):
            return False
        page = item.get("page")
        if (
            isinstance(page, bool)
            or not isinstance(page, int)
            or not 1 <= page <= page_count
            or not isinstance(item.get("locator"), str)
            or not item["locator"].strip()
            or not isinstance(item.get("evidence_text"), str)
            or not item["evidence_text"].strip()
            or not isinstance(item.get("visual"), bool)
        ):
            return False
    return True


def _probability(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and 0 <= value <= 1
    )


def _internal_identifier(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是字符串")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 128
        or any(character in normalized for character in ("\r", "\n", "\x00"))
    ):
        display = repr(value[:80])
        raise ValueError(f"{field} 无效：{display}")
    return normalized


def _common_output(
    output: Any,
    page_count: int,
    *,
    stage: str,
    schema_version: int = 1,
) -> dict[str, Any]:
    if not isinstance(output, dict):
        raise ValueError(f"{stage} 没有返回 JSON 对象")
    if output.get("schema_version") != schema_version:
        raise ValueError(f"{stage} schema_version 无效")
    if output.get("source_read_status") != "FULL_PDF_REVIEWED":
        raise ValueError(f"{stage} 未确认完整阅读 PDF")
    if output.get("source_page_count") != page_count:
        raise ValueError(f"{stage} 返回页数与本机 PDF 页数不一致")
    if output.get("visual_content_status") not in _ACCEPTED_VISUAL_STATUSES:
        raise ValueError(f"{stage} 未确认检查页面图像")
    if (
        not isinstance(output.get("source_read_evidence"), str)
        or not output["source_read_evidence"].strip()
    ):
        raise ValueError(f"{stage} 缺少阅读说明")
    return output


def _fact_ids(output: dict[str, Any], *, stage: str, page_count: int) -> set[str]:
    facts = output.get("facts")
    if not isinstance(facts, list) or not facts:
        raise ValueError(f"{stage} 没有提取任何事实")
    identifiers: set[str] = set()
    for fact in facts:
        if not isinstance(fact, dict):
            raise ValueError(f"{stage} 事实条目不是对象")
        fact_id = _internal_identifier(
            fact.get("fact_id"),
            field=f"{stage} 事实编号",
        )
        fact["fact_id"] = fact_id
        if fact_id in identifiers:
            raise ValueError(f"{stage} 出现重复事实编号：{fact_id}")
        if (
            not isinstance(fact.get("statement"), str)
            or not fact["statement"].strip()
            or not _probability(fact.get("confidence"))
            or not _evidence_ok(fact.get("evidence"), page_count)
        ):
            raise ValueError(f"{stage} 事实 {fact_id} 缺少有效陈述或原文证据")
        identifiers.add(fact_id)
    coverage = output.get("coverage")
    if not isinstance(coverage, list) or not coverage:
        raise ValueError(f"{stage} 缺少全文章节覆盖记录")
    for entry in coverage:
        if not isinstance(entry, dict):
            raise ValueError(f"{stage} 章节覆盖记录无效")
        start = entry.get("page_start")
        end = entry.get("page_end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or not 1 <= start <= end <= page_count
        ):
            raise ValueError(f"{stage} 章节覆盖页码无效")
    visuals = output.get("key_visuals")
    if not isinstance(visuals, list):
        raise ValueError(f"{stage} 缺少关键视觉内容清单")
    for visual in visuals:
        page = visual.get("page") if isinstance(visual, dict) else None
        if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= page_count:
            raise ValueError(f"{stage} 关键视觉内容页码无效")
    return identifiers


class MultiAgentCardGeneratorAdapter:
    """Mandatory isolated-role workflow wrapped around a provider adapter."""

    def __init__(
        self,
        delegate: CardGeneratorAdapter,
        config: CardQualityWorkflowConfig,
        *, progress: ProgressCallback | None = None,
    ) -> None:
        self.delegate = delegate
        self.config = config
        self.progress = progress

    def _assets(self) -> dict[str, dict[str, Any]]:
        prompt_paths = {
            "fact_extraction": self.config.fact_extraction_prompt_file,
            "fact_adjudication": self.config.fact_adjudication_prompt_file,
            "critical_analysis": self.config.critical_analysis_prompt_file,
            "adversarial_review": self.config.adversarial_review_prompt_file,
        }
        schema_paths = {
            "fact_extraction": self.config.fact_extraction_schema_file,
            "fact_adjudication": self.config.fact_adjudication_schema_file,
            "critical_analysis": self.config.critical_analysis_schema_file,
            "adversarial_review": self.config.adversarial_review_schema_file,
        }
        assets: dict[str, dict[str, Any]] = {}
        for name, path in prompt_paths.items():
            assets[f"prompt:{name}"] = _asset(path, kind="提示词")
        for name, path in schema_paths.items():
            assets[f"schema:{name}"] = _asset(path, kind="输出 schema")
        if self.config.protocol_version == LOCAL_PATH_PROTOCOL_VERSION and any(
            "hydro_pdf_reader.read_full_source_pdf" in asset["content"] for asset in assets.values()
        ):
            raise ValueError("路径制卡不能使用强制调用旧 PDF MCP 的角色提示词，请更新总配置")
        return assets

    def preflight(self) -> dict[str, Any]:
        result = self.delegate.preflight()
        if not result.get("ok"):
            return result
        try:
            assets = self._assets()
        except ValueError as exc:
            return {
                "schema_version": 1,
                "ok": False,
                "component": "card_generator",
                "error": {
                    "code": "MULTI_AGENT_WORKFLOW_CONFIG_INVALID",
                    "message": str(exc),
                },
            }
        enriched = dict(result)
        enriched["multi_agent_workflow"] = {
            "required": True,
            "protocol_version": self.config.protocol_version,
            "required_roles": list(REQUIRED_CARD_WORKFLOW_ROLES),
            "asset_count": len(assets),
        }
        return enriched

    def smoke_test(self) -> dict[str, Any]:
        return self.delegate.smoke_test()

    def _failure(
        self,
        code: str,
        message: str,
        *,
        stage: str,
        source: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        diagnostic: dict[str, Any] = {
            "stage": stage,
            "protocol_version": self.config.protocol_version,
        }
        if isinstance(source, dict):
            source_diagnostic = source.get("diagnostic")
            if isinstance(source_diagnostic, dict):
                diagnostic["provider"] = source_diagnostic
        return {
            "schema_version": 1,
            "ok": False,
            "component": "card_generator",
            "operation": "multi_agent_evidence_card_generation",
            "error": {"code": code, "message": message},
            "diagnostic": diagnostic,
        }

    def _invoke(
        self,
        role_name: str,
        prompt_asset: dict[str, Any] | None,
        schema_path: Path,
        dynamic_input: dict[str, Any],
        *,
        fallback_prompt: str | None,
        working_directory: Path,
        source_pdf_path: Path,
        zotero_parent_key: str,
        role_records: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        report_progress(
            self.progress, "role_started", role=role_name,
            index=REQUIRED_CARD_WORKFLOW_ROLES.index(role_name) + 1,
            total=len(REQUIRED_CARD_WORKFLOW_ROLES),
        )
        role: CardWorkflowRoleConfig = self.config.roles[role_name]
        base_prompt = prompt_asset["content"] if prompt_asset is not None else fallback_prompt
        if not isinstance(base_prompt, str) or not base_prompt.strip():
            raise _WorkflowAbort(
                self._failure(
                    "MULTI_AGENT_WORKFLOW_CONFIG_INVALID",
                    f"角色 {role_name} 缺少提示词",
                    stage=role_name,
                )
            )
        prompt = (
            base_prompt.rstrip()
            + "\n\n## 本次运行输入\n\n```json\n"
            + json.dumps(dynamic_input, ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        result = self.delegate.generate(
            prompt,
            working_directory=working_directory,
            source_pdf_path=source_pdf_path,
            zotero_parent_key=zotero_parent_key,
            output_schema_path=schema_path,
            model=role.model,
            reasoning_effort=role.reasoning_effort,
            timeout_seconds=role.timeout_seconds,
            run_label=role_name,
        )
        if not result.get("ok"):
            raw_error = result.get("error")
            code = (
                raw_error.get("code")
                if isinstance(raw_error, dict) and isinstance(raw_error.get("code"), str)
                else "CARD_GENERATOR_FAILED"
            )
            message = (
                raw_error.get("message")
                if isinstance(raw_error, dict) and isinstance(raw_error.get("message"), str)
                else f"角色 {role_name} 调用失败"
            )
            raise _WorkflowAbort(
                self._failure(code, message, stage=role_name, source=result)
            )
        report_progress(self.progress, "phase", message="调用已返回，正在检查 PDF 来源、阅读记录和角色输出")
        source_access = result.get("source_access")
        direct = self.config.protocol_version == LOCAL_PATH_PROTOCOL_VERSION
        expected_method = "local_pdf_path" if direct else "bound_local_pdf_mcp"
        if (not source_access_acceptable(source_access,
                expected_sha256=dynamic_input["source_pdf_sha256"], expected_parent_key=zotero_parent_key)
            or source_access.get("method") != expected_method
            or _sha256_file(source_pdf_path) != dynamic_input["source_pdf_sha256"]):
            raise _WorkflowAbort(
                self._failure(
                    "MULTI_AGENT_SOURCE_ACCESS_UNVERIFIED",
                    f"角色 {role_name} 的 PDF 来源或阅读记录不符合当前协议",
                    stage=role_name,
                )
            )
        if result.get("ephemeral") is not True:
            raise _WorkflowAbort(
                self._failure(
                    "MULTI_AGENT_ISOLATION_UNVERIFIED",
                    f"角色 {role_name} 没有证明使用隔离临时会话",
                    stage=role_name,
                )
            )
        output = result.get("output")
        role_records[role_name] = {
            "prompt_version": (
                prompt_asset["version"] if prompt_asset is not None else "synthesis-prompt"
            ),
            "prompt_sha256": (
                prompt_asset["sha256"]
                if prompt_asset is not None
                else hashlib.sha256(base_prompt.encode("utf-8")).hexdigest()
            ),
            "output_schema_sha256": _sha256_file(schema_path),
            "execution": {
                "adapter": result.get("adapter"),
                "model": result.get("configured_model") or "provider_default",
                "reasoning_effort": (
                    result.get("configured_reasoning_effort") or "model_default"
                ),
                "isolated": True,
                "source_access": source_access,
                "reading_prompt_version": result.get("reading_prompt_version"),
                "reading_prompt_sha256": result.get("reading_prompt_sha256"),
                "reading_settings": result.get("reading_settings"),
                "sandbox_preflight": result.get("sandbox_preflight"),
                "usage": result.get("usage"),
            },
            "output": output,
        }
        return result, output

    def generate(
        self,
        prompt: str,
        *,
        working_directory: Path,
        source_pdf_path: Path,
        zotero_parent_key: str,
        output_schema_path: Path,
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout_seconds: float | None = None,
        run_label: str | None = None,
    ) -> dict[str, Any]:
        del model, reasoning_effort, timeout_seconds, run_label
        try:
            assets = self._assets()
        except ValueError as exc:
            return self._failure(
                "MULTI_AGENT_WORKFLOW_CONFIG_INVALID",
                str(exc),
                stage="workflow_preflight",
            )

        template_ids = sorted(set(_TEMPLATE_ID_PATTERN.findall(prompt)))
        if self.config.protocol_version == LOCAL_PATH_PROTOCOL_VERSION and "hydro_pdf_reader.read_full_source_pdf" in prompt:
            return self._failure("MULTI_AGENT_WORKFLOW_CONFIG_INVALID", "路径制卡的合成提示词仍要求旧 PDF MCP",
                                 stage="workflow_preflight")
        if not template_ids:
            return self._failure(
                "MULTI_AGENT_WORKFLOW_INPUT_INVALID",
                "综合提示词中没有已启用模板",
                stage="workflow_preflight",
            )
        role_records: dict[str, dict[str, Any]] = {}
        task_identity = {
            "zotero_parent_key": zotero_parent_key,
            "source_pdf_absolute_path": str(source_pdf_path),
            "source_pdf_sha256": _sha256_file(source_pdf_path),
            "enabled_template_ids": template_ids,
            "independence_rule": (
                "每个角色由程序创建独立临时会话；不得假装为其他角色"
            ),
        }

        try:
            _, facts_a = self._invoke(
                "fact_extractor_a",
                assets["prompt:fact_extraction"],
                self.config.fact_extraction_schema_file,
                {**task_identity, "extractor": "A"},
                fallback_prompt=None,
                working_directory=working_directory,
                source_pdf_path=source_pdf_path,
                zotero_parent_key=zotero_parent_key,
                role_records=role_records,
            )
            page_count = role_records["fact_extractor_a"]["execution"]["source_access"][
                "page_count"
            ]
            facts_a = _common_output(
                facts_a, page_count, stage="fact_extractor_a"
            )
            fact_ids_a = _fact_ids(
                facts_a, stage="fact_extractor_a", page_count=page_count
            )
            report_progress(self.progress, "role_completed", role="fact_extractor_a")

            _, facts_b = self._invoke(
                "fact_extractor_b",
                assets["prompt:fact_extraction"],
                self.config.fact_extraction_schema_file,
                {**task_identity, "extractor": "B"},
                fallback_prompt=None,
                working_directory=working_directory,
                source_pdf_path=source_pdf_path,
                zotero_parent_key=zotero_parent_key,
                role_records=role_records,
            )
            facts_b = _common_output(
                facts_b, page_count, stage="fact_extractor_b"
            )
            fact_ids_b = _fact_ids(
                facts_b, stage="fact_extractor_b", page_count=page_count
            )
            report_progress(self.progress, "role_completed", role="fact_extractor_b")

            _, adjudication = self._invoke(
                "fact_adjudicator",
                assets["prompt:fact_adjudication"],
                self.config.fact_adjudication_schema_file,
                {
                    **task_identity,
                    "extractor_a_output": facts_a,
                    "extractor_b_output": facts_b,
                },
                fallback_prompt=None,
                working_directory=working_directory,
                source_pdf_path=source_pdf_path,
                zotero_parent_key=zotero_parent_key,
                role_records=role_records,
            )
            adjudication = _common_output(
                adjudication, page_count, stage="fact_adjudicator"
            )
            verified_facts = adjudication.get("verified_facts")
            if not _probability(adjudication.get("classification_confidence")):
                raise ValueError("事实裁决返回了无效分类置信度")
            if (
                not isinstance(verified_facts, list)
                or len(verified_facts) < self.config.minimum_verified_facts
            ):
                raise ValueError(
                    "已验证事实数量低于质量门禁："
                    f"{len(verified_facts) if isinstance(verified_facts, list) else 0}/"
                    f"{self.config.minimum_verified_facts}"
                )
            verified_ids: set[str] = set()
            for fact in verified_facts:
                if not isinstance(fact, dict):
                    raise ValueError("事实裁决返回了非对象事实")
                fact_id = _internal_identifier(
                    fact.get("fact_id"),
                    field="事实裁决编号",
                )
                fact["fact_id"] = fact_id
                if (
                    fact_id in verified_ids
                    or not _probability(fact.get("confidence"))
                    or not _evidence_ok(fact.get("evidence"), page_count)
                ):
                    raise ValueError("事实裁决返回了无效或重复的已验证事实")
                source_ids = fact.get("source_fact_ids")
                if not isinstance(source_ids, list) or not source_ids:
                    raise ValueError(f"已验证事实 {fact_id} 缺少来源事实编号")
                normalized_source_ids: list[str] = []
                for source_id in source_ids:
                    if not isinstance(source_id, str) or ":" not in source_id:
                        raise ValueError(f"已验证事实 {fact_id} 的来源编号无效")
                    prefix, raw_id = source_id.split(":", 1)
                    prefix = prefix.strip().upper()
                    raw_id = _internal_identifier(
                        raw_id,
                        field=f"已验证事实 {fact_id} 的来源事实编号",
                    )
                    if (prefix == "A" and raw_id not in fact_ids_a) or (
                        prefix == "B" and raw_id not in fact_ids_b
                    ) or prefix not in {"A", "B"}:
                        raise ValueError(f"已验证事实 {fact_id} 引用了不存在的提取事实")
                    normalized_source_ids.append(f"{prefix}:{raw_id}")
                fact["source_fact_ids"] = normalized_source_ids
                if fact.get("resolution_basis") == "AGREEMENT" and {
                    source_id.split(":", 1)[0] for source_id in normalized_source_ids
                } != {"A", "B"}:
                    raise ValueError(f"已验证事实 {fact_id} 错误声明双路一致")
                verified_ids.add(fact_id)

            template_id = adjudication.get("template_id")
            if template_id not in template_ids:
                raise ValueError("事实裁决返回了非法或未启用模板 ID")
            unresolved_high = sum(
                1
                for item in (
                    list(adjudication.get("disagreements") or [])
                    + list(adjudication.get("coverage_gaps") or [])
                )
                if isinstance(item, dict)
                and item.get("severity") == "HIGH"
                and (item.get("resolution_status") == "UNRESOLVED" or item.get("status") == "UNRESOLVED")
            )
            if unresolved_high > self.config.maximum_unresolved_high_severity:
                raise ValueError(
                    "存在未解决的高严重度事实分歧或覆盖缺口："
                    f"{unresolved_high}"
                )

            report_progress(self.progress, "role_completed", role="fact_adjudicator")
            _, critical = self._invoke(
                "critical_analyst",
                assets["prompt:critical_analysis"],
                self.config.critical_analysis_schema_file,
                {**task_identity, "adjudicated_fact_layer": adjudication},
                fallback_prompt=None,
                working_directory=working_directory,
                source_pdf_path=source_pdf_path,
                zotero_parent_key=zotero_parent_key,
                role_records=role_records,
            )
            critical = _common_output(
                critical, page_count, stage="critical_analyst"
            )
            analyses = critical.get("analyses")
            if (
                not isinstance(analyses, list)
                or len(analyses) < self.config.minimum_critical_analyses
            ):
                raise ValueError(
                    "批判性分析数量低于质量门禁："
                    f"{len(analyses) if isinstance(analyses, list) else 0}/"
                    f"{self.config.minimum_critical_analyses}"
                )
            analysis_ids: set[str] = set()
            for analysis in analyses:
                analysis_id = (
                    analysis.get("analysis_id") if isinstance(analysis, dict) else None
                )
                premise_ids = analysis.get("premise_fact_ids") if isinstance(analysis, dict) else None
                if isinstance(analysis, dict):
                    analysis_id = _internal_identifier(
                        analysis_id,
                        field="批判分析编号",
                    )
                    analysis["analysis_id"] = analysis_id
                if isinstance(premise_ids, list):
                    premise_ids = [
                        _internal_identifier(
                            identifier,
                            field=f"批判分析 {analysis_id} 的前提事实编号",
                        )
                        for identifier in premise_ids
                    ]
                    analysis["premise_fact_ids"] = premise_ids
                if (
                    not isinstance(analysis_id, str)
                    or analysis_id in analysis_ids
                    or not isinstance(premise_ids, list)
                    or not premise_ids
                    or any(identifier not in verified_ids for identifier in premise_ids)
                    or not _probability(analysis.get("confidence"))
                    or not _evidence_ok(analysis.get("evidence"), page_count)
                ):
                    raise ValueError("批判分析引用了无效事实或原文证据")
                analysis_ids.add(analysis_id)

            report_progress(self.progress, "role_completed", role="critical_analyst")
            _, synthesized = self._invoke(
                "card_synthesizer",
                None,
                output_schema_path,
                {
                    **task_identity,
                    "required_template_id": template_id,
                    "adjudicated_fact_layer": adjudication,
                    "critical_analysis": critical,
                },
                fallback_prompt=prompt,
                working_directory=working_directory,
                source_pdf_path=source_pdf_path,
                zotero_parent_key=zotero_parent_key,
                role_records=role_records,
            )
            synthesized = _common_output(
                synthesized,
                page_count,
                stage="card_synthesizer",
                schema_version=2,
            )
            if synthesized.get("template_id") != template_id:
                raise ValueError("卡片综合 Agent 改变了事实裁决确定的模板类型")
            report_progress(self.progress, "role_completed", role="card_synthesizer")

            review_input = {
                **task_identity,
                "adjudicated_fact_layer": adjudication,
                "critical_analysis": critical,
                "candidate_card": synthesized,
            }
            review_result, review = self._invoke(
                "adversarial_reviewer",
                assets["prompt:adversarial_review"],
                self.config.adversarial_review_schema_file,
                review_input,
                fallback_prompt=None,
                working_directory=working_directory,
                source_pdf_path=source_pdf_path,
                zotero_parent_key=zotero_parent_key,
                role_records=role_records,
            )
            review = _common_output(
                review, page_count, stage="adversarial_reviewer"
            )
            challenges = review.get("challenge_checks")
            if (
                not isinstance(challenges, list)
                or len(challenges) < self.config.minimum_adversarial_challenges
            ):
                raise ValueError(
                    "对抗挑战数量低于质量门禁："
                    f"{len(challenges) if isinstance(challenges, list) else 0}/"
                    f"{self.config.minimum_adversarial_challenges}"
                )
            for challenge in challenges:
                if (
                    not isinstance(challenge, dict)
                    or not _evidence_ok(challenge.get("evidence"), page_count)
                ):
                    raise ValueError("对抗复核存在无原文依据的挑战结果")
            challenge_types = {
                item.get("challenge_type")
                for item in challenges
                if isinstance(item, dict)
            }
            if not _REQUIRED_CHALLENGE_TYPES.issubset(challenge_types):
                raise ValueError("对抗复核没有完成全部五类强制挑战")
            coverage_checks = review.get("coverage_checks")
            coverage_areas = {
                item.get("area")
                for item in coverage_checks
                if isinstance(item, dict)
            } if isinstance(coverage_checks, list) else set()
            issues = review.get("issues")
            correction_required = any(
                isinstance(item, dict) and item.get("requires_correction") is True
                for item in (issues if isinstance(issues, list) else [])
            )
            rejected_challenge = any(
                item.get("status") != "SUPPORTED"
                for item in challenges
                if isinstance(item, dict)
            )
            missing_coverage = any(
                item.get("status") == "MISSING"
                for item in (coverage_checks if isinstance(coverage_checks, list) else [])
                if isinstance(item, dict)
            )
            if coverage_areas != _REQUIRED_COVERAGE_AREAS:
                raise ValueError("对抗复核没有逐项检查全部必需覆盖领域")
            if (
                review.get("verdict") != "PASS"
                or correction_required
                or rejected_challenge
                or missing_coverage
            ):
                return self._failure(
                    "CARD_QUALITY_FAILED",
                    "候选粗证据卡未通过自动对抗复核，禁止写入并参与主题生成",
                    stage="quality_gate",
                    source=review_result,
                )

        except _WorkflowAbort as exc:
            return exc.result
        except (OSError, ValueError) as exc:
            return self._failure(
                "CARD_QUALITY_CONTRACT_FAILED",
                str(exc),
                stage="quality_gate",
            )

        quality_report = {
            "status": "VALIDATED",
            "protocol_version": self.config.protocol_version,
            "required_roles": list(REQUIRED_CARD_WORKFLOW_ROLES),
            "completed_role_count": len(role_records),
            "extractor_a_fact_count": len(facts_a["facts"]),
            "extractor_b_fact_count": len(facts_b["facts"]),
            "verified_fact_count": len(verified_facts),
            "critical_analysis_count": len(analyses),
            "adversarial_challenge_count": len(challenges),
            "unresolved_high_severity_count": unresolved_high,
            "correction_required_count": sum(
                1
                for item in issues
                if isinstance(item, dict) and item.get("requires_correction") is True
            ),
            "gates": {
                "isolated_required_roles": True,
                "full_pdf_access_each_role": self.config.protocol_version != LOCAL_PATH_PROTOCOL_VERSION,
                "source_identity_each_role": True,
                "reading_report_each_role": True,
                "dual_fact_extraction": True,
                "source_grounded_adjudication": True,
                "critical_analysis_grounded": True,
                "adversarial_review_passed": True,
                "fail_closed": True,
            },
        }
        quality_audit = {
            "schema_version": 1,
            "created_at": _now(),
            "zotero_parent_key": zotero_parent_key,
            "source_pdf_sha256": _sha256_file(source_pdf_path),
            "protocol_version": self.config.protocol_version,
            "quality_report": quality_report,
            "roles": role_records,
        }
        synthesized_result = {
            key: value
            for key, value in review_result.items()
            if key not in {"output", "usage", "run_label"}
        }
        synthesis_record = role_records["card_synthesizer"]
        synthesis_execution = synthesis_record["execution"]
        synthesized_result.update(
            {
                "schema_version": 1,
                "ok": True,
                "component": "card_generator",
                "operation": "multi_agent_evidence_card_generation",
                "checked_at": _now(),
                "adapter": synthesis_execution.get("adapter"),
                "configured_model": (
                    None
                    if synthesis_execution.get("model") == "provider_default"
                    else synthesis_execution.get("model")
                ),
                "configured_reasoning_effort": (
                    None
                    if synthesis_execution.get("reasoning_effort") == "model_default"
                    else synthesis_execution.get("reasoning_effort")
                ),
                "generation_protocol_version": self.config.protocol_version,
                "ephemeral": True,
                "model_invoked": True,
                "source_access": synthesis_execution["source_access"],
                "usage": _usage_total(role_records),
                "output": synthesized,
                "workflow": quality_report,
                "quality_audit": quality_audit,
            }
        )
        report_progress(self.progress, "role_completed", role="adversarial_reviewer")
        report_progress(self.progress, "workflow_completed")
        return synthesized_result


__all__ = ["MultiAgentCardGeneratorAdapter"]
