"""A generated, human-readable layer over the product root.

The machine trees (``zotero/``, ``themes/``, ``evidence-packs/``) are
hash-chained: their bytes are recorded in ``_registry.json`` and rewritten only
by the pipeline that owns them. This module therefore never edits them. It reads
them and writes a separate layer that an Obsidian vault can navigate:

* ``<root>/HOME.md`` -- the entry page;
* ``<root>/cards/INDEX.md`` -- one row per parent item;
* ``<root>/cards/<parent_key>/card.md`` + ``figures/`` -- the reading edition;
* ``<root>/reading/themes/<theme_id>.md`` -- the current theme text with links
  recomputed for the moved layout.

Everything is deterministic: inputs are sorted, no timestamp is generated, and
files whose bytes already match are left untouched. Relative links are checked
after writing; a broken link makes the report fail instead of silently shipping.

This is orchestration only. It reads JSON and text from disk, so it depends on
neither adapters nor a model provider.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
OPERATION = "cards_index"

HOME_FILENAME = "HOME.md"
CARDS_DIRNAME = "cards"
INDEX_FILENAME = "INDEX.md"
READING_DIRNAME = "reading"
THEMES_DIRNAME = "themes"
EVIDENCE_DIRNAME = "evidence-packs"
DRAFT_READINGS_DIRNAME = "draft-readings"
FIGURE_DIRNAME = "figures"

VALIDATION_PASS = "PASS"
VALIDATION_FAIL = "FAIL"
VALIDATION_MISSING = "未校验"
BANNER_MARKER = "待校验主体卡草稿"
THEME_BODY_MARKER = "\n---\n程序维护的来源引用"

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".svg"})
_LINK_RE = re.compile(r"\]\((?:<([^>]+)>|([^)\s]+))\)")
_COMMENT_RE = re.compile(r"^<!--.*?-->\s*", re.DOTALL)


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _timestamp(value: Any) -> datetime:
    """Parse an ISO timestamp; unreadable values sort first, never raise."""

    if not isinstance(value, str):
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_yaml_scalar(item) for item in value) + "]"
    # A JSON double-quoted string is a valid YAML double-quoted scalar and
    # escapes quotes, backslashes and control characters for us.
    return json.dumps(str(value), ensure_ascii=False)


def _md_text(value: Any) -> str:
    text = " ".join(str(value if value is not None else "").split())
    for character in ("\\", "|", "[", "]"):
        text = text.replace(character, "\\" + character)
    return text


def _relative(target: Path, from_dir: Path) -> str:
    try:
        return Path(os.path.relpath(target, from_dir)).as_posix()
    except ValueError:
        # Windows paths on separate drives: fall back to an absolute path. The
        # link checker skips absolute targets, and so does this fallback.
        return target.as_posix()


def _file_link(text: str, target: Path, from_dir: Path) -> str:
    return f"[{text}](<{_relative(target, from_dir)}>)"


def _strip_banner(text: str) -> str:
    text = text.lstrip("﻿")
    if not text.startswith(">"):
        return text
    first, _, rest = text.partition("\n")
    if BANNER_MARKER not in first:
        return text
    return rest.lstrip("\n")


def _strip_leading_comments(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _COMMENT_RE.sub("", text, count=1)
    return text.lstrip("\n")


def _status_of(latest: dict[str, Any] | None) -> str:
    if latest is None:
        return VALIDATION_MISSING
    status = latest.get("status")
    return status if isinstance(status, str) and status.strip() else VALIDATION_MISSING


def _bool_text(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "未知"


def _year_of(item: dict[str, Any]) -> int | None:
    date = item.get("date")
    if not isinstance(date, str):
        return None
    match = re.match(r"\s*(\d{4})", date)
    return int(match.group(1)) if match else None


def _authors_of(item: dict[str, Any]) -> str | None:
    creators = item.get("creators")
    if isinstance(creators, list):
        joined = "；".join(str(value) for value in creators if str(value).strip())
        return joined or None
    if isinstance(creators, str) and creators.strip():
        return creators
    return None


def _write_text(path: Path, text: str, *, root: Path,
                written: list[str], unchanged: list[str]) -> None:
    data = (text if text.endswith("\n") else text + "\n").encode("utf-8")
    relative = path.relative_to(root).as_posix()
    if path.is_file() and path.read_bytes() == data:
        unchanged.append(relative)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    written.append(relative)


# --------------------------------------------------------------------------------------
# Draft scan and current-draft selection
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Draft:
    directory: Path
    data: dict[str, Any]
    validations: tuple[dict[str, Any], ...]

    @property
    def draft_id(self) -> str:
        value = self.data.get("draft_id")
        return value if isinstance(value, str) and value else self.directory.name

    @property
    def parent_key(self) -> str:
        source = self.data.get("source") or {}
        value = source.get("parent_key")
        return value if isinstance(value, str) else ""

    @property
    def latest_validation(self) -> dict[str, Any] | None:
        if not self.validations:
            return None
        return max(self.validations, key=lambda item: _timestamp(item.get("validated_at")))

    @property
    def created_at(self) -> datetime:
        return _timestamp(self.data.get("created_at"))


def _scan_drafts(root: Path, warnings: list[str]) -> list[_Draft]:
    drafts: list[_Draft] = []
    for path in sorted((root / "zotero").glob("*/drafts/*/draft.json")):
        data = _load_json(path)
        if not isinstance(data, dict):
            warnings.append(f"DRAFT_INVALID:{path.relative_to(root).as_posix()}")
            continue
        validations: list[dict[str, Any]] = []
        for validation_path in sorted((path.parent / "validations").glob("*/validation.json")):
            record = _load_json(validation_path)
            if isinstance(record, dict):
                validations.append(record)
        draft = _Draft(directory=path.parent, data=data, validations=tuple(validations))
        if not draft.parent_key:
            warnings.append(f"DRAFT_SOURCE_MISSING:{path.relative_to(root).as_posix()}")
            continue
        drafts.append(draft)
    return drafts


def _group_drafts(drafts: list[_Draft]) -> dict[str, list[_Draft]]:
    groups: dict[str, list[_Draft]] = {}
    for draft in drafts:
        groups.setdefault(draft.parent_key, []).append(draft)
    return groups


def _select_current(group: list[_Draft]) -> tuple[_Draft, str]:
    """R3: pass+verified beats newer-but-unverified; ties go to the newest."""

    eligible = [
        draft for draft in group
        if (latest := draft.latest_validation) is not None
        and latest.get("status") == VALIDATION_PASS
        and latest.get("reading_verified") is True
    ]
    if eligible:
        chosen = max(
            eligible,
            key=lambda draft: (
                _timestamp(draft.latest_validation.get("validated_at")),  # type: ignore[union-attr]
                draft.created_at,
                draft.draft_id,
            ),
        )
        return chosen, "最新校验 PASS 且 reading_verified=true"
    chosen = max(group, key=lambda draft: (draft.created_at, draft.draft_id))
    return chosen, "没有 PASS+verified 的草稿；取最新创建的一份"


# --------------------------------------------------------------------------------------
# Figure cache
# --------------------------------------------------------------------------------------


def _converter_of(draft: _Draft) -> tuple[str, str]:
    data = draft.data
    for key in ("reading_record", "source_access"):
        record = data.get(key)
        if isinstance(record, dict):
            converter_id = record.get("converter_id")
            converter_version = record.get("converter_version")
            if isinstance(converter_id, str) and isinstance(converter_version, str):
                return converter_id, converter_version
    provenance = data.get("provenance")
    if isinstance(provenance, dict):
        converter_id = provenance.get("converter_id")
        converter_version = provenance.get("converter_version")
        if isinstance(converter_id, str) and isinstance(converter_version, str):
            return converter_id, converter_version
    return "", ""


def _figure_source(draft: _Draft, runtime_dir: Path) -> Path | None:
    """Exact converter cache first; then any sibling conversion of the same PDF.

    The recorded converter wins. A different version (the usual cause of a miss
    after a converter upgrade) still produced the same figures from the same PDF,
    so it is a safe fallback -- but it is never guessed across PDFs.
    """

    source = draft.data.get("source") or {}
    pdf_sha256 = source.get("pdf_sha256")
    if not isinstance(pdf_sha256, str) or not pdf_sha256:
        return None
    paper_dir = runtime_dir / "papers" / pdf_sha256
    converter_id, converter_version = _converter_of(draft)
    if converter_id:
        exact = paper_dir / f"{converter_id}-{converter_version}" / FIGURE_DIRNAME
        if exact.is_dir():
            return exact
    if not paper_dir.is_dir():
        return None
    candidates = sorted(
        directory / FIGURE_DIRNAME
        for directory in paper_dir.iterdir()
        if directory.is_dir()
    )
    preferred = [path for path in candidates if converter_id and path.parent.name.startswith(converter_id)]
    for path in preferred + candidates:
        if path.is_dir():
            return path
    return None


def _copy_figures(source_dir: Path, target_dir: Path, *, root: Path,
                  written: list[str], unchanged: list[str]) -> list[Path]:
    copied: list[Path] = []
    wanted = sorted(
        path for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
    )
    for source in wanted:
        target = target_dir / source.name
        try:
            data = source.read_bytes()
        except OSError:
            continue
        relative = target.relative_to(root).as_posix()
        if target.is_file() and target.read_bytes() == data:
            unchanged.append(relative)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written.append(relative)
        copied.append(target)
    # Drop images a previous run copied but the cache no longer has, so the
    # card never embeds a stale picture that is not part of this reading.
    if target_dir.is_dir():
        keep = {path.name for path in copied}
        for stale in sorted(target_dir.iterdir()):
            if stale.is_file() and stale.suffix.lower() in _IMAGE_SUFFIXES and stale.name not in keep:
                stale.unlink()
                written.append(stale.relative_to(root).as_posix())
    return copied


# --------------------------------------------------------------------------------------
# Theme pool and readings
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Theme:
    theme_id: str
    title: str
    status: str
    directory: Path
    source_file: Path
    readings: tuple[dict[str, Any], ...]


def _scan_themes(root: Path, warnings: list[str]) -> list[_Theme]:
    themes_dir = root / THEMES_DIRNAME
    payload = _load_json(themes_dir / "_registry.json")
    record = payload.get("record") if isinstance(payload, dict) else None
    entries = record.get("themes") if isinstance(record, dict) else None
    if not isinstance(entries, dict):
        warnings.append("THEMES_REGISTRY_MISSING")
        return []
    themes: list[_Theme] = []
    for theme_id in sorted(entries):
        entry = entries[theme_id]
        if not isinstance(entry, dict):
            continue
        if entry.get("status") == "SUPERSEDED":
            continue
        current = entry.get("current") or {}
        relative = current.get("directory")
        if not isinstance(relative, str):
            warnings.append(f"THEME_VERSION_MISSING:{theme_id}")
            continue
        directory = themes_dir / relative
        source_file = directory / "revised.md"
        if not source_file.is_file():
            source_file = directory / "initial.md"
        if not source_file.is_file():
            warnings.append(f"THEME_VERSION_MISSING:{theme_id}")
            continue
        readings = current.get("readings")
        title = entry.get("title")
        themes.append(_Theme(
            theme_id=theme_id,
            title=title if isinstance(title, str) and title.strip() else theme_id,
            status=entry.get("status") if isinstance(entry.get("status"), str) else "",
            directory=directory,
            source_file=source_file,
            readings=tuple(ref for ref in (readings or []) if isinstance(ref, dict)),
        ))
    return themes


def _scan_readings(root: Path) -> dict[str, list[Path]]:
    """``EV-<key>`` -> reading.md files, sorted by reading id."""

    found: dict[str, list[Path]] = {}
    base = root / EVIDENCE_DIRNAME / DRAFT_READINGS_DIRNAME
    for path in sorted(base.glob("*/readings/*/reading.md")):
        evidence_id = path.parents[2].name
        found.setdefault(evidence_id, []).append(path)
    return found


def _theme_readings_text(theme: _Theme, root: Path, card_paths: dict[str, Path],
                         page_dir: Path) -> str:
    lines: list[str] = []
    for ref in theme.readings:
        source = ref.get("source") or {}
        evidence_id = source.get("evidence_id")
        parent_key = source.get("parent_key")
        relative = ref.get("directory")
        parts: list[str] = []
        card = card_paths.get(parent_key) if isinstance(parent_key, str) else None
        if card is not None:
            parts.append(_file_link(f"{evidence_id} 粗卡", card, page_dir))
        if isinstance(relative, str):
            reading = root / EVIDENCE_DIRNAME / relative / "reading.md"
            if reading.is_file():
                parts.append(_file_link("定向精读", reading, page_dir))
        if parts:
            lines.append("- " + " · ".join(parts))
    return "\n".join(lines)


def _theme_page(theme: _Theme, root: Path, card_paths: dict[str, Path],
                page_dir: Path) -> str:
    body = _strip_leading_comments(theme.source_file.read_text(encoding="utf-8"))
    marker = body.find(THEME_BODY_MARKER)
    if marker != -1:
        body = body[:marker]
    body = body.rstrip()
    if not body.startswith("#"):
        body = f"# {theme.title}\n\n{body}"
    source_note = theme.source_file.relative_to(root).as_posix()
    links = _theme_readings_text(theme, root, card_paths, page_dir)
    lines = [
        f"> 本页由 `uv run hydrolitagent cards index` 生成；源文件在 `{source_note}`（机器产物，不要手改）。",
        "",
        body,
        "",
        "---",
        "",
        "## 来源（重算的链接）",
        "",
        links or "- 当前版本没有登记来源。",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Card pages
# --------------------------------------------------------------------------------------


def _front_matter(entry: dict[str, Any]) -> str:
    fields = (
        ("title", entry["title"]),
        ("authors", entry["authors"]),
        ("year", entry["year"]),
        ("venue", entry["venue"]),
        ("doi", entry["doi"]),
        ("zotero_key", entry["parent_key"]),
        ("status", entry["status"]),
        ("validated_at", entry["validated_at"]),
        ("reading_verified", entry["reading_verified"]),
        ("source_pdf", entry["source_pdf"]),
        ("tags", entry["tags"]),
    )
    lines = ["---"]
    lines.extend(f"{name}: {_yaml_scalar(value)}" for name, value in fields)
    lines.append("---")
    return "\n".join(lines)


def _status_line(entry: dict[str, Any]) -> str:
    return (
        f"> 状态：{entry['status']} · "
        f"production_eligible：{_bool_text(entry['production_eligible'])} · "
        f"scientific_correctness_verified：{_bool_text(entry['scientific_correctness_verified'])} · "
        f"reading_verified：{entry['reading_verified_display']} · "
        f"当前草稿：`{entry['draft_id']}`"
    )


def _related_themes_text(entry: dict[str, Any], path: Path,
                         theme_paths: dict[str, Path],
                         theme_titles: dict[str, str]) -> str:
    lines: list[str] = []
    for theme_id in entry["theme_ids"]:
        theme_path = theme_paths.get(theme_id)
        if theme_path is None:
            continue
        label = _md_text(theme_titles.get(theme_id, theme_id))
        lines.append(f"- {_file_link(label, theme_path, path.parent)}")
    return "\n".join(lines)


def _reading_links_text(entry: dict[str, Any], path: Path) -> str:
    lines = [
        f"- {_file_link(_md_text(reading.parent.name), reading, path.parent)} "
        f"（{_md_text(reading.parents[2].name)}）"
        for reading in entry["readings"]
    ]
    return "\n".join(lines)


def _figures_text(entry: dict[str, Any], path: Path) -> str:
    if not entry["figures"]:
        if entry["figure_warning"]:
            return (
                f"> 警告：{entry['figure_warning']} —— 转换缓存里没有这篇论文的插图，"
                "本页没有内嵌图。"
            )
        return "> 转换缓存中没有插图。"
    lines = [
        f"![{_md_text(figure.stem)}](<{_relative(figure, path.parent)}>)"
        for figure in entry["figures"]
    ]
    return "\n".join(lines)


def _card_page(entry: dict[str, Any], path: Path,
               theme_paths: dict[str, Path],
               theme_titles: dict[str, str]) -> str:
    source_lines = [
        f"- Zotero 条目：[在 Zotero 中打开](zotero://select/library/items/{entry['parent_key']})"
    ]
    if entry["attachment_key"]:
        source_lines.append(
            f"- PDF 附件：[打开 PDF](zotero://open-pdf/library/items/{entry['attachment_key']})"
        )
    if entry["doi"]:
        source_lines.append(f"- DOI：[{_md_text(entry['doi'])}](https://doi.org/{entry['doi']})")
    related = _related_themes_text(entry, path, theme_paths, theme_titles)
    readings = _reading_links_text(entry, path)
    lines = [
        _front_matter(entry),
        "",
        _status_line(entry),
        "",
        entry["body"].rstrip(),
        "",
        "## 来源",
        "",
        "\n".join(source_lines),
        "",
        "## 相关主题",
        "",
        related or "- 暂无（该卡尚未被任何候选主题引用）",
        "",
        "## 定向精读",
        "",
        readings or "- 暂无定向精读记录",
        "",
        "## 图",
        "",
        _figures_text(entry, path),
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Home and index
# --------------------------------------------------------------------------------------


def _index_page(entries: list[dict[str, Any]], root: Path) -> str:
    lines = [
        "# 文献卡索引",
        "",
        "> 本页由 `uv run hydrolitagent cards index` 生成。每篇论文只列**当前选中**的一份草稿；"
        "机器原稿在 `zotero/` 下，不要手改。",
        "",
        "| 条目 | 标题 | 年份 | 状态 | 校验时间 | 选中草稿 | 选择依据 | 卡片 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    index_path = root / CARDS_DIRNAME / INDEX_FILENAME
    for entry in entries:
        card_path = root / CARDS_DIRNAME / entry["parent_key"] / "card.md"
        year = entry["year"] if entry["year"] is not None else "—"
        validated = entry["validated_at"] or "—"
        lines.append(
            f"| `{entry['parent_key']}` "
            f"| {_md_text(entry['title'])} "
            f"| {year} "
            f"| {entry['status']} "
            f"| {_md_text(validated)} "
            f"| `{entry['draft_id']}` "
            f"| {_md_text(entry['reason'])} "
            f"| {_file_link('阅读版', card_path, index_path.parent)} |"
        )
    if not entries:
        lines.append("| — | 还没有可读的草稿 | — | — | — | — | — | — |")
    lines.append("")
    return "\n".join(lines)


def _home_page(entries: list[dict[str, Any]], themes: list[_Theme], root: Path) -> str:
    home = root / HOME_FILENAME
    lines = [
        "# 文献阅读层",
        "",
        "> 本页由 `uv run hydrolitagent cards index` 生成。机器产物在 `zotero/`、`themes/`、"
        "`evidence-packs/`；本层（`HOME.md`、`cards/`、`reading/`）可以随时重建，不要手改。",
        "",
        "## 怎么读",
        "",
        "1. 在 Obsidian 里选 **Open folder as vault**，指向**产物根**（默认 `outputs/`）。",
        "2. 从本页开始：下面每一行都能点到卡片或主题。",
        "3. 卡片底部有来源、相关主题与定向精读；图直接内嵌在卡片页。",
        "",
        "## 文献卡",
        "",
    ]
    if entries:
        for entry in entries:
            card_path = root / CARDS_DIRNAME / entry["parent_key"] / "card.md"
            year = f"{entry['year']} · " if entry["year"] is not None else ""
            lines.append(
                f"- {_file_link(_md_text(entry['title']), card_path, home.parent)} · "
                f"{year}{entry['status']}"
            )
    else:
        lines.append("- 还没有可读的草稿；先跑 `evidence-generate` 与 `evidence-validate`。")
    lines.extend(["", f"- 全部卡片：[文献卡索引](<{CARDS_DIRNAME}/{INDEX_FILENAME}>)", "", "## 主题", ""])
    theme_index = root / THEMES_DIRNAME / "index.md"
    theme_paths = {theme.theme_id: root / READING_DIRNAME / THEMES_DIRNAME / f"{theme.theme_id}.md"
                   for theme in themes}
    if theme_index.is_file():
        lines.append(f"- 主题池入口（机器产物）：{_file_link('themes/index.md', theme_index, home.parent)}")
    for theme in themes:
        lines.append(
            f"- {_file_link(_md_text(theme.title), theme_paths[theme.theme_id], home.parent)} · "
            f"{_md_text(theme.status)}"
        )
    if not themes:
        lines.append("- 还没有候选主题。")
    lines.extend([
        "",
        "## 说明",
        "",
        "- 阅读层是**生成物**：重跑 `cards index` 会更新 `HOME.md`、`cards/` 与 `reading/`。",
        "- 旧目录 `survey-ai-scientist/`、`_archive/` 与其他 vault 杂项**不在**本阅读层。",
        "- 卡片状态取自最新 `validation.json`；`PASS` 只表示确定性规则通过，不证明科学正确。",
        "",
    ])
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Link self-check
# --------------------------------------------------------------------------------------


def _check_links(paths: list[Path], root: Path) -> tuple[int, list[dict[str, str]]]:
    checked = 0
    broken: list[dict[str, str]] = []
    for path in sorted(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in _LINK_RE.finditer(text):
            target = match.group(1) or match.group(2) or ""
            target = target.split("#", 1)[0].strip()
            if not target:
                continue
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith("/"):
                continue
            checked += 1
            if not (path.parent / target).exists():
                broken.append({
                    "file": path.relative_to(root).as_posix(),
                    "target": target,
                })
    return checked, broken


# --------------------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------------------


def build_reading_layer(root: Path, *, runtime_dir: Path | None = None) -> dict[str, Any]:
    """Generate the reading layer under ``root`` and return a machine report."""

    root = Path(root)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "operation": OPERATION,
        "ok": False,
        "root": str(root),
        "runtime_dir": str(runtime_dir) if runtime_dir is not None else None,
        "written": [],
        "unchanged": [],
        "warnings": [],
        "links_checked": 0,
        "broken_links": [],
        "card_count": 0,
        "theme_count": 0,
    }
    if not root.is_dir():
        report["error"] = {"code": "READING_ROOT_MISSING", "message": f"产物根不存在：{root}"}
        return report
    runtime = Path(runtime_dir) if runtime_dir is not None else root.parent / ".runtime"
    report["runtime_dir"] = str(runtime)

    written: list[str] = report["written"]
    unchanged: list[str] = report["unchanged"]
    warnings: list[str] = report["warnings"]

    drafts = _scan_drafts(root, warnings)
    themes = _scan_themes(root, warnings)
    reading_index = _scan_readings(root)
    theme_titles = {theme.theme_id: theme.title for theme in themes}
    groups = _group_drafts(drafts)
    # EV -> theme ids whose current version cites it, and EV -> its reading refs.
    theme_readings: dict[str, list[str]] = {}
    theme_reading_refs: dict[str, list[dict[str, Any]]] = {}
    for theme in themes:
        for ref in theme.readings:
            evidence_id = (ref.get("source") or {}).get("evidence_id")
            if not isinstance(evidence_id, str):
                continue
            theme_readings.setdefault(evidence_id, []).append(theme.theme_id)
            theme_reading_refs.setdefault(evidence_id, []).append(ref)

    generated: list[Path] = []
    card_paths: dict[str, Path] = {}
    entries: list[dict[str, Any]] = []

    for parent_key in sorted(groups):
        chosen, reason = _select_current(groups[parent_key])
        data = chosen.data
        source = data.get("source") or {}
        item = source.get("item") if isinstance(source.get("item"), dict) else {}
        latest = chosen.latest_validation
        status = _status_of(latest)
        evidence_id = f"EV-{parent_key}"
        tags = sorted(set(theme_readings.get(evidence_id, [])))

        card_dir = root / CARDS_DIRNAME / parent_key
        card_path = card_dir / "card.md"
        source_figures = _figure_source(chosen, runtime)
        copied: list[Path] = []
        warning = ""
        if source_figures is None:
            warning = f"FIGURE_CACHE_MISSING:{parent_key}"
            warnings.append(warning)
        else:
            copied = _copy_figures(
                source_figures, card_dir / FIGURE_DIRNAME, root=root,
                written=written, unchanged=unchanged,
            )

        required_readings = [
            root / EVIDENCE_DIRNAME / ref["directory"] / "reading.md"
            for ref in theme_reading_refs.get(evidence_id, [])
            if isinstance(ref.get("directory"), str)
        ]
        ordered = list(dict.fromkeys(required_readings))
        remaining = [
            path for path in reading_index.get(evidence_id, [])
            if path not in ordered
        ]
        readings = [path for path in ordered if path.is_file()]
        readings.extend(path for path in remaining if path.is_file())

        entry = {
            "parent_key": parent_key,
            "draft_id": chosen.draft_id,
            "reason": reason,
            "title": item.get("title") if isinstance(item.get("title"), str) else parent_key,
            "authors": _authors_of(item),
            "year": _year_of(item),
            "venue": item.get("venue") if isinstance(item.get("venue"), str) else None,
            "doi": item.get("doi") if isinstance(item.get("doi"), str) else None,
            "attachment_key": source.get("attachment_key") if isinstance(source.get("attachment_key"), str) else "",
            "status": status,
            "validated_at": latest.get("validated_at") if latest else None,
            "reading_verified": latest.get("reading_verified") if latest else None,
            "reading_verified_display": _bool_text(latest.get("reading_verified") if latest else None),
            "production_eligible": latest.get("production_eligible") if latest else data.get("production_eligible"),
            "scientific_correctness_verified": (
                latest.get("scientific_correctness_verified") if latest
                else data.get("scientific_correctness_verified")
            ),
            "source_pdf": (
                f"zotero://open-pdf/library/items/{source['attachment_key']}"
                if isinstance(source.get("attachment_key"), str) else None
            ),
            "tags": tags,
            "theme_ids": tags,
            "body": _strip_banner(data.get("card_body_markdown") or ""),
            "figures": copied,
            "figure_warning": warning,
            "readings": readings,
        }
        entries.append(entry)
        card_paths[parent_key] = card_path

    # Theme pages need the card path map, so write them after selection.
    theme_paths: dict[str, Path] = {}
    for theme in themes:
        theme_path = root / READING_DIRNAME / THEMES_DIRNAME / f"{theme.theme_id}.md"
        theme_paths[theme.theme_id] = theme_path
        _write_text(theme_path, _theme_page(theme, root, card_paths, theme_path.parent),
                    root=root, written=written, unchanged=unchanged)
        generated.append(theme_path)

    for entry in entries:
        card_path = card_paths[entry["parent_key"]]
        _write_text(card_path, _card_page(entry, card_path, theme_paths, theme_titles),
                    root=root, written=written, unchanged=unchanged)
        generated.append(card_path)

    index_path = root / CARDS_DIRNAME / INDEX_FILENAME
    _write_text(index_path, _index_page(entries, root), root=root,
                written=written, unchanged=unchanged)
    generated.append(index_path)

    home_path = root / HOME_FILENAME
    _write_text(home_path, _home_page(entries, themes, root), root=root,
                written=written, unchanged=unchanged)
    generated.append(home_path)

    checked, broken = _check_links(generated, root)
    report["links_checked"] = checked
    report["broken_links"] = broken
    report["card_count"] = len(entries)
    report["theme_count"] = len(themes)
    report["ok"] = not broken
    return report


__all__ = ["build_reading_layer"]
