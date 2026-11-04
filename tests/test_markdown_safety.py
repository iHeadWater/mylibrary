"""The reading layer escapes bare ``<TOKEN>`` literals before a reader sees them.

Obsidian Live Preview starts an HTML block at an unknown, unclosed tag and stops
rendering Markdown after it, so a model placeholder such as ``<CLASS>`` silently
swallows the rest of a card. The machine drafts stay byte-identical; only the
generated pages change.
"""

from __future__ import annotations

from pathlib import Path

from hydrolitagent.cards.application.markdown_safety import escape_html_like
from hydrolitagent.cards.application.reading_layer import _Theme, _theme_page


def test_bare_placeholder_is_escaped() -> None:
    assert escape_html_like("参数为 <CLASS> 与 <METHOD>。") == (
        "参数为 &lt;CLASS&gt; 与 &lt;METHOD&gt;。"
    )


def test_whitelisted_html_tags_survive() -> None:
    text = '<details><summary>点击</summary><br><sub>a</sub><sup>b</sup>' \
           '<kbd>Ctrl</kbd><mark>m</mark><span>x</span><code>y</code></details>'
    assert escape_html_like(text) == text


def test_whitelist_is_case_insensitive() -> None:
    text = "<DETAILS><SUMMARY>x</SUMMARY></DETAILS>"
    assert escape_html_like(text) == text


def test_inline_code_is_untouched() -> None:
    assert escape_html_like("值 `<PAD>` 不变") == "值 `<PAD>` 不变"


def test_inline_maths_is_untouched() -> None:
    assert escape_html_like("设 $<x>$ 与 $\\<y\\>$") == "设 $<x>$ 与 $\\<y\\>$"


def test_display_maths_block_is_untouched() -> None:
    text = "$$\n<CLASS> = a < b\n$$"
    assert escape_html_like(text) == text


def test_single_line_display_maths_is_untouched() -> None:
    assert escape_html_like("$$<a>$$ 后") == "$$<a>$$ 后"


def test_prose_after_single_line_maths_is_escaped() -> None:
    # The maths span is literal; the prose after it is not. Skipping the whole
    # line would let a bare placeholder switch Obsidian into an HTML block.
    assert escape_html_like("$$E=mc^2$$ 其中 <CLASS> 是类") == (
        "$$E=mc^2$$ 其中 &lt;CLASS&gt; 是类"
    )


def test_fenced_code_block_is_untouched() -> None:
    text = "前文 <CLASS>\n```python\nx = '<TAG>'\n```\n后文 <TAG>"
    assert escape_html_like(text) == (
        "前文 &lt;CLASS&gt;\n```python\nx = '<TAG>'\n```\n后文 &lt;TAG&gt;"
    )


def test_tilde_fence_is_untouched() -> None:
    text = "~~~\n<TAG>\n~~~"
    assert escape_html_like(text) == text


def test_markdown_link_destination_is_untouched() -> None:
    text = "见图 [图 1](<figures/a b.png>)。"
    assert escape_html_like(text) == text


def test_image_destination_is_untouched() -> None:
    text = "![Table 1](<figures/page-001-table-1.png>)"
    assert escape_html_like(text) == text


def test_bare_url_is_untouched() -> None:
    text = "见 https://example.org/<path> 原文"
    assert escape_html_like(text) == text


def test_placeholder_inside_link_text_is_left_alone() -> None:
    # The whole link is a literal span; rewriting inside it would break the
    # destination, and the model's <TOKEN> there is link text, not prose.
    text = "[<CLASS>](<figures/a.png>)"
    assert escape_html_like(text) == text


def test_escaping_is_idempotent() -> None:
    once = escape_html_like("值 <CLASS> 与 <DETAILS>x</DETAILS>")
    assert escape_html_like(once) == once


def test_pipe_table_rows_are_escaped() -> None:
    text = "| 项 | 值 |\n| --- | --- |\n| <CLASS> | 1 |"
    assert escape_html_like(text) == (
        "| 项 | 值 |\n| --- | --- |\n| &lt;CLASS&gt; | 1 |"
    )


def test_theme_page_escapes_bare_tokens_after_citation_rewrite(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    source = root / "themes" / "candidates" / "TH-1" / "revised.md"
    source.parent.mkdir(parents=True)
    source.write_text("# 标题\n\n正文 <CLASS>。\n", encoding="utf-8")
    theme = _Theme(
        theme_id="TH-1", title="标题", status="CANDIDATE_REFINED",
        directory=source.parent, source_file=source, readings=(),
    )

    page = _theme_page(theme, root, {}, tmp_path, {})

    assert "&lt;CLASS&gt;" in page
    assert "<CLASS>" not in page
