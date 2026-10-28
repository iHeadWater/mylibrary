"""Prompt assets and the template-driven prompt bundle.

A card run needs three things from disk before any executor is involved:

* the reading prompt (``prompt_version`` + content digest),
* the enabled card templates from the asset catalog,
* one combined prompt that embeds the task identity and the template bodies.

This module owns that assembly. It is pure file reading plus string building: it
never calls a model and never decides which executor runs.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from hydrolitagent.cards.domain.errors import CardGenerationError
from hydrolitagent.cards.evidence_templates import (
    EvidenceTemplateError,
    validate_evidence_templates,
)

PROMPT_VERSION_PATTERN = re.compile(
    r'^---\s*\r?\nprompt_version:\s*["\']([^"\']+)["\']\s*\r?\n---',
    re.MULTILINE,
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_prompt(path: Path) -> dict[str, str]:
    """Read one UTF-8 prompt asset with its front-matter version and digest."""

    try:
        content = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CardGenerationError(
            "CARD_GENERATION_PROMPT_INVALID",
            f"无法读取 UTF-8 制卡提示词：{path}",
        ) from exc
    match = PROMPT_VERSION_PATTERN.search(content)
    if match is None or not match.group(1).strip():
        raise CardGenerationError(
            "CARD_GENERATION_PROMPT_INVALID",
            "制卡提示词缺少 prompt_version",
        )
    return {
        "version": match.group(1).strip(),
        "sha256": sha256_text(content),
        "content": content,
    }


def _template_body(content: str, template_file: Path) -> str:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise CardGenerationError(
            "EVIDENCE_TEMPLATE_INVALID",
            f"模板缺少 front matter：{template_file.name}",
        )
    try:
        closing = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise CardGenerationError(
            "EVIDENCE_TEMPLATE_INVALID",
            f"模板 front matter 未闭合：{template_file.name}",
        ) from exc
    body = "\n".join(lines[closing + 1 :]).strip()
    if not body:
        raise CardGenerationError(
            "EVIDENCE_TEMPLATE_INVALID",
            f"模板正文为空：{template_file.name}",
        )
    return body + "\n"


def load_template_bundle(
    templates_dir: Path,
    catalog_file: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Return ``(catalog, enabled templates keyed by template_id)``."""

    try:
        catalog = validate_evidence_templates(templates_dir, catalog_file)
    except EvidenceTemplateError as exc:
        raise CardGenerationError(exc.code, str(exc)) from exc

    templates: dict[str, dict[str, Any]] = {}
    for entry in catalog["templates"]:
        if not entry["enabled"]:
            continue
        template_file = (Path(templates_dir) / entry["file"]).resolve()
        try:
            content = template_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise CardGenerationError(
                "EVIDENCE_TEMPLATE_INVALID",
                f"无法读取 UTF-8 模板：{template_file}",
            ) from exc
        templates[entry["template_id"]] = {
            **entry,
            "body": _template_body(content, template_file),
        }
    if not templates:
        raise CardGenerationError(
            "EVIDENCE_TEMPLATE_CATALOG_INVALID",
            "没有可供制卡器选择的已启用模板",
        )
    return catalog, templates


def build_template_prompt(
    prompt_info: dict[str, str],
    context: dict[str, Any],
    templates: dict[str, dict[str, Any]],
) -> str:
    """Embed the task identity and the enabled template bodies into one prompt."""

    sections = [
        prompt_info["content"].rstrip(),
        "\n## 本次任务身份\n",
        "```json\n" + json.dumps(context, ensure_ascii=False, indent=2) + "\n```",
        "\n## 已启用模板正文",
    ]
    for template_id in sorted(templates):
        sections.extend(
            [
                f'\n<evidence-card-template id="{template_id}">',
                templates[template_id]["body"].rstrip(),
                "</evidence-card-template>",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


__all__ = [
    "PROMPT_VERSION_PATTERN",
    "build_template_prompt",
    "load_template_bundle",
    "read_prompt",
    "sha256_text",
]
