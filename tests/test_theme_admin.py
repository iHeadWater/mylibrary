from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from hydrolitagent.cards import theme_admin
from hydrolitagent.cards import theme_pool as pool
from hydrolitagent.cards.cli import main
from hydrolitagent.cards.config import load_config
from hydrolitagent.cards.publication import text_hash
from hydrolitagent.cards.themes import ThemeError
from test_config import write_config


class ThemeAdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config_path = write_config(self.root)
        self.config = load_config(self.config_path)

    def _theme(self, theme_id: str, evidence: list[str], *, change: str | None = None) -> dict:
        change = change or "CHANGE-" + theme_id[-20:].lower().replace("-", "a")
        directory = self.config.paths.themes_dir / "candidates" / theme_id / "versions" / change
        directory.mkdir(parents=True)
        revised = f"# {theme_id}\n\n候选主题正文。\n"
        (directory / "revised.md").write_text(revised, encoding="utf-8")
        manifest = {
            "theme_id": theme_id,
            "readings": [{"source": {"evidence_id": item}} for item in evidence],
        }
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        reference = {
            "directory": f"candidates/{theme_id}/versions/{change}",
            "hashes": {"revised.md": text_hash(revised)},
            "readings": [],
        }
        return {
            "theme_id": theme_id,
            "title": theme_id,
            "status": pool.ACTIVE,
            "formal_confirmation": None,
            "predecessors": [],
            "successors": [],
            "current": reference,
            "history": [reference],
            "reason": "test",
        }

    def _orphan(self, theme_id: str, evidence: list[str]) -> Path:
        change = "CHANGE-" + theme_id[-20:].lower().replace("-", "b")
        directory = self.config.paths.themes_dir / "candidates" / theme_id / "versions" / change
        directory.mkdir(parents=True)
        (directory / "revised.md").write_text(f"# {theme_id}\n", encoding="utf-8")
        (directory / "manifest.json").write_text(json.dumps({
            "theme_id": theme_id,
            "readings": [{"source": {"evidence_id": item}} for item in evidence],
        }), encoding="utf-8")
        return directory

    def _write_registry(self, entries: list[dict]) -> Path:
        state = pool._empty(self.config)
        state["generation"] = 1
        state["themes"] = {entry["theme_id"]: entry for entry in entries}
        state["index_sha256"] = text_hash(pool.index_text(self.config, state))
        themes_dir = self.config.paths.themes_dir
        themes_dir.mkdir(parents=True, exist_ok=True)
        registry = themes_dir / "_registry.json"
        registry.write_text(json.dumps(pool._wrap(state), ensure_ascii=False), encoding="utf-8")
        (themes_dir / "index.md").write_text(pool.index_text(self.config, state), encoding="utf-8")
        return registry

    def test_audit_separates_registered_themes_from_orphans(self) -> None:
        self._write_registry([
            self._theme("TH-" + "1" * 24, ["EV-AAAA1111"]),
            self._theme("TH-" + "2" * 24, ["EV-BBBB2222"]),
        ])
        self._orphan("TH-" + "3" * 24, ["EV-AAAA1111"])

        report = theme_admin.audit(self.config)

        self.assertTrue(report["ok"])
        self.assertEqual(report["registered_count"], 2)
        self.assertEqual(report["orphan_root_count"], 1)
        self.assertEqual(report["duplicate_groups_registered"], [])
        self.assertEqual(report["orphan_roots"][0]["theme_id"], "TH-" + "3" * 24)

    def test_merge_retires_same_evidence_theme(self) -> None:
        canonical = "TH-" + "1" * 24
        duplicate = "TH-" + "2" * 24
        registry = self._write_registry([
            self._theme(canonical, ["EV-AAAA1111"]),
            self._theme(duplicate, ["EV-AAAA1111"]),
        ])

        report = theme_admin.merge(
            self.config, canonical=canonical, retire=[duplicate], reason="same evidence",
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "CANDIDATES_MERGED")
        state = pool.load(self.config)
        self.assertEqual(state["themes"][duplicate]["status"], pool.RETIRED)
        self.assertEqual(state["themes"][duplicate]["successors"], [canonical])
        self.assertIn("已合并或拆分的历史主题", (self.config.paths.themes_dir / "index.md").read_text(encoding="utf-8"))
        self.assertTrue(list((self.config.paths.themes_dir / "changes").glob("*/commit.json")))
        self.assertNotEqual(registry.read_bytes(), b"")

    def test_merge_rejects_evidence_mismatch_without_writing(self) -> None:
        canonical = "TH-" + "1" * 24
        other = "TH-" + "2" * 24
        registry = self._write_registry([
            self._theme(canonical, ["EV-AAAA1111"]),
            self._theme(other, ["EV-BBBB2222"]),
        ])
        before = registry.read_bytes()

        with self.assertRaises(ThemeError) as caught:
            theme_admin.merge(self.config, canonical=canonical, retire=[other], reason="mismatch")

        self.assertEqual(caught.exception.code, "THEME_MERGE_EVIDENCE_MISMATCH")
        self.assertEqual(registry.read_bytes(), before)

    def test_merge_is_idempotent(self) -> None:
        canonical = "TH-" + "1" * 24
        duplicate = "TH-" + "2" * 24
        self._write_registry([
            self._theme(canonical, ["EV-AAAA1111"]),
            self._theme(duplicate, ["EV-AAAA1111"]),
        ])
        theme_admin.merge(self.config, canonical=canonical, retire=[duplicate], reason="first")

        report = theme_admin.merge(self.config, canonical=canonical, retire=[duplicate], reason="again")

        self.assertEqual(report["status"], "NO_CHANGE_NEEDED")
        self.assertEqual(report["already_retired"], [duplicate])
        commits = list((self.config.paths.themes_dir / "changes").glob("*/commit.json"))
        self.assertEqual(len(commits), 1)

    def test_merge_rejects_self_and_unknown(self) -> None:
        canonical = "TH-" + "1" * 24
        self._write_registry([self._theme(canonical, ["EV-AAAA1111"])])

        with self.assertRaises(ThemeError) as self_merge:
            theme_admin.merge(self.config, canonical=canonical, retire=[canonical], reason="self")
        self.assertEqual(self_merge.exception.code, "THEME_MERGE_INVALID")

        with self.assertRaises(ThemeError) as unknown:
            theme_admin.merge(self.config, canonical=canonical, retire=["TH-" + "9" * 24], reason="missing")
        self.assertEqual(unknown.exception.code, "THEME_MERGE_UNKNOWN_THEME")

    def test_prune_dry_run_does_not_move_and_apply_archives(self) -> None:
        registered = "TH-" + "1" * 24
        orphan = "TH-" + "3" * 24
        self._write_registry([self._theme(registered, ["EV-AAAA1111"])])
        orphan_dir = self._orphan(orphan, ["EV-AAAA1111"])

        dry = theme_admin.prune(self.config, apply=False)
        self.assertEqual(dry["status"], "DRY_RUN")
        self.assertTrue(orphan_dir.exists())

        applied = theme_admin.prune(self.config, apply=True)
        self.assertEqual(applied["status"], "ORPHANS_ARCHIVED")
        self.assertFalse(orphan_dir.exists())
        archive = Path(applied["archive_path"])
        self.assertTrue((archive / orphan).is_dir())
        self.assertTrue((archive / "manifest.json").is_file())
        self.assertTrue((self.config.paths.themes_dir / "candidates" / registered).is_dir())

    def test_cli_audit_json(self) -> None:
        self._write_registry([self._theme("TH-" + "1" * 24, ["EV-AAAA1111"])])
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["themes-audit", "--config", str(self.config_path), "--json"])
        self.assertEqual(code, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["operation"], "themes_audit")
        self.assertEqual(report["registered_count"], 1)
