from __future__ import annotations

import hashlib
import io
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.cli import main, _render_human
from hydro_platform.config import ConfigError, load_config
from hydro_platform.native_deployment import (MARKER, TOOLS, NativeDeploymentError, _ReleaseRedirects,
    _archive, _archive_entries, _binding, _extract, _probe_tools, _publish_bytes,
    bootstrap_native, load_native_lock)
from hydro_platform.tasks import PipelineRunLock
from test_config import write_config


class NativeDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hydro native 中文 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = write_config(self.root)
        self.config = load_config(self.path)
        path = self.config.deployment.native_lock_file
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).resolve().parents[1] / "setup/native-tools.lock.json", path)
        self.lock, self.digest = load_native_lock(self.config)
        self.target = self.config.deployment.native_tools_dir

    def files(self):
        return {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def zip_bytes(self, extra=None, *, only_extra=False):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            if not only_extra:
                for name, path in TOOLS.items():
                    archive.writestr(self.lock["archive_root"] + "/" + path, (name + " fixture not executed").encode())
            for name, raw in extra or []:
                if isinstance(name, str) and "\\" in name:
                    info = zipfile.ZipInfo(name)
                    info.filename = info.orig_filename = name
                    name = info
                archive.writestr(name, raw)
        return stream.getvalue()

    def cached_archive(self, extra=None):
        raw = self.zip_bytes(extra)
        lock = dict(self.lock, sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        self.config.deployment.native_lock_file.write_text(json.dumps(lock))
        self.lock, self.digest = load_native_lock(self.config)
        cache = self.config.deployment.native_cache_dir
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / self.lock["filename"]
        path.write_bytes(raw)
        return path

    def install_fixture(self):
        self.cached_archive()
        with patch("hydro_platform.native_deployment._probe_tools", return_value={"fixture": "not executed"}):
            return bootstrap_native(self.config, install=True)

    def test_plan_is_read_only_no_download_or_executable(self):
        before = self.files()
        with patch("hydro_platform.native_deployment._archive", side_effect=AssertionError("no download")), \
             patch("hydro_platform.native_deployment._probe_tools", side_effect=AssertionError("no exec")):
            result = bootstrap_native(self.config)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "PLAN")
        self.assertEqual(before, self.files())

    def test_unmanaged_target_is_preserved(self):
        self.target.mkdir(parents=True)
        (self.target / "keep.txt").write_text("personal")
        before = self.files()
        result = bootstrap_native(self.config, install=True)
        self.assertEqual(result["error"]["code"], "NATIVE_OWNERSHIP_CONFLICT")
        self.assertEqual(before, self.files())

    def test_install_and_offline_reuse_do_not_change_files(self):
        first = self.install_fixture()
        self.assertEqual(first["status"], "INSTALLED", first)
        self.assertEqual(first["file_count"], 3)
        before = self.files()
        with patch("hydro_platform.native_deployment._archive", side_effect=AssertionError("no download")), \
             patch("hydro_platform.native_deployment._probe_tools", return_value={}):
            second = bootstrap_native(self.config, install=True)
        self.assertEqual(second["status"], "REUSED")
        self.assertEqual(before, self.files())

    def test_changed_binary_is_not_overwritten_or_executed(self):
        self.install_fixture()
        tool = self.target / TOOLS["pdfinfo"]
        tool.write_bytes(b"changed")
        with patch("hydro_platform.native_deployment._probe_tools", side_effect=AssertionError("no exec")):
            result = bootstrap_native(self.config, install=True)
        self.assertEqual(result["error"]["code"], "NATIVE_INSTALL_DRIFT")
        self.assertEqual(tool.read_bytes(), b"changed")

    def test_unexpected_extra_file_rejected(self):
        self.install_fixture()
        (self.target / "personal.txt").write_text("keep")
        result = bootstrap_native(self.config, verify=True)
        self.assertEqual(result["error"]["code"], "NATIVE_INSTALL_DRIFT")
        self.assertEqual((self.target / "personal.txt").read_text(), "keep")

    def test_wrong_lock_or_project_marker_does_not_take_over(self):
        self.install_fixture()
        marker = self.target / MARKER
        original = json.loads(marker.read_text(encoding="utf-8"))
        for values in ({"project_root": "other project"}, {"lock_sha256": "f" * 64}):
            with self.subTest(values=values):
                marker.write_text(json.dumps(dict(original, **values)))
                result = bootstrap_native(self.config, install=True)
                self.assertEqual(result["error"]["code"], "NATIVE_OWNERSHIP_CONFLICT")

    def test_interrupted_owned_extraction_can_resume_identical_files(self):
        archive = self.cached_archive()
        self.target.mkdir(parents=True)
        (self.target / MARKER).write_text(json.dumps({**_binding(self.config, self.digest), "status": "INSTALLING"}))
        existing = self.target / TOOLS["pdfinfo"]
        existing.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive) as z:
            existing.write_bytes(z.read(self.lock["archive_root"] + "/" + TOOLS["pdfinfo"]))
        before = existing.read_bytes()
        with patch("hydro_platform.native_deployment._probe_tools", return_value={}):
            result = bootstrap_native(self.config, install=True)
        self.assertEqual(result["status"], "INSTALLED", result)
        self.assertEqual(before, existing.read_bytes())

    def test_bad_zip_hash_preserved_before_target_created(self):
        path = self.cached_archive()
        path.write_bytes(b"corrupted")
        result = bootstrap_native(self.config, install=True)
        self.assertEqual(result["error"]["code"], "NATIVE_ARCHIVE_HASH_MISMATCH")
        self.assertEqual(path.read_bytes(), b"corrupted")
        self.assertFalse(self.target.exists())

    def test_invalid_source_version_size_and_tools_rejected(self):
        original = self.config.deployment.native_lock_file.read_text()
        for field, value in (("url", "https://evil.test/p.zip"), ("sha256", "bad"), ("version", "latest"),
                             ("filename", "../a.zip"), ("size_bytes", -1), ("tools", {"pdfinfo": "run.cmd"}),
                             ("archive_root", "../escape"), ("uncompressed_size_limit", 900_000_000)):
            with self.subTest(field=field):
                lock = json.loads(original)
                lock[field] = value
                self.config.deployment.native_lock_file.write_text(json.dumps(lock))
                with self.assertRaises(NativeDeploymentError):
                    load_native_lock(self.config)

    def test_zip_slip_windows_ads_and_reserved_names_rejected(self):
        for relative in ("../escape", "Library/../../escape", "Library/a:stream", "Library/CON.txt", "/absolute",
                         "Library/trailing. ", "Library\\escape", "Library/a\x01", "Library//a"):
            with self.subTest(relative=relative):
                data = self.zip_bytes([(self.lock["archive_root"] + "/" + relative, b"bad")])
                with zipfile.ZipFile(io.BytesIO(data)) as archive, self.assertRaises(NativeDeploymentError):
                    _archive_entries(archive, self.lock)

    def test_archive_link_and_case_collisions_rejected(self):
        info = zipfile.ZipInfo(self.lock["archive_root"] + "/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        for extras in ([(info, b"outside")], [(self.lock["archive_root"] + "/Library/bin/PDFINFO.exe", b"collision")]):
            with self.subTest(extras=extras):
                with zipfile.ZipFile(io.BytesIO(self.zip_bytes(extras))) as archive, self.assertRaises(NativeDeploymentError):
                    _archive_entries(archive, self.lock)

    def test_archive_missing_tools_size_and_count_caps_rejected(self):
        cases = [(self.zip_bytes(only_extra=True), self.lock),
                 (self.zip_bytes(), dict(self.lock, uncompressed_size_limit=5)),
                 (self.zip_bytes(), dict(self.lock, file_count_limit=1))]
        for raw, lock in cases:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive, self.assertRaises(NativeDeploymentError):
                _archive_entries(archive, lock)

    def test_all_archive_names_checked_before_first_file_write(self):
        path = self.cached_archive([(self.lock["archive_root"] + "/../escape", b"bad")])
        self.target.mkdir(parents=True)
        with self.assertRaises(NativeDeploymentError):
            _extract(path, self.target, self.lock)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_download_hash_checked_and_then_cache_used_without_network(self):
        raw = self.zip_bytes()
        lock = dict(self.lock, sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = raw
        response.geturl.return_value = "https://release-assets.githubusercontent.com/release/file.zip?token=fixture"
        opener = Mock()
        opener.open.return_value = response
        with patch("hydro_platform.native_deployment.build_opener", return_value=opener):
            first = _archive(lock, self.config.deployment.native_cache_dir, 5)
            second = _archive(lock, self.config.deployment.native_cache_dir, 5)
        self.assertEqual(first, second)
        opener.open.assert_called_once()
        response.read.assert_called_once_with(len(raw) + 1)

    def test_redirect_rejected_before_contacting_unknown_host(self):
        handler = _ReleaseRedirects()
        for url in ("http://github.com/file", "https://evil.test/file", "https://github.com:999/file", "https://user:pass@github.com/file"):
            with self.subTest(url=url), self.assertRaises(NativeDeploymentError):
                handler.redirect_request(Request(self.lock["url"]), None, 302, "redirect", {}, url)

    def test_wrong_download_hash_not_cached_or_executed(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"bad"
        response.geturl.return_value = self.lock["url"]
        opener = Mock()
        opener.open.return_value = response
        with patch("hydro_platform.native_deployment.build_opener", return_value=opener), self.assertRaises(NativeDeploymentError):
            _archive(self.lock, self.config.deployment.native_cache_dir, 5)
        self.assertFalse(self.config.deployment.native_cache_dir.exists())

    def test_conflicting_file_preserved(self):
        file = self.root / "file"
        file.write_bytes(b"user")
        with self.assertRaises(NativeDeploymentError):
            _publish_bytes(file, b"new")
        self.assertEqual(file.read_bytes(), b"user")

    def test_probe_absolute_exes_no_old_external_path(self):
        def run(argv, **kwargs):
            name = Path(argv[0]).stem
            return subprocess.CompletedProcess(argv, 0, b"", f"{name} version 26.07.0\n".encode())
        with patch("hydro_platform.native_deployment.subprocess.run", side_effect=run) as execute:
            result = _probe_tools(self.target, self.lock, 9)
        self.assertEqual(len(result), 3)
        for call in execute.call_args_list:
            self.assertTrue(Path(call.args[0][0]).is_absolute())
            self.assertEqual(call.args[0][1:], ["-v"])
            self.assertEqual(call.kwargs["timeout"], 9)
            self.assertNotIn("codex", call.kwargs["env"]["PATH"].lower())

    def test_failed_process_does_not_mark_ready(self):
        self.cached_archive()
        with patch("hydro_platform.native_deployment.subprocess.run", return_value=subprocess.CompletedProcess([], 1, b"", b"secret")):
            result = bootstrap_native(self.config, install=True)
        self.assertEqual(result["error"]["code"], "NATIVE_TOOL_PROBE_FAILED")
        self.assertNotIn("secret", json.dumps(result))
        self.assertEqual(json.loads((self.target / MARKER).read_text())["status"], "INSTALLING")

    def test_unknown_platform_no_download_or_creation(self):
        with patch("hydro_platform.native_deployment.platform.machine", return_value="ARM64"):
            result = bootstrap_native(self.config, install=True)
        self.assertEqual(result["error"]["code"], "NATIVE_PLATFORM_UNSUPPORTED")
        self.assertFalse(self.target.exists())

    def test_live_lock_rejects_parallel_installer(self):
        with PipelineRunLock(self.target.parent / (self.target.name + ".bootstrap.lock")):
            result = bootstrap_native(self.config, install=True)
        self.assertEqual(result["error"]["code"], "TASK_STORE_BUSY")
        self.assertFalse(self.target.exists())

    def test_config_protects_code_knowledge_environment_and_lock(self):
        original = self.path.read_text()
        for fields in ({"native_tools_dir": "."}, {"native_tools_dir": "../outside"},
                       {"native_tools_dir": "evidence-packs/tools"}, {"native_cache_dir": "automation/cache"},
                       {"native_tools_dir": ".venv/tools"}, {"native_cache_dir": ".tools/poppler/cache"},
                       {"native_lock_file": ".tools/poppler/lock.json"}):
            with self.subTest(fields=fields):
                data = json.loads(original)
                data["deployment"] = fields
                self.path.write_text(json.dumps(data))
                with self.assertRaises(ConfigError):
                    load_config(self.path)

    def test_cli_routes_install_without_group_or_model(self):
        with patch("hydro_platform.cli.bootstrap_native", return_value={"ok": True}) as install, redirect_stdout(io.StringIO()) as out:
            code = main(["bootstrap-native", "--config", str(self.path), "--install", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["ok"])
        self.assertTrue(install.call_args.kwargs["install"])
        self.assertIn("PDF工具", _render_human({"operation": "bootstrap_native", "status": "PLAN"}))


if __name__ == "__main__":
    unittest.main()
