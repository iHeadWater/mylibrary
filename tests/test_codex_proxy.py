"""Offline proxy wiring/isolation tests. Never connect to a proxy or model service."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from hydrolitagent.cards._paths import ASSETS_DIR
from hydrolitagent.cards.card_generators.codex_cli import CodexCliAdapter, _run_command, _run_prompt_command
from hydrolitagent.cards.card_generators.proxy import (
    LOCAL_BYPASS, PROXY_VARIABLES, codex_proxy_environment, proxy_summary,
)
from hydrolitagent.cards.card_generators.streaming import run_streaming_prompt
from hydrolitagent.cards.config import CodexProxyConfig, ConfigError, load_config
from test_card_generator import generator_config, smoke_jsonl
from test_codex_local_pdf import LocalProviderFixture
from test_config import write_config

PROXY = CodexProxyConfig(True, "http://127.0.0.1:17897", ("intranet.example",))

class ProxyConfigTests(unittest.TestCase):
    def load_proxy(self, value):
        with tempfile.TemporaryDirectory() as directory:
            path = write_config(Path(directory), {"card_generator": {"proxy": value}})
            return load_config(path).card_generator.proxy

    def test_old_configuration_and_explicit_disabled_keep_inheritance(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(write_config(Path(directory))).card_generator
        self.assertEqual(config.proxy, CodexProxyConfig())
        self.assertEqual(self.load_proxy({}), CodexProxyConfig())
        self.assertEqual(self.load_proxy({"enabled": False, "url": None}), CodexProxyConfig())

    def test_valid_urls_and_custom_bypass(self):
        for url in ("http://127.0.0.1:7897", "http://[::1]:7897", "https://proxy.example:8443/"):
            with self.subTest(url=url):
                config = self.load_proxy({"enabled": True, "url": url, "no_proxy": [".internal.example"]})
                self.assertEqual(config.url, url)
                self.assertEqual(config.no_proxy, (".internal.example",))

    def test_invalid_config_rejected_without_echoing_secrets(self):
        invalid = [None, [], {"enabled": "true"}, {"enabled": True}, {"extra": 1},
            {"no_proxy": "localhost"}, {"no_proxy": ["*"]}, {"no_proxy": ["localhost,127.0.0.1"]},
            {"no_proxy": ["http://localhost"]}, {"no_proxy": [None]}]
        for url in ("", True, "127.0.0.1:7897", "http://localhost", "socks5://localhost:7897",
                    "http://localhost:0", "http://localhost:65536", "http://localhost:notaport",
                    "http://localhost:7897/a", "http://localhost:7897?token=PRIVATE_SECRET",
                    "http://name:PRIVATE_SECRET@localhost:7897", "http://localhost:7897#PRIVATE_SECRET",
                    "http://local\nhost:7897", "http://[::1:7897"):
            invalid.append({"enabled": True, "url": url})
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ConfigError) as caught:
                self.load_proxy(value)
            self.assertNotIn("PRIVATE_SECRET", str(caught.exception))

    def test_shipped_config_does_not_force_machine_proxy_on_new_install(self):
        root = ASSETS_DIR
        example = load_config(root / "config/config.example.json", group_id=42)
        self.assertFalse(example.card_generator.proxy.enabled)
        self.assertIsNone(example.card_generator.proxy.url)
        # Current config is parsed too; no model, task or network operations are run.
        self.assertIsInstance(load_config(root / "config/config.json").card_generator.proxy, CodexProxyConfig)

class ProxyEnvironmentTests(unittest.TestCase):
    def test_override_is_a_copy_and_preserves_pdf_reader_metadata(self):
        metadata = {"HYDRO_SOURCE_PDF": "source.pdf", "NO_PROXY": "*", "https_proxy": "old"}
        original = dict(metadata)
        env = codex_proxy_environment(PROXY, metadata)
        self.assertEqual(metadata, original)
        self.assertEqual(env["HYDRO_SOURCE_PDF"], "source.pdf")
        for name in PROXY_VARIABLES:
            self.assertEqual(env[name], PROXY.url)
            self.assertEqual(env[name.lower()], PROXY.url)
        self.assertEqual(env["NO_PROXY"], "localhost,127.0.0.1,::1,intranet.example")
        self.assertEqual(env["NO_PROXY"], env["no_proxy"])

    def test_disabled_does_not_force_direct_or_erase_existing_environment(self):
        metadata = {"HTTPS_PROXY": "http://old:1234", "NO_PROXY": "*"}
        self.assertEqual(codex_proxy_environment(CodexProxyConfig(), metadata), metadata)
        self.assertEqual(codex_proxy_environment(CodexProxyConfig()), {})

    def test_empty_bypass_still_keeps_local_addresses(self):
        env = codex_proxy_environment(replace(PROXY, no_proxy=()))
        self.assertEqual(env["NO_PROXY"].split(","), list(LOCAL_BYPASS))
        self.assertFalse(proxy_summary(PROXY)["connectivity_verified"])

    def test_all_execution_paths_only_change_their_own_child(self):
        # A real, tiny Python child only reports environment; it never opens a socket.
        script = "import json,os,sys; sys.stdin.read(); print(json.dumps({k:os.environ.get(k) for k in ['HTTPS_PROXY','WSS_PROXY','NO_PROXY']}))"
        command = [sys.executable, "-u", "-c", script]
        inherited = {"HTTPS_PROXY": "http://parent.invalid:1222", "WSS_PROXY": "http://parent.invalid:1222", "NO_PROXY": "*"}
        with patch.dict(os.environ, inherited):
            before = dict(os.environ)
            env = codex_proxy_environment(PROXY)
            calls = (
                lambda: _run_command(command, 5, env),
                lambda: _run_prompt_command(command, "", 5, env),
                lambda: run_streaming_prompt(command, "", 5, env),
            )
            # subprocess.run without input inherits stdin; avoid reading it in that path.
            command[-1] = script.replace("sys.stdin.read(); ", "")
            for run in calls:
                result = run()
                self.assertEqual(result.returncode, 0, result.stderr)
                observed = json.loads(result.stdout)
                self.assertEqual(observed["HTTPS_PROXY"], PROXY.url)
                self.assertEqual(observed["WSS_PROXY"], PROXY.url)
                self.assertNotEqual(observed["NO_PROXY"], "*")
                self.assertEqual(dict(os.environ), before)
            # A later unrelated child still inherits the original parent settings.
            other = _run_command(command, 5)
            self.assertEqual(json.loads(other.stdout), inherited)

class ProxyAdapterTests(unittest.TestCase):

    def test_local_pdf_generation_receives_proxy_only_in_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = LocalProviderFixture(Path(directory))
            fixture.adapter.config = replace(fixture.config, proxy=PROXY)
            result = fixture.run()
            self.assertTrue(result["ok"], result)
            command, prompt, _, env = fixture.calls[0]
            self.assertEqual(env["HTTPS_PROXY"], PROXY.url)
            self.assertNotIn(PROXY.url, prompt)
            self.assertNotIn(PROXY.url, " ".join(command))

    def test_legacy_pdf_environment_and_streaming_default_are_both_wired(self):
        metadata = {"HYDRO_SOURCE_PDF": "source.pdf", "HYDRO_PDF_RECEIPT": "receipt.json"}
        config = replace(generator_config(), proxy=PROXY)
        for mocked in (True, False):
            with self.subTest(mocked=mocked):
                prompt_runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
                with patch("hydrolitagent.cards.card_generators.codex_cli.run_streaming_prompt", prompt_runner):
                    adapter = CodexCliAdapter(config, **({"prompt_runner": prompt_runner} if mocked else {}))
                    adapter._prompt_runner(["codex", "exec"], "task", 5, metadata)
                env = prompt_runner.call_args.args[3]
                self.assertEqual(env["HTTPS_PROXY"], PROXY.url)
                for key, value in metadata.items():
                    self.assertEqual(env[key], value)
                self.assertNotIn("HTTPS_PROXY", metadata)

if __name__ == "__main__":
    unittest.main()
