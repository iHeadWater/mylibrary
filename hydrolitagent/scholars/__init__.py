"""按人/机构检索论文并统计产出、作者位次与研究方向。

数据源以 OpenAlex 为主；中文清单/网页检索只作为候选，不自动计入。
"""

from __future__ import annotations

SCHEMA_VERSION = 1

__all__ = ["SCHEMA_VERSION"]
