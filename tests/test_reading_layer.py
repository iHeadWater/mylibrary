"""Tests for the generated reading layer over the product root.

The machine trees are hash-chained, so these tests build a throwaway product
root and assert three things that matter to a reader:

* the current draft is chosen by rule, not by directory name;
* every relative link the generator writes resolves to a real file;
* a second run changes nothing (idempotent), and a missing figure cache warns
  instead of crashing.

Nothing here touches Zotero, a model, or the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydrolitagent.cards import theme_pool as pool
from hydrolitagent.cards import theme_pool_runner as runner
from hydrolitagent.cards.application.reading_layer import build_reading_layer
from hydrolitagent.cards.publication import text_hash

SHA_A = "a" * 64
SHA_B = "b" * 64


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _draft(*, draft_id: str, parent_key: str, title: str, date: str, doi: str,
           attachment: str, sha: str, body: str, created_at: str,
           converter: tuple[str, str] = ("pymupdf", "1.0")) -> dict:
    return {
        "schema_version": 2,
        "draft_id": draft_id,
        "status": "DRAFT_PENDING_VALIDATION",
        "created_at": created_at,
        "pipeline": "markdown",
        "content_validation_performed": True,
        "production_eligible": False,
        "scientific_correctness_verified": False,
        "source": {
            "library": {"type": "user", "id": 0},
            "parent_key": parent_key,
            "requested_item_key": parent_key,
            "attachment_key": attachment,
            "pdf_sha256": sha,
            "pdf_size_bytes": 1000,
            "pdf_page_count": 3,
            "item": {
                "item_key": parent_key,
                "item_type": "journalArticle",
                "title": title,
                "creators": "作者 等",
                "date": date,
                "doi": doi,
                "url": None,
                "child_count": 1,
            },
        },
        "card_body_markdown": body,
        "reading_record": {"converter_id": converter[0], "converter_version": converter[1]},
    }


def _validation(*, status: str, validated_at: str, reading_verified: bool | None) -> dict:
    return {
        "schema_version": 1,
        "status": status,
        "validated_at": validated_at,
        "reading_verified": reading_verified,
        "production_eligible": False,
        "scientific_correctness_verified": False,
    }


def _add_draft(root: Path, library: str, draft: dict, *validations: dict) -> None:
    draft_dir = root / "zotero" / library / "drafts" / draft["draft_id"]
    _write_json(draft_dir / "draft.json", draft)
    (draft_dir / "card.md").write_text(
        "> 待校验主体卡草稿；未通过内容门禁，不是正式发布的卡片。\n\n" + draft["card_body_markdown"],
        encoding="utf-8",
    )
    for index, validation in enumerate(validations):
        _write_json(draft_dir / "validations" / f"v{index}" / "validation.json", validation)


def _fixture(root: Path) -> None:
    _add_draft(
        root,
        "user-0-AAAA1111",
        _draft(
            draft_id="draft-pass", parent_key="AAAA1111", title="论文 A",
            date="2020", doi="10.1/a", attachment="ATTACH01", sha=SHA_A,
            body="# 卡 A\n\n正文 A", created_at="2026-01-02T00:00:00Z",
        ),
        _validation(status="PASS", validated_at="2026-01-03T00:00:00+00:00", reading_verified=True),
    )
    _add_draft(
        root,
        "user-0-AAAA1111",
        _draft(
            draft_id="draft-pass-old", parent_key="AAAA1111", title="论文 A",
            date="2020", doi="10.1/a", attachment="ATTACH01", sha=SHA_A,
            body="# 卡 A 旧版\n\n旧正文", created_at="2026-01-01T00:00:00Z",
        ),
        _validation(status="PASS", validated_at="2026-01-01T00:00:00+00:00", reading_verified=True),
    )
    # Newer than the chosen draft, but its latest validation failed: PASS wins.
    _add_draft(
        root,
        "user-0-AAAA1111",
        _draft(
            draft_id="draft-fail", parent_key="AAAA1111", title="论文 A",
            date="2020", doi="10.1/a", attachment="ATTACH01", sha=SHA_A,
            body="# 卡 A 失败版\n\n失败正文", created_at="2026-01-04T00:00:00Z",
        ),
        _validation(status="FAIL", validated_at="2026-01-05T00:00:00+00:00", reading_verified=True),
    )
    _add_draft(
        root,
        "user-0-BBBB2222",
        _draft(
            draft_id="draft-unvalidated", parent_key="BBBB2222", title="论文 B | 副题",
            date="2019-05-01", doi="", attachment="ATTACH02", sha=SHA_B,
            body="# 卡 B\n\n正文 B", created_at="2026-01-03T00:00:00Z",
        ),
    )

    figures = root.parent / ".runtime" / "papers" / SHA_A / "pymupdf-1.0" / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    (figures / "page-001-fig-1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    reading_dir = root / "evidence-packs" / "draft-readings" / "EV-AAAA1111" / "readings" / "RD-1"
    reading_dir.mkdir(parents=True, exist_ok=True)
    (reading_dir / "reading.md").write_text("# 定向精读 A\n\n引文。", encoding="utf-8")
    _write_json(reading_dir / "result.json", {"record": {}, "sha256": "0" * 64})

    version = root / "themes" / "candidates" / "TH-TEST" / "versions" / "CHANGE-1"
    version.mkdir(parents=True, exist_ok=True)
    (version / "revised.md").write_text(
        "<!-- CANDIDATE_REFINED; NOT CONFIRMED -->\n"
        "# 候选主题：测试主题\n\n正文主题。\n\n---\n"
        "程序维护的来源引用（不代表独立科学核验）：\n\n"
        "- [EV-AAAA1111 粗卡](<../../../../../outputs/zotero/user-0-AAAA1111/drafts/draft-pass/card.md>)\n",
        encoding="utf-8",
    )
    _write_json(
        root / "themes" / "_registry.json",
        {
            "record": {
                "themes": {
                    "TH-TEST": {
                        "theme_id": "TH-TEST",
                        "title": "测试主题",
                        "status": "CANDIDATE_REFINED",
                        "current": {
                            "directory": "candidates/TH-TEST/versions/CHANGE-1",
                            "readings": [
                                {
                                    "reading_id": "RD-1",
                                    "root": "evidence_packs",
                                    "directory": "draft-readings/EV-AAAA1111/readings/RD-1",
                                    "source": {
                                        "evidence_id": "EV-AAAA1111",
                                        "parent_key": "AAAA1111",
                                    },
                                }
                            ],
                        },
                    }
                }
            },
            "sha256": "0" * 64,
        },
    )
    (root / "themes" / "index.md").write_text("# 统一主题池\n", encoding="utf-8")


@pytest.fixture()
def product_root(tmp_path: Path) -> Path:
    root = tmp_path / "outputs"
    root.mkdir()
    _fixture(root)
    return root


def test_selects_pass_verified_draft_and_writes_reading_edition(product_root: Path) -> None:
    report = build_reading_layer(product_root, runtime_dir=product_root.parent / ".runtime")

    assert report["ok"], report
    assert report["card_count"] == 2
    assert report["theme_count"] == 1
    assert report["broken_links"] == []
    assert report["links_checked"] > 0

    card = (product_root / "cards" / "AAAA1111" / "card.md").read_text(encoding="utf-8")
    assert 'title: "论文 A"' in card
    assert 'zotero_key: "AAAA1111"' in card
    assert "year: 2020" in card
    assert 'status: "PASS"' in card
    assert "reading_verified: true" in card
    assert "当前草稿：`draft-pass`" in card
    assert "正文 A" in card
    assert "旧正文" not in card
    assert "失败正文" not in card

    unvalidated = (product_root / "cards" / "BBBB2222" / "card.md").read_text(encoding="utf-8")
    assert 'status: "未校验"' in unvalidated
    assert "reading_verified: null" in unvalidated

    index = (product_root / "cards" / "INDEX.md").read_text(encoding="utf-8")
    assert "`draft-pass`" in index
    assert "最新校验 PASS" in index
    assert "`draft-fail`" not in index


def test_copies_figures_and_embeds_them(product_root: Path) -> None:
    report = build_reading_layer(product_root, runtime_dir=product_root.parent / ".runtime")

    copied = product_root / "cards" / "AAAA1111" / "figures" / "page-001-fig-1.png"
    assert copied.is_file()
    assert "cards/AAAA1111/figures/page-001-fig-1.png" in report["written"]
    card = (product_root / "cards" / "AAAA1111" / "card.md").read_text(encoding="utf-8")
    assert "](<figures/page-001-fig-1.png>)" in card


def test_missing_figure_cache_warns_without_crashing(product_root: Path) -> None:
    report = build_reading_layer(product_root, runtime_dir=product_root.parent / "absent")

    assert report["ok"], report
    assert "FIGURE_CACHE_MISSING:AAAA1111" in report["warnings"]
    assert "FIGURE_CACHE_MISSING:BBBB2222" in report["warnings"]
    card = (product_root / "cards" / "AAAA1111" / "card.md").read_text(encoding="utf-8")
    assert "FIGURE_CACHE_MISSING:AAAA1111" in card
    assert "](<figures/" not in card


def test_theme_reading_page_recomputes_links(product_root: Path) -> None:
    build_reading_layer(product_root, runtime_dir=product_root.parent / ".runtime")

    page = (product_root / "reading" / "themes" / "TH-TEST.md").read_text(encoding="utf-8")
    assert "本页由" in page
    assert "正文主题。" in page
    usages = [
        "../../cards/AAAA1111/card.md",
        "../../evidence-packs/draft-readings/EV-AAAA1111/readings/RD-1/reading.md",
    ]
    for target in usages:
        assert target in page
        assert (product_root / "reading" / "themes" / target).is_file()
    # The historical machine link is not copied into the generated page.
    assert "../../../../../outputs/zotero" not in page


def test_home_links_cards_themes_and_index(product_root: Path) -> None:
    build_reading_layer(product_root, runtime_dir=product_root.parent / ".runtime")

    home = (product_root / "HOME.md").read_text(encoding="utf-8")
    assert "cards/AAAA1111/card.md" in home
    assert "cards/BBBB2222/card.md" in home
    assert "cards/INDEX.md" in home
    assert "themes/index.md" in home
    assert "reading/themes/TH-TEST.md" in home


_MACHINE_PREFIXES = ("zotero/", "themes/", "evidence-packs/")


def _read_tree(root: Path, *, machine: bool) -> dict[str, bytes]:
    tree: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(_MACHINE_PREFIXES) != machine:
            continue
        tree[relative] = path.read_bytes()
    return tree


def test_second_run_is_byte_identical(product_root: Path) -> None:
    runtime = product_root.parent / ".runtime"
    first = build_reading_layer(product_root, runtime_dir=runtime)
    snapshot = _read_tree(product_root, machine=False)

    second = build_reading_layer(product_root, runtime_dir=runtime)

    assert second["ok"], second
    assert second["written"] == []
    assert second["unchanged"]
    assert _read_tree(product_root, machine=False) == snapshot
    assert first["links_checked"] == second["links_checked"]


def test_machine_trees_are_not_modified(product_root: Path) -> None:
    before = _read_tree(product_root, machine=True)
    build_reading_layer(product_root, runtime_dir=product_root.parent / ".runtime")
    assert _read_tree(product_root, machine=True) == before


def test_broken_link_fails_the_report(product_root: Path) -> None:
    draft_path = (product_root / "zotero" / "user-0-AAAA1111" / "drafts"
                  / "draft-pass" / "draft.json")
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    draft["card_body_markdown"] += "\n\n[缺失图](missing.png)\n"
    _write_json(draft_path, draft)

    report = build_reading_layer(product_root, runtime_dir=product_root.parent / ".runtime")

    assert report["ok"] is False
    assert {
        "file": "cards/AAAA1111/card.md",
        "target": "missing.png",
    } in report["broken_links"]


# --------------------------------------------------------------------------------------
# R6: escaped newlines on the reading write path
# --------------------------------------------------------------------------------------


def test_normalize_reading_markdown_rewrites_doubled_escapes_only() -> None:
    assert pool.normalize_reading_markdown("a\\\\nb") == "a\nb"
    assert pool.normalize_reading_markdown("a\\\\r\\\\nb") == "a\nb"
    # LaTeX and single-backslash escapes are left exactly as written.
    assert pool.normalize_reading_markdown(r"\nabla") == r"\nabla"
    assert pool.normalize_reading_markdown(r"a\nb") == r"a\nb"


def test_reading_reference_writes_real_newlines(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence-packs"
    directory = evidence / "draft-readings" / "EV-AAAA1111" / "readings" / "RD-1"
    directory.mkdir(parents=True)
    (directory / "result.json").write_text("{}\n", encoding="utf-8")
    source = {"parent_key": "AAAA1111", "pdf_sha256": SHA_A}
    record = {
        "output": {"reading_markdown": "# 精读\\\\n\\\\n第一段。\\\\n第二段。"},
        "execution": {
            "source_access": {
                "method": "markdown_prepared",
                "source_pdf_sha256": SHA_A,
                "markdown_sha256": SHA_A,
                "parent_key": "AAAA1111",
                "page_count": 3,
                "converter_id": "converter",
                "converter_version": "1",
                "reading": {
                    "verified": True,
                    "canaries_ok": True,
                    "scientific_correctness_verified": False,
                },
            }
        },
        "binding": {"source": source},
    }
    config = SimpleNamespace(paths=SimpleNamespace(evidence_packs_dir=evidence))

    ref = pool.reading_reference(config, directory, record, source, "focus", "context")

    text = (directory / "reading.md").read_text(encoding="utf-8")
    assert "\\\\n" not in text
    assert "# 精读\n\n第一段。\n第二段。" in text
    assert ref["hashes"]["reading.md"] == text_hash(text)


# --------------------------------------------------------------------------------------
# R4: theme links must stay resolvable after themes/ moved under outputs/
# --------------------------------------------------------------------------------------


def test_theme_links_resolve_after_move(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    card = root / "zotero" / "user-0-AAAA1111" / "drafts" / "draft-pass" / "card.md"
    card.parent.mkdir(parents=True)
    card.write_text("# 卡 A\n", encoding="utf-8")
    reading = (root / "evidence-packs" / "draft-readings" / "EV-AAAA1111"
               / "readings" / "RD-1" / "reading.md")
    reading.parent.mkdir(parents=True)
    reading.write_text("# 精读\n", encoding="utf-8")
    directory = root / "themes" / "candidates" / "TH-TEST" / "versions" / "CHANGE-1"
    directory.mkdir(parents=True)
    config = SimpleNamespace(paths=SimpleNamespace(evidence_packs_dir=root / "evidence-packs"))
    ref = {
        "root": "evidence_packs",
        "directory": "draft-readings/EV-AAAA1111/readings/RD-1",
        "source": {
            "evidence_id": "EV-AAAA1111",
            "package_directory": "zotero/user-0-AAAA1111/drafts/draft-pass",
        },
    }

    text = runner._links(config, [ref], directory, root)

    assert "../../../../../zotero/user-0-AAAA1111/drafts/draft-pass/card.md" in text
    assert "../../../../../evidence-packs/draft-readings/EV-AAAA1111/readings/RD-1/reading.md" in text
    for target in ("../../../../../zotero/user-0-AAAA1111/drafts/draft-pass/card.md",
                   "../../../../../evidence-packs/draft-readings/EV-AAAA1111/readings/RD-1/reading.md"):
        assert (directory / target).is_file(), target
