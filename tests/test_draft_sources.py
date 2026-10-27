"""Validated single-paper drafts as theme sources: accept, reject, merge."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hydrolitagent.cards import themes
from hydrolitagent.cards.application.draft_sources import (
    REJECT_REASONS,
    inspect_draft,
    scan_drafts,
)
from hydrolitagent.cards.card_validation import fingerprint
from hydrolitagent.cards.publication import text_hash
from test_card_generation import ATTACHMENT_KEY, FakeAdapter, GenerationFixture, PARENT_KEY
from test_config import write_config

GROUP_ID = 42
OTHER_KEY = "ITEM0002"
PDF_HASH = "a" * 64


def _config(root: Path, *, group_id: int | None = GROUP_ID):
    return SimpleNamespace(
        zotero=SimpleNamespace(group_id=group_id),
        paths=SimpleNamespace(evidence_packs_dir=root / "evidence-packs"),
    )


class DraftTree:
    """Builds draft directories with the same on-disk shape the pipeline writes."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def directory(self, key: str = PARENT_KEY, *, library=("user", 0), draft_id="a" * 16) -> Path:
        identity = f"{library[0]}-{library[1]}-{key}"
        path = self.root / "zotero" / identity / "drafts" / draft_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def draft(self, *, key: str = PARENT_KEY, library=("user", 0), draft_id="a" * 16,
              status: str = "DRAFT_PENDING_VALIDATION", pipeline: str = "markdown",
              card: str = "# 草稿正文\n\n洪水频率分析。") -> tuple[Path, dict]:
        directory = self.directory(key, library=library, draft_id=draft_id)
        draft = {
            "schema_version": 2,
            "draft_id": draft_id,
            "status": status,
            "created_at": "2026-10-27T00:00:00Z",
            "pipeline": pipeline,
            "source": {
                "library": {"type": library[0], "id": library[1]},
                "parent_key": key,
                "requested_item_key": key,
                "attachment_key": ATTACHMENT_KEY,
                "pdf_sha256": PDF_HASH,
                "pdf_size_bytes": 2048,
                "pdf_page_count": 3,
                "item": {"title": "Draft paper"},
            },
            "card_body_markdown": card,
            "provenance": {"converter_id": "pymupdf", "converter_version": "1.24.0"},
        }
        (directory / "draft.json").write_text(
            json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (directory / "card.md").write_text(card, encoding="utf-8")
        return directory, draft

    def validation(self, directory: Path, draft: dict, *, name: str = "v1",
                   status: str = "PASS", ok: bool = True, validated_at: str = "2026-10-27T00:00:01Z",
                   reading_verified: bool = True, eligible: bool = True,
                   draft_sha256: str | None = None, draft_id: str | None = None) -> Path:
        target = directory / "validations" / name
        target.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": 1,
            "validation_id": name,
            "validated_at": validated_at,
            "status": status,
            "ok": ok,
            "reading_verified": reading_verified,
            "eligible_for_theme_generation": eligible,
            "draft_id": draft_id if draft_id is not None else draft["draft_id"],
            "draft_sha256": draft_sha256 if draft_sha256 is not None else fingerprint(draft),
            "production_eligible": False,
            "scientific_correctness_verified": False,
        }
        (target / "validation.json").write_text(json.dumps(record), encoding="utf-8")
        return target


class DraftScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "literature"
        self.root.mkdir()
        self.tree = DraftTree(self.root)
        self.config = _config(self.root)

    def scan(self, *, group_id: int | None = GROUP_ID):
        return scan_drafts(_config(self.root, group_id=group_id), self.root)

    def test_validated_personal_draft_is_accepted_with_its_record_shape(self):
        directory, draft = self.tree.draft()
        self.tree.validation(directory, draft)

        result = self.scan()

        self.assertEqual(len(result.items), 1)
        source = result.items[0]
        self.assertEqual(source.evidence_id, "EV-" + PARENT_KEY)
        self.assertEqual(source.record, {
            "evidence_id": "EV-" + PARENT_KEY,
            "group_id": None,  # personal library
            "parent_key": PARENT_KEY,
            "attachment_key": ATTACHMENT_KEY,
            "pdf_sha256": PDF_HASH,
            "card_sha256": text_hash((directory / "card.md").read_text(encoding="utf-8")),
            "package_directory": directory.relative_to(self.root).as_posix(),
        })
        self.assertEqual(source.directory, directory.resolve())
        self.assertEqual(source.pdf_size_bytes, 2048)
        self.assertEqual(source.converter_id, "pymupdf")
        self.assertEqual(set(result.rejected), set(REJECT_REASONS))
        self.assertEqual(sum(result.rejected.values()), 0)

    def test_group_draft_must_match_the_configured_group(self):
        matched, draft = self.tree.draft(key="AAABBB11", library=("group", GROUP_ID), draft_id="b" * 16)
        self.tree.validation(matched, draft, name="v1")
        foreign, other = self.tree.draft(key="CCCDDD22", library=("group", 77), draft_id="c" * 16)
        self.tree.validation(foreign, other, name="v2")

        result = self.scan()

        self.assertEqual([item.evidence_id for item in result.items], ["EV-AAABBB11"])
        self.assertEqual(result.items[0].record["group_id"], GROUP_ID)
        self.assertEqual(result.rejected["foreign_group"], 1)

    def test_missing_validation_record_is_rejected_and_counted(self):
        self.tree.draft()

        result = self.scan()

        self.assertEqual(result.items, ())
        self.assertEqual(result.rejected["unvalidated"], 1)

    def test_failed_validation_is_rejected(self):
        directory, draft = self.tree.draft()
        self.tree.validation(directory, draft, status="FAIL", ok=False)

        self.assertEqual(inspect_draft(directory, literature_root=self.root,
                                       group_id=GROUP_ID)[1], "failed_validation")

    def test_pass_without_verified_reading_is_partial(self):
        directory, draft = self.tree.draft()
        self.tree.validation(directory, draft, reading_verified=False, eligible=False)

        self.assertEqual(inspect_draft(directory, literature_root=self.root,
                                       group_id=GROUP_ID)[1], "partial")

    def test_draft_changed_after_validation_is_stale(self):
        directory, draft = self.tree.draft()
        self.tree.validation(directory, draft)
        changed = json.loads((directory / "draft.json").read_text(encoding="utf-8"))
        changed["card_body_markdown"] += "\n手工改动。"
        (directory / "draft.json").write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")

        self.assertEqual(inspect_draft(directory, literature_root=self.root,
                                       group_id=GROUP_ID)[1], "stale")

    def test_card_without_draft_json_is_rejected(self):
        directory = self.tree.directory("AAABBB11")
        (directory / "card.md").write_text("# 只有卡片", encoding="utf-8")

        result = self.scan()

        self.assertEqual(result.items, ())
        self.assertEqual(result.rejected["unvalidated"], 1)

    def test_broken_draft_json_does_not_hide_other_sources(self):
        broken = self.tree.directory("AAABBB11")
        (broken / "card.md").write_text("# 坏草稿", encoding="utf-8")
        (broken / "draft.json").write_text("{not json", encoding="utf-8")
        good, draft = self.tree.draft(key="CCCDDD22", draft_id="c" * 16)
        self.tree.validation(good, draft, name="v1")

        result = self.scan()

        self.assertEqual([item.evidence_id for item in result.items], ["EV-CCCDDD22"])
        self.assertEqual(result.rejected["unreadable"], 1)

    def test_newest_validation_record_decides(self):
        directory, draft = self.tree.draft()
        self.tree.validation(directory, draft, name="pass", validated_at="2026-10-27T00:00:01Z")
        self.tree.validation(directory, draft, name="fail", status="FAIL", ok=False,
                             validated_at="2026-10-27T00:00:02Z")

        self.assertEqual(inspect_draft(directory, literature_root=self.root,
                                       group_id=GROUP_ID)[1], "failed_validation")


class SourceMergeTests(unittest.TestCase):
    """Packs and drafts are merged by evidence identity, packs first."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = GenerationFixture(self.root)
        self.fixture.generate(FakeAdapter())
        from hydrolitagent.cards.config import load_config

        self.config = load_config(write_config(self.root))
        self.literature = self.root / "literature"
        self.literature.mkdir()
        self.tree = DraftTree(self.literature)

    def collected(self):
        return themes._collect_sources(self.config, self.literature)

    def test_draft_only_run_reports_kinds_and_ids(self):
        (self.fixture.package / "manifest.json").unlink()  # no pack for this run
        directory, draft = self.tree.draft()
        self.tree.validation(directory, draft)

        sources, report = self.collected()

        self.assertEqual(list(sources), ["EV-" + PARENT_KEY])
        self.assertEqual(sources["EV-" + PARENT_KEY]["kind"], "draft")
        self.assertEqual(report["sources_by_kind"], {"evidence_pack": 0, "draft": 1})
        self.assertEqual(report["source_ids"], ["EV-" + PARENT_KEY])
        self.assertEqual(report["duplicate_sources"], [])
        self.assertEqual(sum(report["rejected_drafts"].values()), 0)

    def test_pack_wins_when_both_describe_the_same_paper(self):
        # The fixture's pack uses PARENT_KEY; the draft repeats the identity.
        directory, draft = self.tree.draft()
        self.tree.validation(directory, draft)

        sources, report = self.collected()

        self.assertEqual(list(sources), ["EV-" + PARENT_KEY])
        self.assertEqual(sources["EV-" + PARENT_KEY]["kind"], "evidence_pack")
        self.assertEqual(report["sources_by_kind"], {"evidence_pack": 1, "draft": 0})
        self.assertEqual(report["duplicate_sources"],
                         [{"evidence_id": "EV-" + PARENT_KEY,
                           "code": "DUPLICATE_SOURCE_PREFERRED_PACK"}])

    def test_pack_keeps_the_identity_when_two_drafts_repeat_it(self):
        first, draft = self.tree.draft(draft_id="a" * 16)
        self.tree.validation(first, draft, name="v1")
        second, other = self.tree.draft(library=("group", GROUP_ID), draft_id="b" * 16)
        self.tree.validation(second, other, name="v2")

        sources, report = self.collected()

        self.assertEqual(list(sources), ["EV-" + PARENT_KEY])
        self.assertEqual(sources["EV-" + PARENT_KEY]["kind"], "evidence_pack")
        self.assertEqual(report["duplicate_sources"],
                         [{"evidence_id": "EV-" + PARENT_KEY,
                           "code": "DUPLICATE_SOURCE_PREFERRED_PACK"}])

    def test_two_drafts_for_one_paper_are_ambiguous(self):
        first, draft = self.tree.draft(draft_id="a" * 16)
        self.tree.validation(first, draft, name="v1")
        second, other = self.tree.draft(library=("group", GROUP_ID), draft_id="b" * 16)
        self.tree.validation(second, other, name="v2")
        # Remove the fixture pack so the duplicate is between drafts only.
        (self.fixture.package / "manifest.json").unlink()

        with self.assertRaises(themes.ThemeError) as error:
            self.collected()
        self.assertEqual(error.exception.code, "THEME_DUPLICATE_SOURCE")


if __name__ == "__main__":
    unittest.main()
