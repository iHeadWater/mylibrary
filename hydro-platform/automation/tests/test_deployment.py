from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.config import ConfigError, load_config
from hydro_platform.cli import main
from hydro_platform.deployment import (MARKER, DeploymentError, bootstrap, load_dependency_lock,
                                        _wheel, _verified, _run)
from test_config import write_config


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hydro setup 中文 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = write_config(self.root)
        self.config = load_config(self.path)
        lockpath = self.config.deployment.dependency_lock_file
        lockpath.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).resolve().parents[1] / "setup/dependencies.lock.json", lockpath)
        self.lock, self.digest = load_dependency_lock(self.config)
        self.target = self.config.deployment.environment_dir
        self.base = {"python": [3, 12, 14]}
        self.valid = {"python": [3, 12, 14], "prefix": str(self.target), "base_prefix": "base",
                      "site_packages": [str(self.target / "Lib/site-packages")],
                      "user_site": False, "packages": {"pypdf": {"version": "6.18.0", "location": str(self.target / "Lib/site-packages")}}}

    def files(self):
        return {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def owner(self, status="READY", **changes):
        self.target.mkdir(exist_ok=True)
        data = {"schema_version": 1, "owner": "hydro-platform", "project_root": str(self.root.resolve()),
                "environment_dir": str(self.target), "lock_sha256": self.digest, "status": status}
        data.update(changes)
        (self.target / MARKER).write_text(json.dumps(data), encoding="utf-8")

    def test_plan_writes_nothing_and_never_downloads(self):
        before = self.files()
        with patch("hydro_platform.deployment._probe", return_value=self.base), \
             patch("hydro_platform.deployment.urlopen", side_effect=AssertionError("no network")):
            result = bootstrap(self.config)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "PLAN")
        self.assertEqual(self.files(), before)
        self.assertFalse(self.target.exists())

    def test_unmanaged_directory_is_not_overwritten(self):
        self.target.mkdir()
        (self.target / "personal.txt").write_text("keep")
        before = self.files()
        result = bootstrap(self.config, install=True)
        self.assertEqual(result["error"]["code"], "ENVIRONMENT_CONFLICT")
        self.assertEqual(before, self.files())

    def test_old_lock_and_moved_environment_are_rejected(self):
        for change in ({"lock_sha256": "0" * 64}, {"project_root": "different-machine"}):
            with self.subTest(change=change):
                self.owner(**change)
                result = bootstrap(self.config, install=True)
                self.assertEqual(result["error"]["code"], "ENVIRONMENT_CONFLICT")

    def test_ready_environment_is_reused_without_pip_or_network(self):
        self.owner()
        with patch("hydro_platform.deployment._probe", side_effect=[self.base, self.valid]), \
             patch("hydro_platform.deployment._run", side_effect=AssertionError("no pip")), \
             patch("hydro_platform.deployment.urlopen", side_effect=AssertionError("no network")):
            result = bootstrap(self.config, install=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "REUSED")

    def test_version_drift_does_not_trigger_silent_upgrade(self):
        self.owner()
        self.valid["packages"]["pypdf"]["version"] = "0.1"
        with patch("hydro_platform.deployment._probe", side_effect=[self.base, self.valid]), \
             patch("hydro_platform.deployment._run", side_effect=AssertionError("no mutation")):
            result = bootstrap(self.config, install=True)
        self.assertEqual(result["error"]["code"], "ENVIRONMENT_DRIFT")

    def test_install_only_owned_venv_offline_hash_locked_wheels(self):
        with patch("hydro_platform.deployment._probe", side_effect=[self.base, self.valid]), \
             patch("hydro_platform.deployment._wheel", return_value=self.root / "verified.whl"), \
             patch("hydro_platform.deployment._run") as run:
            result = bootstrap(self.config, install=True)
        self.assertTrue(result["ok"], result)
        commands = [c.args[0] for c in run.call_args_list]
        self.assertIn(str(self.target), commands[0])
        install = commands[1]
        self.assertEqual(install[0], result["python_executable"])
        for flag in ("--no-index", "--no-deps", "--require-hashes", "--only-binary=:all:", "--isolated"):
            self.assertIn(flag, install)
        self.assertNotIn("--upgrade", install)
        self.assertEqual(json.loads((self.target / MARKER).read_text())["status"], "READY")

    def test_interrupted_owned_install_resumes_without_recreating_venv(self):
        self.owner("INSTALLING")
        with patch("hydro_platform.deployment._probe", side_effect=[self.base, self.valid]), \
             patch("hydro_platform.deployment._wheel"), patch("hydro_platform.deployment._run") as run:
            result = bootstrap(self.config, install=True)
        self.assertTrue(result["ok"], result)
        self.assertFalse(any("venv" in c.args[0] for c in run.call_args_list))

    def test_missing_python_and_bad_version_fail_before_creation(self):
        with patch("hydro_platform.deployment.shutil.which", return_value=None):
            result = bootstrap(self.config, install=True)
        self.assertEqual(result["error"]["code"], "BASE_PYTHON_NOT_FOUND")
        with patch("hydro_platform.deployment._probe", return_value={"python": [3, 11, 0]}):
            result = bootstrap(self.config, install=True)
        self.assertEqual(result["error"]["code"], "PYTHON_VERSION_UNSUPPORTED")
        self.assertFalse(self.target.exists())

    def test_dependency_lock_rejects_url_hash_filename_and_duplicate(self):
        original = self.config.deployment.dependency_lock_file.read_text()
        for field, value in (("url", "https://untrusted.example/script"), ("sha256", "bad"),
                             ("filename", "../escape.whl"), ("size_bytes", -1)):
            data = json.loads(original)
            data["packages"][0][field] = value
            self.config.deployment.dependency_lock_file.write_text(json.dumps(data))
            with self.assertRaises(DeploymentError):
                load_dependency_lock(self.config)
        data = json.loads(original)
        data["packages"] *= 2
        self.config.deployment.dependency_lock_file.write_text(json.dumps(data))
        with self.assertRaises(DeploymentError):
            load_dependency_lock(self.config)

    def test_bad_cached_wheel_is_preserved_not_installed(self):
        cache = self.config.deployment.wheel_cache_dir
        cache.mkdir(parents=True)
        package = self.lock["packages"][0]
        path = cache / package["filename"]
        path.write_bytes(b"bad")
        with patch("hydro_platform.deployment.urlopen", side_effect=AssertionError("no network")), self.assertRaises(DeploymentError):
            _wheel(package, cache, 1)
        self.assertEqual(path.read_bytes(), b"bad")

    def test_download_checked_then_cache_reused(self):
        raw = b"test-wheel"
        package = dict(self.lock["packages"][0], sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = package["url"]
        response.read.return_value = raw
        with patch("hydro_platform.deployment.urlopen", return_value=response) as download:
            path = _wheel(package, self.config.deployment.wheel_cache_dir, 2)
            self.assertEqual(_wheel(package, self.config.deployment.wheel_cache_dir, 2), path)
        download.assert_called_once()
        self.assertEqual(path.read_bytes(), raw)

    def test_external_package_location_and_user_site_rejected(self):
        self.assertTrue(_verified(self.valid, self.lock, self.target))
        self.valid["user_site"] = True
        self.assertFalse(_verified(self.valid, self.lock, self.target))
        self.valid["user_site"] = False
        self.valid["site_packages"].append(str(self.root / "global-site"))
        self.assertFalse(_verified(self.valid, self.lock, self.target))
        self.valid["site_packages"].pop()
        self.valid["packages"]["pypdf"]["location"] = str(self.root / "global")
        self.assertFalse(_verified(self.valid, self.lock, self.target))

    def test_config_rejects_destructive_targets_and_overlap(self):
        original = self.path.read_text()
        for fields in ({"environment_dir": "."}, {"environment_dir": "../outside"},
                       {"environment_dir": "evidence-packs/env"}, {"wheel_cache_dir": "automation"},
                       {"environment_dir": "tmp", "wheel_cache_dir": "tmp/cache"}):
            data = json.loads(original)
            data["deployment"] = fields
            self.path.write_text(json.dumps(data))
            with self.subTest(fields=fields), self.assertRaises(ConfigError):
                load_config(self.path)

    def test_relative_executables_use_project_root_not_working_directory(self):
        data = json.loads(self.path.read_text())
        data["card_generator"]["executable"] = "tools/codex.exe"
        data["deployment"] = {"base_python": "python"}
        self.path.write_text(json.dumps(data))
        config = load_config(self.path)
        self.assertEqual(config.card_generator.executable, str(self.root / "tools/codex.exe"))
        self.assertEqual(config.deployment.base_python, "python")

    def test_subprocess_failure_hides_stderr_and_no_shell(self):
        with patch("hydro_platform.deployment.subprocess.run", return_value=subprocess.CompletedProcess([], 1, b"", b"secret")) as run:
            with self.assertRaises(DeploymentError) as caught:
                _run(["python", "-V"], 1, "probe")
        self.assertNotIn("secret", str(caught.exception))
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_cli_default_plan_and_install_flag(self):
        for flag in ([], ["--install"]):
            with patch("hydro_platform.cli.bootstrap", return_value={"ok": True}) as start, redirect_stdout(io.StringIO()):
                code = main(["bootstrap", "--config", str(self.path), "--json", *flag])
            self.assertEqual(code, 0)
            self.assertEqual(start.call_args.kwargs["install"], bool(flag))


if __name__ == "__main__":
    unittest.main()
