"""uv 托管的共享工作区 .venv：平台只验证，不 provisioning。

测试布局刻意镜像真实仓库：

    <workspace>/              等于仓库根目录（真实仓库里含 uv.lock 和根 .venv）
      .venv/                  由 uv 拥有；本套测试只把它作为配置值引用，从不创建它
      platform/               等于 hydro-platform/，即 paths.project_root
        config/config.json
        automation/setup/dependencies.lock.json

因此 deployment.environment_dir = "../.venv" 会解析到 platform 之外、工作区之内。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hydro_platform.config import ConfigError, load_config
from hydro_platform.deployment import bootstrap, load_dependency_lock
from test_config import write_config


WORKSPACE_VENV = "../.venv"
PROVISIONING_STATUSES = ("PLAN", "REUSED", "INSTALLED")


def forbidden_provisioning(argv, *args, **kwargs):
    """subprocess.run 的替身：一旦有 venv/pip/install 就判定 uv-managed 模式违规。"""
    rendered = " ".join(str(part) for part in argv).lower()
    for token in ("venv", "pip", "install"):
        if token in rendered:
            raise AssertionError(f"uv-managed 模式不得创建 venv 或安装依赖，却执行了：{argv!r}")
    return subprocess.CompletedProcess(argv, 0, b"", b"")


class UvManagedDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hydro uv managed ")
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.root = self.workspace / "platform"
        self.path = write_config(self.root)
        self.config = load_config(self.path)
        lockpath = self.config.deployment.dependency_lock_file
        lockpath.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            Path(__file__).resolve().parents[1] / "setup/dependencies.lock.json",
            lockpath,
        )
        self.lock, self.digest = load_dependency_lock(self.config)
        self.target = (self.workspace / ".venv").resolve()
        self.base = {"python": [3, 12, 14], "prefix": str(self.root / "base-python"),
                     "base_prefix": str(self.root / "base-python"), "user_site": False,
                     "site_packages": [], "packages": {}}

    # -- 复用 test_deployment.py 的装配方式：改写配置 JSON 后重新 load_config --
    def files(self):
        return {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def write_deployment(self, environment_dir):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["deployment"] = {"environment_dir": environment_dir}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        return self.path

    def uv_config(self):
        return load_config(self.write_deployment(WORKSPACE_VENV))

    def probe_payload(self, pypdf_version=None):
        location = str(self.target / "Lib/site-packages")
        packages = {}
        for package in self.lock["packages"]:
            version = package["version"]
            if package["name"] == "pypdf" and pypdf_version is not None:
                version = pypdf_version
            packages[package["name"]] = {"version": version, "location": location}
        return {"python": [3, 12, 14], "prefix": str(self.target), "base_prefix": "base",
                "site_packages": [location], "user_site": False, "packages": packages}

    def probe(self, pypdf_version=None):
        payload = self.probe_payload(pypdf_version=pypdf_version)

        def fake(python, packages, timeout):
            return payload if packages else self.base

        return fake

    # -- 1. 配置必须接受工作区 .venv --------------------------------------
    def test_config_accepts_workspace_venv_outside_platform_root(self):
        self.write_deployment(WORKSPACE_VENV)
        try:
            config = load_config(self.path)
        except ConfigError as error:
            self.fail(
                f'deployment.environment_dir="{WORKSPACE_VENV}" 必须被接受（解析为 {self.target}），'
                f"但 load_config 报错：{error}"
            )
        self.assertEqual(config.deployment.environment_dir, self.target,
                         f"期望解析为 {self.target}")
        self.assertFalse(
            config.deployment.environment_dir.is_relative_to(config.paths.project_root),
            "该路径必须位于平台根目录（self-contained 模式判定的）之外",
        )

    # -- 2. 危险目标仍然必须被拒绝 ----------------------------------------
    def test_config_still_rejects_destructive_and_escaping_targets(self):
        for value in (".", "evidence-packs/env", "automation", "../../../outside"):
            with self.subTest(environment_dir=value):
                self.write_deployment(value)
                try:
                    config = load_config(self.path)
                except ConfigError:
                    continue
                self.fail(
                    f"deployment.environment_dir={value!r} 必须被拒绝，"
                    f"但 load_config 返回了 {config.deployment.environment_dir}"
                )

    # -- 3. 计划模式：不写文件、不联网 -------------------------------------
    def test_plan_mode_in_uv_managed_mode_writes_and_downloads_nothing(self):
        config = self.uv_config()
        before = self.files()
        with patch("hydro_platform.deployment._probe", side_effect=self.probe()), \
             patch("hydro_platform.deployment.urlopen", side_effect=AssertionError("no network")):
            result = bootstrap(config)
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("ok"), f"uv-managed 计划模式应成功，实际返回：{result}")
        self.assertEqual(self.files(), before, f"计划模式不得改动平台目录，实际返回：{result}")
        self.assertFalse(self.target.exists(),
                         f"uv-managed 环境由 uv 拥有，计划模式不得创建它，实际返回：{result}")

    # -- 4. 即使 install=True 也绝不 provisioning ---------------------------
    def test_uv_managed_mode_never_provisions_even_when_install_requested(self):
        config = self.uv_config()
        before = self.files()
        with patch("hydro_platform.deployment._probe", side_effect=self.probe()), \
             patch("hydro_platform.deployment.subprocess.run", side_effect=forbidden_provisioning), \
             patch("hydro_platform.deployment.urlopen", side_effect=AssertionError("no network")):
            result = bootstrap(config, install=True)
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("ok"), f"uv-managed 模式 install=True 应成功返回，实际返回：{result}")
        self.assertEqual(self.files(), before, f"不得改动平台目录，实际返回：{result}")

    # -- 5. 结果必须告诉操作者用 uv sync -----------------------------------
    def test_uv_managed_result_tells_the_operator_to_run_uv_sync(self):
        config = self.uv_config()
        with patch("hydro_platform.deployment._probe", side_effect=self.probe()), \
             patch("hydro_platform.deployment.subprocess.run", side_effect=forbidden_provisioning), \
             patch("hydro_platform.deployment.urlopen", side_effect=AssertionError("no network")):
            result = bootstrap(config, install=True)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertTrue(result.get("ok"), f"期望成功的验证结果，实际返回：{serialized}")
        self.assertIn("uv sync", serialized,
                      f"结果必须提示操作者环境由 uv sync 创建，实际返回：{serialized}")

    # -- 6. 状态必须与 self-contained 模式区分 -----------------------------
    def test_uv_managed_result_distinguishes_its_status(self):
        config = self.uv_config()
        with patch("hydro_platform.deployment._probe", side_effect=self.probe()), \
             patch("hydro_platform.deployment.subprocess.run", side_effect=forbidden_provisioning), \
             patch("hydro_platform.deployment.urlopen", side_effect=AssertionError("no network")):
            result = bootstrap(config, install=True)
        self.assertTrue(result.get("ok"), f"期望成功的验证结果，实际返回：{result}")
        status = result.get("status")
        self.assertIsInstance(status, str, f"status 必须是字符串，实际返回：{result}")
        self.assertTrue(status.strip(), f"status 必须非空，实际返回：{result}")
        self.assertNotIn(status, PROVISIONING_STATUSES,
                         f"uv-managed 状态不得沿用 self-contained 的状态：{result}")
        self.assertEqual(Path(result["environment_dir"]).resolve(), self.target,
                         f"environment_dir 必须是工作区 .venv，实际返回：{result}")

    # -- 7. 仍然检测漂移，且不静默修复 -------------------------------------
    def test_uv_managed_drift_is_reported_and_never_silently_fixed(self):
        config = self.uv_config()
        locked = next((p for p in self.lock["packages"] if p["name"] == "pypdf"), None)
        self.assertIsNotNone(locked, "依赖锁必须包含 pypdf，本用例才有意义")
        drifted = "0.1"
        self.assertNotEqual(drifted, locked["version"], "漂移版本必须与依赖锁不同")
        with patch("hydro_platform.deployment._probe",
                   side_effect=self.probe(pypdf_version=drifted)), \
             patch("hydro_platform.deployment.subprocess.run", side_effect=forbidden_provisioning), \
             patch("hydro_platform.deployment.urlopen", side_effect=AssertionError("no network")):
            result = bootstrap(config, install=True)
        # subprocess.run 被 forbidden_provisioning 接管：一旦尝试建 venv/装包就抛
        # AssertionError，而 bootstrap 的 except 元组不含 AssertionError，因此会直接
        # 冒泡为测试失败，而不是被吞成 {"ok": false}。
        self.assertFalse(result.get("ok", False),
                         f"pypdf 版本与依赖锁不一致时必须失败，而不是静默修复：{result}")
        error = result.get("error")
        self.assertIsInstance(error, dict, f"漂移必须带 error 对象，实际返回：{result}")
        # 必须是"检测到漂移"，而不是"路径被拒"或"探针失败"——只有漂移检测会给出这个码。
        self.assertEqual(error.get("code"), "ENVIRONMENT_DRIFT",
                         f"必须是漂移检测失败（而非路径拒绝或探针失败）：{result}")
        self.assertTrue(str(error.get("message") or "").strip(),
                        f"error.message 必须非空，实际返回：{result}")
        # 模式专属状态，而不是通用兜底 FAILED：后者意味着异常是从 bootstrap 的
        # except 分支冒出来的，即根本没走到 uv-managed 的判定逻辑。
        status = result.get("status")
        self.assertIsInstance(status, str, f"status 必须是字符串，实际返回：{result}")
        self.assertNotEqual(status, "FAILED",
                            f"漂移必须给出 uv-managed 模式专属状态，而不是通用 FAILED：{result}")

    # -- 8. self-contained 模式回归护栏（写测试时即为 GREEN） ----------------
    def test_self_contained_mode_still_plans(self):
        installed = (self.root / ".venv").resolve()
        self.assertEqual(self.config.deployment.environment_dir, installed)
        self.assertTrue(installed.is_relative_to(self.root))
        before = self.files()
        with patch("hydro_platform.deployment._probe", side_effect=self.probe()), \
             patch("hydro_platform.deployment.urlopen", side_effect=AssertionError("no network")):
            result = bootstrap(self.config)
        self.assertTrue(result.get("ok"), f"平台内环境描述仍应走计划模式，实际返回：{result}")
        self.assertEqual(result.get("status"), "PLAN", f"实际返回：{result}")
        self.assertEqual(self.files(), before, f"计划模式不得改动平台目录：{result}")
        self.assertFalse(installed.exists(), f"计划模式不得创建环境目录：{result}")


if __name__ == "__main__":
    unittest.main()
