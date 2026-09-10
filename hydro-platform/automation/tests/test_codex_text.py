import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.card_generators.codex_text import CodexTextAdapter
from hydro_platform.config import CodexProxyConfig, load_config
from test_config import write_config
from test_card_generator import smoke_jsonl


class TextAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = replace(load_config(write_config(self.root)).card_generator,
            model="test-model", reasoning_effort="high")
        self.schema = self.root / "schema.json"
        self.schema.write_text('{"type":"object"}')
        self.prompt_runner = Mock(return_value=subprocess.CompletedProcess([], 0,
            smoke_jsonl(message=json.dumps({"revised_markdown": "自由格式正文"})), ""))
        def runner(command, timeout):
            return subprocess.CompletedProcess(command, 0, "codex-cli test" if "--version" in command else "Logged in using ChatGPT", "")
        self.adapter = CodexTextAdapter(self.config, runner=runner, prompt_runner=self.prompt_runner,
            executable_finder=lambda value: "codex")

    def run_adapter(self):
        return self.adapter.generate("输入材料", output_schema_path=self.schema, run_label="refinement", timeout_seconds=45)

    def test_isolated_no_tools_and_configuration(self):
        result = self.run_adapter()
        self.assertTrue(result["ok"], result)
        command, prompt, timeout, environment = self.prompt_runner.call_args.args
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("read-only", command)
        self.assertIn("test-model", command)
        self.assertIn('model_reasoning_effort="high"', command)
        self.assertEqual(timeout, 45)
        self.assertEqual(prompt, "输入材料")
        self.assertTrue(Path(result["draft_path"]).exists())
        self.assertFalse(Path(command[command.index("--cd") + 1]).exists())

    def test_tool_call_is_out_of_scope(self):
        self.prompt_runner.return_value.stdout = smoke_jsonl(message='{"revised_markdown":"text"}', extra_events=[
            {"type": "item.completed", "item": {"type": "command_execution"}}])
        result = self.run_adapter()
        self.assertFalse(result["ok"])
        self.assertTrue(Path(result["error"]["draft_path"]).exists())

    def test_theme_model_inherits_only_configured_child_proxy(self):
        self.adapter.config = replace(self.config, proxy=CodexProxyConfig(True, "http://127.0.0.1:17897"))
        self.assertTrue(self.run_adapter()["ok"])
        command, prompt, _, env = self.prompt_runner.call_args.args
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:17897")
        self.assertEqual(env["WSS_PROXY"], env["HTTPS_PROXY"])
        self.assertNotIn(env["HTTPS_PROXY"], prompt)
        self.assertNotIn(env["HTTPS_PROXY"], " ".join(command))

    def test_incomplete_turn_not_accepted(self):
        self.prompt_runner.return_value.stdout = json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": '{"revised_markdown":"text"}'}})
        self.assertFalse(self.run_adapter()["ok"])

    def test_bad_json_retained_not_silent_success(self):
        self.prompt_runner.return_value.stdout = smoke_jsonl(message="not-json")
        result = self.run_adapter()
        self.assertFalse(result["ok"])
        self.assertTrue(Path(result["error"]["draft_path"]).exists())

    def test_timeout_returns_bounded_failure(self):
        self.prompt_runner.side_effect = subprocess.TimeoutExpired("codex", 45)
        self.assertEqual(self.run_adapter()["error"]["code"], "CODEX_GENERATION_TIMEOUT")


if __name__ == "__main__":
    unittest.main()
