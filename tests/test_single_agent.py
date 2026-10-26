"""Legacy v1 attribution contract and the shared nine-template invariants.

The provider-driven single-agent generation path was removed together with the
PDF-direct-read adapters (stage 6a). These tests keep the deterministic pieces
that are still imported by the legacy Claude adapter and by card saving.
"""
from __future__ import annotations

import hashlib
import json
import unittest

from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.card_generators.single_agent import validate_attribution

BODY = """# 原创研究证据卡：Test paper

## 声明—原文证据对应表

| 声明ID | 本卡可核声明 | 性质 | 忠实释义 | 位置 | 限定 | 证据状态 |
| --- | --- | --- | --- | --- | --- | --- |
| C01 | 结果甲 | 【原文陈述】结果 | 对象甲的结果甲 | PDF 第 2 页图 1 | 仅对象甲 | 原文有据 |
| C02 | 结果乙 | 【原文转述】 | 作者引用乙研究 | PDF 第 3 页 | 未读被引论文 | 转述未独立读取 |

## AI 推理

- 【AI 推理】：由 C01 可讨论对同类对象的可能适用性，但假设过程一致；不能推出其他气候区均适用。

## 信息边界

- 【信息边界】：原文未报告其他气候区的外部验证，现有证据不能支持普适性。
"""


def configure_template(f):
    path = f.templates / "01_original-research.md"
    front = path.read_text(encoding="utf-8").split("---", 2)[:2]
    content = "---" + front[1] + "---\n\n" + BODY.replace("Test paper", "{{TITLE}}")
    path.write_text(content, encoding="utf-8")
    catalog = json.loads(f.catalog.read_text(encoding="utf-8"))
    catalog["templates"][0]["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    f.catalog.write_text(json.dumps(catalog), encoding="utf-8")


class AttributionTests(unittest.TestCase):
    def test_attribution_contract_rejects_mixing_handoff_and_dangling_ids(self):
        self.assertEqual(validate_attribution(BODY)["claim_count"], 2)
        self.assertEqual(validate_attribution(BODY + "\n本卡不需要人工核验。\n")["claim_count"], 2)
        self.assertEqual(validate_attribution(BODY + "\n【原文陈述】作者的方法需要人工核验样本。\n")["claim_count"], 2)
        for body in (BODY.replace("【原文陈述】结果", "已证实"),
                     BODY.replace("C02 |", "C01 |"),
                     BODY + "\n依据 C99\n",
                     BODY.replace("【AI 推理】", "结论"),
                     BODY.replace("【信息边界】", "备注"),
                     BODY + "\n需要人工进一步核验\n",
                     BODY + "\n请导师复核\n",
                     BODY + "\n- 本人复查：已完成\n"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                validate_attribution(body)
        self.assertEqual(validate_attribution(BODY.replace("结果甲 | 【原文", "结果甲含 \\| 符号 | 【原文"))["claim_count"], 2)

    def test_source_marker_accepts_subtypes_without_changing_body(self):
        for marker in ("【原文陈述·方法】", "【原文陈述·结果及解释】", "【原文转述·案例证据】",
                       "**【原文陈述：局限】**", "【原文陈述】结果"):
            with self.subTest(marker=marker):
                body = BODY.replace("【原文陈述】结果", marker)
                self.assertEqual(validate_attribution(body)["claim_count"], 2)
        for marker in ("【AI 推理·方法】", "【原文陈述可能】", "【原文陈述", "【原文转述·】"):
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                validate_attribution(BODY.replace("【原文陈述】结果", marker))

    def test_ai_marker_whitespace_variants_and_explicit_annotations(self):
        for marker in ("【AI推理】", "【AI  推理】", "【AI\t推理】", "【AI　推理】",
                       "【 AI推理 】", "【AI推理；依据C01】", "【AI 推理·适用性】"):
            with self.subTest(marker=marker):
                body = BODY.replace("【AI 推理】", marker)
                self.assertEqual(validate_attribution(body)["claim_count"], 2)
        for heading in ("## AI推理", "##\tAI\t推理", "## AI　推理"):
            with self.subTest(heading=heading):
                body = BODY.replace("## AI 推理", heading).replace("【AI 推理】", "【AI推理】")
                self.assertEqual(validate_attribution(body)["claim_count"], 2)

    def test_missing_or_mislabeled_inference_is_still_rejected(self):
        for marker in ("【非AI推理】", "【AI推理可能】", "【原文陈述】", "AI推理"):
            with self.subTest(marker=marker), self.assertRaisesRegex(ValueError, "章节缺少明确的性质标记"):
                validate_attribution(BODY.replace("【AI 推理】", marker))
        # A marker in a different section must not satisfy the inference section.
        body = BODY.replace("【AI 推理】", "无标记") + "\n【AI推理】别处的文字。\n"
        with self.assertRaisesRegex(ValueError, "章节缺少明确的性质标记"):
            validate_attribution(body)
        with self.assertRaisesRegex(ValueError, "缺少独立的 AI 推理 章节"):
            validate_attribution(BODY.replace("## AI 推理", "## 其他内容"))


class TemplateInvariantTests(unittest.TestCase):
    def test_all_nine_adapted_templates_have_attribution_and_no_human_review_fields(self):
        root = ASSETS_DIR / "templates" / "evidence-cards"
        templates = list(root.glob("0*.md"))
        # 2.0.0:正文骨架改用王新宇 V1.7,并新增第 9 类 platform-decision-synthesis。
        # 2.0.1:九类模板正文各补一条数学公式与金额的 LaTeX 转写规则。
        # 「## AI 推理」「## 信息边界」两节必须保留——它们承载原文陈述/原文转述/
        # AI 推理三分与信息边界声明,对应王新宇侧的 statement_role 机器字段。
        self.assertEqual(len(templates), 9)
        for path in templates:
            body = path.read_text(encoding="utf-8")
            self.assertIn('template_version: "2.0.1"', body)
            self.assertIn("## AI 推理", body)
            self.assertIn("## 信息边界", body)
            self.assertNotIn("- 本人", body)
            self.assertNotIn("- 独立检查", body)
            self.assertNotIn("原文短摘录", body)


if __name__ == "__main__":
    unittest.main()
