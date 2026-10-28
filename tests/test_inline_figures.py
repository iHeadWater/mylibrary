"""Reading layer: figures are inlined at their first mention.

The reading edition used to pile every figure into a trailing ``## 图``
section. A reader who reaches "（Figure 6）" wants the picture there, not
eight screens later. These tests pin the deterministic rules:

* a figure is inlined once, after the paragraph that first cites it;
* a mention inside a bullet keeps the embed inside that bullet (4 spaces);
* code fences and table rows are never written into;
* anything not cited -- including a caption with no parseable number -- goes
  to a small appendix instead of a full trailing gallery;
* regenerating twice is byte-identical and every embedded path exists.
"""

from __future__ import annotations

import json
from pathlib import Path

from hydrolitagent.cards.application.reading_layer import (
    InlineFigure,
    build_reading_layer,
    inline_figures,
)


# --------------------------------------------------------------------------------------
# Pure insertion rules (AC1-AC7)
# --------------------------------------------------------------------------------------


def test_inlines_after_first_mention_paragraph_only() -> None:
    body = (
        "# 标题\n"
        "\n"
        "第一段引用（Figure 2）说明结果。\n"
        "\n"
        "第二段仍然（Figure 2）提到同一张图。\n"
    )
    figures = [InlineFigure(path="figures/page-002-fig-1.png", caption="Figure 2. 降雨与径流")]

    new_body, unreferenced = inline_figures(body, figures)

    assert unreferenced == []
    assert new_body.count("![Figure 2]") == 1
    # Between the first paragraph and the second one.
    assert new_body.index("说明结果。") < new_body.index("![Figure 2]") < new_body.index("第二段")
    assert "*图 2：降雨与径流*" in new_body
    assert "## 图" not in new_body


def test_a_figure_is_never_inlined_twice() -> None:
    body = "甲（Figure 2）。\n\n乙（Figure 2）。\n\n丙 Figure 2 又一次。\n"
    figures = [InlineFigure(path="figures/page-002-fig-1.png", caption="Figure 2. 图注")]

    new_body, _ = inline_figures(body, figures)

    assert new_body.count("![Figure 2]") == 1


def test_bullet_mention_indents_the_block_four_spaces() -> None:
    body = "- 第一条（Figure 3）\n- 第二条\n"
    figures = [InlineFigure(path="figures/page-003-fig-1.png", caption="Figure 3. 示意图")]

    new_body, _ = inline_figures(body, figures)
    lines = new_body.splitlines()

    assert "    ![Figure 3](<figures/page-003-fig-1.png>)" in lines
    assert "    *图 3：示意图*" in lines
    assert lines.index("    ![Figure 3](<figures/page-003-fig-1.png>)") < lines.index("- 第二条")


def test_table_reference_matches_a_table_image() -> None:
    body = "结果见（Table 1），参数见（表 1）。\n"
    figures = [InlineFigure(path="figures/page-018-table-1.png", caption="Table 1. 参数与取值")]

    new_body, unreferenced = inline_figures(body, figures)

    assert unreferenced == []
    assert new_body.count("![Table 1]") == 1
    assert "*表 1：参数与取值*" in new_body


def test_unreferenced_figures_are_returned_for_the_appendix() -> None:
    body = "只引用（Figure 1）。\n"
    figures = [
        InlineFigure(path="figures/page-001-fig-1.png", caption="Figure 1. 已引用"),
        InlineFigure(path="figures/page-004-fig-1.png", caption="Figure 4. 未引用"),
    ]

    new_body, unreferenced = inline_figures(body, figures)

    assert [figure.path for figure in unreferenced] == ["figures/page-004-fig-1.png"]
    assert "page-004-fig-1.png" not in new_body


def test_caption_without_a_number_goes_to_the_appendix() -> None:
    body = "讨论（Figure 5）的结果。\n"
    figures = [InlineFigure(path="figures/page-005-fig-1.png", caption="没有编号的图注")]

    new_body, unreferenced = inline_figures(body, figures)

    assert "![Figure 5]" not in new_body
    assert [figure.path for figure in unreferenced] == ["figures/page-005-fig-1.png"]


def test_no_figures_leaves_the_body_untouched() -> None:
    body = "# A\n\n正文没有任何图。\n"

    new_body, unreferenced = inline_figures(body, [])

    assert new_body == body
    assert unreferenced == []


def test_body_without_mentions_sends_every_figure_to_the_appendix() -> None:
    body = "# A\n\n正文完全不含图号。\n"
    figures = [
        InlineFigure(path="figures/page-001-fig-1.png", caption="Figure 1. 一"),
        InlineFigure(path="figures/page-002-fig-1.png", caption="Figure 2. 二"),
    ]

    new_body, unreferenced = inline_figures(body, figures)

    assert new_body == body
    assert [figure.path for figure in unreferenced] == [figure.path for figure in figures]


def test_code_fences_and_table_rows_are_not_written_into() -> None:
    body = (
        "```\n"
        "代码里提到 Figure 7\n"
        "```\n"
        "\n"
        "| 列 | 值（Figure 7） |\n"
        "|---|---|\n"
        "| a | b |\n"
        "\n"
        "正文没有提图。\n"
    )
    figures = [InlineFigure(path="figures/page-007-fig-1.png", caption="Figure 7. 图注")]

    new_body, unreferenced = inline_figures(body, figures)

    assert new_body.count("![Figure 7]") == 0
    assert [figure.path for figure in unreferenced] == ["figures/page-007-fig-1.png"]


def test_regeneration_is_byte_identical() -> None:
    body = "第一段（Figure 2）。\n\n第二段（Table 1）。\n"
    figures = [
        InlineFigure(path="figures/page-002-fig-1.png", caption="Figure 2. 降雨"),
        InlineFigure(path="figures/page-018-table-1.png", caption="Table 1. 参数"),
    ]

    first, _ = inline_figures(body, figures)
    second, _ = inline_figures(body, figures)

    assert first == second


# --------------------------------------------------------------------------------------
# End to end through build_reading_layer (AC8 + appendix wiring)
# --------------------------------------------------------------------------------------


SHA = "c" * 64


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_root_with(
    tmp_path: Path,
    *,
    body: str,
    image_names: tuple[str, ...],
    manifest_figures: list[dict[str, object]],
) -> tuple[Path, Path]:
    """A product root whose conversion cache holds exactly ``image_names``."""

    root = tmp_path / "outputs"
    root.mkdir()
    draft = {
        "schema_version": 2,
        "draft_id": "draft-pass",
        "created_at": "2026-01-02T00:00:00Z",
        "source": {
            "parent_key": "AAAA1111",
            "attachment_key": "ATTACH01",
            "pdf_sha256": SHA,
            "item": {"title": "论文 A", "date": "2020", "doi": "10.1/a"},
        },
        "card_body_markdown": body,
        "reading_record": {"converter_id": "pymupdf", "converter_version": "1.0"},
    }
    _write_json(root / "zotero" / "user-0-AAAA1111" / "drafts" / "draft-pass" / "draft.json", draft)

    paper_dir = tmp_path / ".runtime" / "papers" / SHA / "pymupdf-1.0"
    figures_dir = paper_dir / "figures"
    figures_dir.mkdir(parents=True)
    for name in image_names:
        (figures_dir / name).write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode("utf-8"))
    _write_json(
        paper_dir / "manifest.json",
        {"manifest_version": 2, "figures": manifest_figures},
    )
    return root, tmp_path / ".runtime"


def _build_root(tmp_path: Path) -> tuple[Path, Path]:
    return _build_root_with(
        tmp_path,
        body=(
            "# 卡\n"
            "\n"
            "正文第一段（Figure 2）。\n"
            "\n"
            "第二段没有图。\n"
        ),
        image_names=("page-002-fig-1.png", "page-018-table-1.png"),
        manifest_figures=[
            {
                "path": "figures/page-002-fig-1.png",
                "caption": "Figure 2. 降雨与径流",
            },
            # No caption at all: must land in the appendix.
            {"path": "figures/page-018-table-1.png", "caption": None},
        ],
    )


# --------------------------------------------------------------------------------------
# Table renders are absent from the manifest (their number lives in the filename)
# --------------------------------------------------------------------------------------


def _card_of(root: Path) -> str:
    return (root / "cards" / "AAAA1111" / "card.md").read_text(encoding="utf-8")


def test_unlisted_table_image_is_inlined_at_its_reference(tmp_path: Path) -> None:
    # The converter renders a table as page-018-table-1.png without recording
    # it in manifest.json, so the caption has to come from the filename.
    root, runtime = _build_root_with(
        tmp_path,
        body="# 卡\n\n参数见（表 1）。\n\n后续段落。\n",
        image_names=("page-018-table-1.png",),
        manifest_figures=[],
    )

    report = build_reading_layer(root, runtime_dir=runtime)

    assert report["ok"], report
    card = _card_of(root)
    assert "![Table 1](<figures/page-018-table-1.png>)" in card
    assert card.index("参数见") < card.index("page-018-table-1.png")
    assert "*表 1*" in card
    assert "## 未在正文引用的图" not in card


def test_english_table_reference_matches_the_numbered_file(tmp_path: Path) -> None:
    root, runtime = _build_root_with(
        tmp_path,
        body="# 卡\n\n结果见（Table 2）。\n",
        image_names=("page-020-table-2.png",),
        manifest_figures=[],
    )

    report = build_reading_layer(root, runtime_dir=runtime)

    assert report["ok"], report
    card = _card_of(root)
    assert "![Table 2](<figures/page-020-table-2.png>)" in card
    assert "## 未在正文引用的图" not in card


def test_table_mention_without_a_matching_file_inserts_nothing(tmp_path: Path) -> None:
    root, runtime = _build_root_with(
        tmp_path,
        body="# 卡\n\n见（表 3）。\n",
        image_names=("page-018-table-1.png",),
        manifest_figures=[],
    )

    report = build_reading_layer(root, runtime_dir=runtime)

    assert report["ok"], report
    card = _card_of(root)
    assert "![Table 3]" not in card
    # The unrelated table image still reaches the appendix.
    appendix = card.split("## 未在正文引用的图", 1)[1]
    assert "page-018-table-1.png" in appendix


def test_page_figure_counter_is_not_a_figure_number(tmp_path: Path) -> None:
    # page-016-fig-1.png is "the first figure crop on page 16", not Figure 1.
    root, runtime = _build_root_with(
        tmp_path,
        body="# 卡\n\n正文引用了（Figure 1）。\n",
        image_names=("page-016-fig-1.png",),
        manifest_figures=[{"path": "figures/page-016-fig-1.png", "caption": None}],
    )

    report = build_reading_layer(root, runtime_dir=runtime)

    assert report["ok"], report
    card = _card_of(root)
    assert "![Figure 1]" not in card
    appendix = card.split("## 未在正文引用的图", 1)[1]
    assert "page-016-fig-1.png" in appendix


def test_manifest_caption_wins_over_the_filename(tmp_path: Path) -> None:
    root, runtime = _build_root_with(
        tmp_path,
        body="# 卡\n\n参数见（表 1）。\n",
        image_names=("page-018-table-1.png",),
        manifest_figures=[
            {"path": "figures/page-018-table-1.png", "caption": "Table 1. 参数与取值"}
        ],
    )

    report = build_reading_layer(root, runtime_dir=runtime)

    assert report["ok"], report
    card = _card_of(root)
    assert "*表 1：参数与取值*" in card
    assert card.count("page-018-table-1.png") == 1


def _read_non_machine(root: Path) -> dict[str, bytes]:
    machine = ("zotero/", "themes/", "evidence-packs/")
    tree: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.relative_to(root).as_posix().startswith(machine):
            tree[path.relative_to(root).as_posix()] = path.read_bytes()
    return tree


def test_reading_edition_inlines_and_links_resolve(tmp_path: Path) -> None:
    root, runtime = _build_root(tmp_path)

    report = build_reading_layer(root, runtime_dir=runtime)

    assert report["ok"], report
    assert report["broken_links"] == []
    assert report["links_checked"] > 0
    card = (root / "cards" / "AAAA1111" / "card.md").read_text(encoding="utf-8")

    assert "## 图\n" not in card
    assert card.index("正文第一段") < card.index("![Figure 2]") < card.index("## 来源")
    assert "*图 2：降雨与径流*" in card
    assert "## 未在正文引用的图" in card
    appendix = card.split("## 未在正文引用的图", 1)[1]
    assert "page-018-table-1.png" in appendix
    assert "page-002-fig-1.png" not in appendix


def test_second_build_is_byte_identical(tmp_path: Path) -> None:
    root, runtime = _build_root(tmp_path)

    first = build_reading_layer(root, runtime_dir=runtime)
    snapshot = _read_non_machine(root)
    second = build_reading_layer(root, runtime_dir=runtime)

    assert first["ok"] and second["ok"], second
    assert second["written"] == []
    assert _read_non_machine(root) == snapshot
    assert first["links_checked"] == second["links_checked"]
