"""视频笔记流水线的纯函数测试。

只测「不该由模型决定」的部分：章节覆盖校验、按字数均分、配图与段落的顺序约束与
去重、拼装出来的链接形态。这些都是出过一次错就会整篇烂掉的硬约束。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydrolitagent.literature.video_notes import assemble, bodies, frames, layout, outline, proofread


# ---------------------------------------------------------------- ② → ③ 合并
def _segs(*pairs):
    return [{"start": s, "end": e, "text": t} for s, e, t in pairs]


def test_merge_blocks_splits_on_gap():
    segs = _segs((0.0, 2.0, "第一句。"), (2.2, 4.0, "第二句。"), (9.0, 11.0, "很久以后。"))
    blocks = proofread.merge_blocks(segs)
    assert [b["text"] for b in blocks] == ["第一句。第二句。", "很久以后。"]
    assert blocks[0]["end"] == 4.0


def test_merge_blocks_splits_on_length():
    segs = _segs((0.0, 1.0, "啊" * 200), (1.5, 2.0, "嗯"))
    blocks = proofread.merge_blocks(segs, max_chars=100)
    assert len(blocks) == 2


def test_merge_blocks_handles_empty():
    assert proofread.merge_blocks([]) == []


def test_merge_blocks_inserts_space_without_terminal_punctuation():
    segs = _segs((0.0, 1.0, "没有句号"), (1.5, 2.0, "下一句"))
    assert proofread.merge_blocks(segs)[0]["text"] == "没有句号 下一句"


# ---------------------------------------------------------------- ④ 切章节
def _blocks(n: int, width: int = 10):
    return [{"start": i * 10.0, "end": i * 10.0 + 5, "text": "字" * width} for i in range(n)]


def test_split_by_chars_covers_everything():
    items = _blocks(20)
    spans = outline.split_by_chars(items, 7)
    assert len(spans) == 7
    assert spans[0][0] == 1 and spans[-1][1] == 20
    assert all(b[0] == a[1] + 1 for a, b in zip(spans, spans[1:]))


def test_split_by_chars_balances_weight():
    items = [{"text": "字" * w} for w in (5, 5, 5, 5, 40)]
    spans = outline.split_by_chars(items, 2)
    # 大头在后，第一刀不能只切在 2 个字后面 —— 按字数均衡即可
    assert spans[0][1] >= 3


def test_tidy_sections_drops_illegal_spans():
    raw = [
        {"title": "甲", "from": 1, "to": 2},
        {"title": "越界", "from": 3, "to": 99},
        {"title": "倒序", "from": 5, "to": 2},
        {"title": "", "from": "x", "to": 2},
        {"title": "乙", "from": 3, "to": 4},
    ]
    assert outline.tidy_sections(raw, 4) == [
        {"title": "甲", "from": 1, "to": 2},
        {"title": "乙", "from": 3, "to": 4},
    ]


def test_covers_all():
    ok = [{"from": 1, "to": 2}, {"from": 3, "to": 5}]
    gap = [{"from": 1, "to": 2}, {"from": 4, "to": 5}]
    assert outline.covers_all(ok, 5)
    assert not outline.covers_all(gap, 5)
    assert not outline.covers_all([{"from": 1, "to": 4}], 5)  # 没到末段
    assert not outline.covers_all([], 5)


class _BadClient:
    """永远只覆盖前两段：逼出等分兜底。"""

    def ask(self, *_a, **_k):
        return '{"sections":[{"title":"甲","from":1,"to":2}]}'


def test_plan_falls_back_to_even_split():
    blocks = _blocks(40)
    sections = outline.plan(_BadClient(), blocks, {"title": "t", "chapters": []}, log=lambda *_: None)
    assert outline.covers_all(sections, len(blocks))
    assert len(sections) == outline.FALLBACK_SECTIONS


# ---------------------------------------------------------------- ⑦ 配图
def _cands():
    return [
        {"t": 10, "desc": "成本函数曲线与 C(w) 公式", "usable": True},
        {"t": 20, "desc": "成本函数曲线与 C(w) 公式", "usable": True},
        {"t": 30, "desc": "梯度下降的迭代步骤", "usable": True},
        {"t": 40, "desc": "终端安装命令界面", "usable": True},
    ]


def test_accept_items_enforces_monotonic_order():
    items = [
        {"para": 1, "t": 31},  # ±2 秒吸附到 30
        {"para": 1, "t": 10},  # 比上一个小 → 丢
        {"para": 2, "t": 40},
        {"para": 1, "t": 40},  # 段落倒退 → 丢
    ]
    got = layout.accept_items(items, 2, _cands())
    assert [(g["para"], g["t"]) for g in got] == [(1, 30), (2, 40)]


def test_accept_items_dedupes_by_second_and_content():
    items = [
        {"para": 1, "t": 10},
        {"para": 1, "t": 10},  # 同一秒
        {"para": 1, "t": 20},  # 描述一样
    ]
    assert [g["t"] for g in layout.accept_items(items, 2, _cands())] == [10]


def test_accept_items_rejects_out_of_range_para_and_far_seconds():
    items = [{"para": 0, "t": 10}, {"para": 3, "t": 30}, {"para": 1, "t": 99}]
    assert layout.accept_items(items, 2, _cands()) == []


def test_candidates_skip_logo_words_and_unusable():
    shots = [
        {"t": 5, "desc": "片头 logo", "usable": True},
        {"t": 8, "desc": "主讲人露脸", "usable": False},
        {"t": 12, "desc": "成本函数曲线", "usable": True},
        {"t": 50, "desc": "范围外", "usable": True},
    ]
    got = layout.candidates(shots, 0, 20)
    assert [g["t"] for g in got] == [12]


# ---------------------------------------------------------------- ⑥ 抽帧
def test_frame_times_trims_head_and_tail():
    assert frames.frame_times(20) == [2, 6, 10, 14]
    assert 2 not in frames.frame_times(4)


# ---------------------------------------------------------------- ⑤ 风格
def test_load_style_has_both_sections():
    style = bodies.load_style()
    assert "加粗" in style["body"]
    assert "全文整理" in style["spoken"] or "口语化" in style["spoken"]


# ---------------------------------------------------------------- ⑧ 拼装
def test_cn_num():
    assert [assemble.cn_num(n) for n in (1, 9, 10, 12, 20, 21, 60, 99)] == [
        "一",
        "九",
        "十",
        "十二",
        "二十",
        "二十一",
        "六十",
        "九十九",
    ]


def test_to_vault_links_uses_vault_relative_path():
    text = "![[images/f0010.jpg|成本函数曲线]]"
    assert (
        assemble.to_vault_links(text, "BV1REx46NEc4")
        == "![[media/videos/BV1REx46NEc4/f0010.jpg|成本函数曲线]]"
    )


def test_caption_line_is_italic_with_prefix():
    assert assemble.caption_line("界面截图") == "*图｜界面截图*"


def test_figures_reads_new_caption_format():
    md = "正文。\n\n![[images/f0010.jpg]]\n*图｜成本函数曲线*\n\n下一段。"
    out = assemble.figures(md)
    assert "<figcaption>成本函数曲线</figcaption>" in out
    assert "图｜" not in out          # 前缀只是给读者看的，渲染时去掉
    assert "![[" not in out


def test_figures_still_reads_legacy_format():
    """#88 之前导入的笔记长这样：``|说明`` 后面再跟一行同样的说明。"""
    md = "说明段。\n\n![[images/f0010.jpg|成本函数曲线]]\n成本函数曲线\n\n下一段。"
    out = assemble.figures(md)
    assert "<figcaption>成本函数曲线</figcaption>" in out
    assert "\n成本函数曲线" not in out
    assert "![[" not in out


def test_figures_handles_bare_embed():
    out = assemble.figures("正文。\n\n![[images/f0001.jpg]]\n")
    assert '<img src="images/f0001.jpg"' in out
    assert "<figcaption>" not in out


def test_render_html_has_no_obsidian_syntax():
    html = assemble.render_html(
        "---\ntitle: 示例\n---\n\n## 一、开头\n\n正文。\n\n![[images/f0004.jpg]]\n*图｜界面截图*\n"
    )
    assert "<title>示例</title>" in html
    assert "![[ " not in html and "![[" not in html
    assert '<img src="images/f0004.jpg"' in html


def _workspace(tmp_path: Path, *, sections, written, arranged):
    work = tmp_path / "BV1"
    (work / "frames").mkdir(parents=True)
    (work / "images").mkdir()
    for item in arranged[0]["items"]:
        (work / "frames" / f"f{item['t']:04d}.jpg").write_bytes(b"jpg")
    meta = {"id": "BV1", "title": "示例视频", "duration": 60, "uploader": "某 UP",
            "webpage_url": "https://example.invalid/BV1"}
    text, n_img = assemble.build_markdown(meta, sections, written, arranged, work)
    return work, meta, text, n_img


def test_build_markdown_places_image_after_its_paragraph(tmp_path):
    sections = [{"title": "开头", "from": 1, "to": 1}]
    written = ["第一段。\n\n第二段。"]
    arranged = [{"section": 1, "items": [{"para": 1, "t": 10, "desc": "界面截图"}]}]
    work, meta, text, n_img = _workspace(
        tmp_path, sections=sections, written=written, arranged=arranged
    )
    assert n_img == 1
    assert "## 一、开头" in text
    assert text.index("第一段。") < text.index("![[images/f0010.jpg]]")
    assert text.index("![[images/f0010.jpg") < text.index("第二段。")
    # 图注只写一次，且是斜体单独一行（#88）
    assert "*图｜界面截图*" in text
    assert text.count("界面截图") == 1
    assert (work / "images" / "f0010.jpg").exists()
    assert "saved:" in text and "video-notes" not in text


def test_build_markdown_full_section():
    tail = assemble.build_full(["### 一\n\n口语化一段。"])
    assert tail.strip().startswith("## 全文整理")
    assert "口语化一段。" in tail


@pytest.mark.parametrize("n", [1, 3, 8])
def test_group_size_covers_all_sections(n):
    size = bodies.group_size(n)
    assert size * (len(range(0, n, size))) >= n


# ---------------------------------------------------------------- 命名（#87）
import json  # noqa: E402

from hydrolitagent.literature.video_notes import __main__ as vn_cli  # noqa: E402
from hydrolitagent.literature.video_notes import naming  # noqa: E402


def test_sanitize_replaces_filesystem_illegal_chars():
    assert naming.sanitize('a/b\\c:d*e?f"g<h>i|j') == "a b c d e f g h i j"


def test_sanitize_removes_obsidian_link_chars():
    out = naming.sanitize("标题[1]#2^3")
    assert not any(ch in out for ch in "[]#^")


def test_sanitize_collapses_whitespace_and_trailing_dots():
    assert naming.sanitize("  多   空白..  ") == "多 空白"


def test_sanitize_truncates_long_titles():
    assert len(naming.sanitize("字" * 200)) == naming.MAX_TITLE


def test_sanitize_truncation_drops_trailing_punctuation():
    out = naming.sanitize("字" * 59 + "，尾巴")
    assert len(out) <= naming.MAX_TITLE
    assert not out.endswith(("，", "、", "。"))


def test_sanitize_all_illegal_becomes_empty():
    assert naming.sanitize("") == ""
    assert naming.sanitize("///") == ""


def test_folder_name_appends_bv():
    meta = {"id": "BV1xx", "title": "贝叶斯/定理"}
    assert naming.folder_name(meta) == "贝叶斯 定理（BV1xx）"


def test_folder_name_falls_back_to_bv():
    assert naming.folder_name({"id": "BV1xx", "title": "///"}) == "BV1xx"


def test_folder_name_requires_id():
    with pytest.raises(ValueError):
        naming.folder_name({"title": "x"})


def test_same_title_different_bv_stays_unique():
    a = naming.folder_name({"id": "BV1a", "title": "同名视频"})
    b = naming.folder_name({"id": "BV1b", "title": "同名视频"})
    assert a != b


def test_existing_work_finds_dir_by_bv(tmp_path, monkeypatch):
    root = tmp_path / "video-notes"
    old = root / "BV1old"
    old.mkdir(parents=True)
    (old / "meta.json").write_text(json.dumps({"id": "BV1"}), encoding="utf-8")
    (root / "没有meta的目录").mkdir()
    monkeypatch.setattr(vn_cli, "video_notes_root", lambda: root)

    assert vn_cli.existing_work("BV1") == old
    assert vn_cli.existing_work("BVmissing") is None


def test_to_vault_links_keeps_titled_album():
    text = "![[images/f0010.jpg|说明]]"
    assert (
        assemble.to_vault_links(text, "贝叶斯定理（BV1R7411a76r）")
        == "![[media/videos/贝叶斯定理（BV1R7411a76r）/f0010.jpg|说明]]"
    )


# ---------------------------------------------------------------- NO_PROXY 净化
from hydrolitagent.literature.video_notes.client import sanitize_no_proxy  # noqa: E402


def test_sanitize_no_proxy_drops_bracketed_ipv6():
    env = {
        "NO_PROXY": "localhost,127.0.0.1,::1,*.local,[::1]",
        "no_proxy": "localhost,127.0.0.1,::1,*.local,[::1]",
    }
    dropped = sanitize_no_proxy(env)
    assert dropped == ["[::1]", "[::1]"]
    assert env["NO_PROXY"] == "localhost,127.0.0.1,::1,*.local"
    assert env["no_proxy"] == "localhost,127.0.0.1,::1,*.local"


def test_sanitize_no_proxy_keeps_plain_ipv6():
    env = {"NO_PROXY": "localhost,::1"}
    assert sanitize_no_proxy(env) == []
    assert env["NO_PROXY"] == "localhost,::1"


def test_sanitize_no_proxy_handles_missing_and_empty():
    env: dict[str, str] = {}
    assert sanitize_no_proxy(env) == []
    env = {"NO_PROXY": ""}
    assert sanitize_no_proxy(env) == []


# ---------------------------------------------------------------- log.md 不重复
def test_append_log_skips_duplicate_note(tmp_path):
    entry = "- 视频笔记「甲乙」→ [[甲乙（BV1a）]]（3 图）"
    path, written = vn_cli.append_log(tmp_path, entry, key="甲乙（BV1a）")
    assert written is True
    path, written = vn_cli.append_log(tmp_path, entry, key="甲乙（BV1a）")
    assert written is False
    assert (tmp_path / "log.md").read_text(encoding="utf-8").count("[[甲乙（BV1a）]]") == 1


def test_append_log_records_different_notes(tmp_path):
    vn_cli.append_log(tmp_path, "- 甲 → [[甲（BV1a）]]", key="甲（BV1a）")
    vn_cli.append_log(tmp_path, "- 乙 → [[乙（BV1b）]]", key="乙（BV1b）")
    text = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "[[甲（BV1a）]]" in text and "[[乙（BV1b）]]" in text
