from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE_ROOT))

from hydro_platform.cli import main
from hydro_platform.evidence_templates import (
    EvidenceTemplateError,
    validate_evidence_templates,
)


SOURCE_COMMIT = "1" * 40
SOURCE_BLOB = "2" * 40


def template_content(
    *,
    template_id: str = "original-research",
    local_version: str = "1.0.0",
    source_commit: str = SOURCE_COMMIT,
) -> str:
    return f'''---
template_id: "{template_id}"
template_version: "{local_version}"
template_source_commit: "{source_commit}"
evidence_id: "{{{{EVIDENCE_ID}}}}"
card_state: "{{{{CARD_STATE}}}}"
title: "{{{{TITLE}}}}"
zotero_group_id: "{{{{ZOTERO_GROUP_ID}}}}"
zotero_parent_key: "{{{{ZOTERO_PARENT_KEY}}}}"
zotero_attachment_key: "{{{{ZOTERO_ATTACHMENT_KEY}}}}"
source_pdf_sha256: "{{{{PDF_SHA256}}}}"
classification_confidence: "{{{{CLASSIFICATION_CONFIDENCE}}}}"
classification_reason: "{{{{CLASSIFICATION_REASON}}}}"
reading_scope: "{{{{READING_SCOPE}}}}"
generated_at: "{{{{GENERATED_AT}}}}"
updated_at: "{{{{GENERATED_AT}}}}"
---

# 测试模板：{{{{TITLE}}}}
'''


def write_fixture(
    root: Path,
    *,
    template_id: str = "original-research",
    enabled: bool = True,
) -> tuple[Path, Path]:
    templates_dir = root / "templates" / "evidence-cards"
    templates_dir.mkdir(parents=True)
    template_file = templates_dir / "01_original-research.md"
    content = template_content(template_id=template_id)
    template_file.write_text(content, encoding="utf-8")
    content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    catalog = {
        "schema_version": 1,
        "catalog_version": "1.0.0",
        "source": {
            "repository": "https://example.test/source",
            "commit": SOURCE_COMMIT,
            "license_status": "permission_required",
            "authorization_basis": "test_fixture",
        },
        "required_template_ids": [template_id],
        "templates": [
            {
                "template_id": template_id,
                "local_version": "1.0.0",
                "enabled": enabled,
                "file": template_file.name,
                "source_path": "templates/01_original-research.md",
                "source_blob_sha": SOURCE_BLOB,
                "content_sha256": content_sha256,
            }
        ],
    }
    catalog_file = templates_dir / "_catalog.json"
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    return templates_dir, catalog_file


class EvidenceTemplateValidationTests(unittest.TestCase):
    def test_real_catalog_validates_all_nine_templates(self) -> None:
        templates_dir = PROJECT_ROOT / "templates" / "evidence-cards"

        result = validate_evidence_templates(
            templates_dir,
            templates_dir / "_catalog.json",
        )

        self.assertTrue(result["ok"])
        # 2.0.0:与王新宇分支合并后,模板正文改用其 V1.7 版本,
        # 并新增第 9 类 platform-decision-synthesis(原 1.1.0 为八类)。
        self.assertEqual(result["template_count"], 9)
        self.assertEqual(result["enabled_count"], 9)
        self.assertEqual(result["catalog_version"], "2.0.0")
        self.assertEqual(
            result["source_commit"],
            "7b0f2b7e209aa566f3c68db817d5c4a71d9f8b19",
        )

    def test_accepts_valid_single_template_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            templates_dir, catalog_file = write_fixture(Path(directory))

            result = validate_evidence_templates(templates_dir, catalog_file)

            self.assertEqual(result["template_count"], 1)
            self.assertEqual(
                result["templates"][0]["template_id"], "original-research"
            )
            self.assertIn("CLASSIFICATION_REASON", result["templates"][0]["placeholders"])

    def test_rejects_duplicate_template_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            templates_dir, catalog_file = write_fixture(Path(directory))
            catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
            duplicate = {**catalog["templates"][0], "file": "02_duplicate.md"}
            (templates_dir / duplicate["file"]).write_text(
                template_content(), encoding="utf-8"
            )
            duplicate["content_sha256"] = hashlib.sha256(
                (templates_dir / duplicate["file"]).read_text(encoding="utf-8").encode(
                    "utf-8"
                )
            ).hexdigest()
            catalog["templates"].append(duplicate)
            catalog_file.write_text(json.dumps(catalog), encoding="utf-8")

            with self.assertRaisesRegex(EvidenceTemplateError, "模板 ID 重复") as caught:
                validate_evidence_templates(templates_dir, catalog_file)

            self.assertEqual(caught.exception.code, "EVIDENCE_TEMPLATE_DUPLICATE")

    def test_rejects_missing_template_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            templates_dir, catalog_file = write_fixture(Path(directory))
            catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
            catalog["templates"][0]["file"] = "missing.md"
            catalog_file.write_text(json.dumps(catalog), encoding="utf-8")

            with self.assertRaises(EvidenceTemplateError) as caught:
                validate_evidence_templates(templates_dir, catalog_file)

            self.assertEqual(caught.exception.code, "EVIDENCE_TEMPLATE_NOT_FOUND")

    def test_rejects_required_template_missing_from_catalog_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            templates_dir, catalog_file = write_fixture(Path(directory))
            catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
            catalog["required_template_ids"].append("review-synthesis")
            catalog_file.write_text(json.dumps(catalog), encoding="utf-8")

            with self.assertRaisesRegex(EvidenceTemplateError, "缺少：review-synthesis"):
                validate_evidence_templates(templates_dir, catalog_file)

    def test_rejects_template_path_outside_configured_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            templates_dir, catalog_file = write_fixture(root)
            outside_file = templates_dir.parent / "outside.md"
            outside_file.write_text(template_content(), encoding="utf-8")
            catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
            catalog["templates"][0]["file"] = "../outside.md"
            catalog_file.write_text(json.dumps(catalog), encoding="utf-8")

            with self.assertRaises(EvidenceTemplateError) as caught:
                validate_evidence_templates(templates_dir, catalog_file)

            self.assertEqual(caught.exception.code, "EVIDENCE_TEMPLATE_PATH_INVALID")

    def test_rejects_content_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            templates_dir, catalog_file = write_fixture(Path(directory))
            template_file = templates_dir / "01_original-research.md"
            template_file.write_text(
                template_file.read_text(encoding="utf-8") + "\n已修改\n",
                encoding="utf-8",
            )

            with self.assertRaises(EvidenceTemplateError) as caught:
                validate_evidence_templates(templates_dir, catalog_file)

            self.assertEqual(caught.exception.code, "EVIDENCE_TEMPLATE_HASH_MISMATCH")

    def test_rejects_front_matter_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            templates_dir, catalog_file = write_fixture(Path(directory))
            template_file = templates_dir / "01_original-research.md"
            content = template_content(local_version="2.0.0")
            template_file.write_text(content, encoding="utf-8")
            catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
            catalog["templates"][0]["content_sha256"] = hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()
            catalog_file.write_text(json.dumps(catalog), encoding="utf-8")

            with self.assertRaisesRegex(EvidenceTemplateError, "template_version"):
                validate_evidence_templates(templates_dir, catalog_file)

    def test_rejects_missing_required_machine_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            templates_dir, catalog_file = write_fixture(Path(directory))
            template_file = templates_dir / "01_original-research.md"
            content = template_file.read_text(encoding="utf-8").replace(
                'classification_reason: "{{CLASSIFICATION_REASON}}"\n', ""
            )
            template_file.write_text(content, encoding="utf-8")
            catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
            catalog["templates"][0]["content_sha256"] = hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()
            catalog_file.write_text(json.dumps(catalog), encoding="utf-8")

            with self.assertRaisesRegex(EvidenceTemplateError, "classification_reason"):
                validate_evidence_templates(templates_dir, catalog_file)

    def test_requires_at_least_one_enabled_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            templates_dir, catalog_file = write_fixture(Path(directory), enabled=False)

            with self.assertRaisesRegex(EvidenceTemplateError, "至少需要启用"):
                validate_evidence_templates(templates_dir, catalog_file)


class EvidenceTemplateCliTests(unittest.TestCase):
    def test_validation_command_uses_configured_paths(self) -> None:
        expected = {
            "schema_version": 1,
            "ok": True,
            "component": "evidence_templates",
            "catalog_version": "1.0.0",
            "source_commit": SOURCE_COMMIT,
            "template_count": 8,
            "enabled_count": 8,
            "templates_dir": "configured-templates",
        }
        app_config = SimpleNamespace(
            paths=SimpleNamespace(
                evidence_card_templates_dir=Path("configured-templates"),
                evidence_card_template_catalog_file=Path("configured-catalog.json"),
            )
        )
        output = io.StringIO()

        with (
            patch("hydro_platform.cli.load_config", return_value=app_config),
            patch(
                "hydro_platform.cli.validate_evidence_templates",
                return_value=expected,
            ) as validate,
            redirect_stdout(output),
        ):
            exit_code = main(
                ["evidence-templates-validate", "--config", "unused.json", "--json"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue()), expected)
        validate.assert_called_once_with(
            app_config.paths.evidence_card_templates_dir,
            app_config.paths.evidence_card_template_catalog_file,
        )


if __name__ == "__main__":
    unittest.main()
