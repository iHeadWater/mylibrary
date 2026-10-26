"""Fixed protocol strings and allow-lists for the Codex CLI runner.

Moved out of ``card_generators/codex_cli.py`` in stage 1.6. Values are kept
byte-identical; tests and old on-disk records depend on the exact spelling.
"""
from __future__ import annotations

SMOKE_TEST_VERSION = "codex-cli-smoke-v1"
SMOKE_TEST_EXPECTED_TEXT = "HYDRO_GENERATOR_OK"
SMOKE_TEST_PROMPT = (
    "这是水利科研知识平台的运行环境连通性测试。"
    "不要调用任何工具，不要读取或修改任何文件，不要联网搜索。"
    f"只输出字符串 {SMOKE_TEST_EXPECTED_TEXT}，不要添加标点、代码块或解释。"
)
DISALLOWED_SMOKE_ITEM_TYPES = frozenset(
    {"command_execution", "file_change", "mcp_tool_call", "web_search"}
)
DISALLOWED_GENERATION_ITEM_TYPES = frozenset(
    {"command_execution", "file_change", "web_search"}
)
USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)

__all__ = [
    "DISALLOWED_GENERATION_ITEM_TYPES",
    "DISALLOWED_SMOKE_ITEM_TYPES",
    "SMOKE_TEST_EXPECTED_TEXT",
    "SMOKE_TEST_PROMPT",
    "SMOKE_TEST_VERSION",
    "USAGE_FIELDS",
]
