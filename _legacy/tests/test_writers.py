from __future__ import annotations

from hydro_miner.writers import markdown_cell, markdown_table


def test_markdown_cell_escapes_table_breaking_characters() -> None:
    assert markdown_cell("A|B\nC") == r"A\|B<br>C"


def test_markdown_table_uses_placeholder_for_empty_rows() -> None:
    assert markdown_table(["A"], []) == ["_暂无条目。_"]
