"""Install a hash-locked wheel into a new, project-owned venv; never mutate global Python."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from hydro_platform.publication import atomic_text
from hydro_platform.tasks import PipelineRunLock, TaskStoreError

MARKER = ".hydro-environment.json"
PROBE = """import json,sys,site,importlib.metadata as m
names=json.loads(sys.argv[1]); packages={}
for name in names:
    try:
        d=m.distribution(name)
        packages[name]={'version':d.version,'location':str(d.locate_file(''))}
    except m.PackageNotFoundError:
        packages[name]=None
print(json.dumps({'python':list(sys.version_info[:3]),'prefix':sys.prefix,
    'base_prefix':sys.base_prefix,'user_site':site.ENABLE_USER_SITE,
    'site_packages':site.getsitepackages(),'packages':packages}))
"""


class DeploymentError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def load_dependency_lock(config):
    path = config.deployment.dependency_lock_file or config.paths.project_root / "automation/setup/dependencies.lock.json"
    raw = path.read_bytes()
    data = json.loads(raw)
    def require(condition):
        if not condition:
            raise ValueError("invalid lock")
    try:
        require(data["schema_version"] == 1)
        for key in ("minimum", "maximum_exclusive"):
            values = data["python"][key]
            require(isinstance(values, list) and len(values) == 2 and all(type(v) is int and v >= 0 for v in values))
        require(tuple(data["python"]["minimum"]) < tuple(data["python"]["maximum_exclusive"]))
        require(isinstance(data["packages"], list) and data["packages"])
        names = set()
        for package in data["packages"]:
            name, version = package["name"], package["version"]
            require(re.fullmatch(r"[a-z][a-z0-9_]*", name) and name not in names)
            names.add(name)
            require(re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version))
            require(package["filename"] == f"{name}-{version}-py3-none-any.whl")
            require(re.fullmatch(r"[0-9a-f]{64}", package["sha256"]))
            require(type(package["size_bytes"]) is int and 0 < package["size_bytes"] <= 100_000_000)
            url = urlparse(package["url"])
            require(url.scheme == "https" and url.netloc == "files.pythonhosted.org")
            require(not url.query and not url.fragment and url.path.endswith("/" + package["filename"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise DeploymentError("DEPENDENCY_LOCK_INVALID", "依赖锁无效；只接受有版本、大小和 SHA256 的 PyPI 通用 wheel") from exc
    return data, hashlib.sha256(raw).hexdigest()


def _run(argv, timeout, stage):
    try:
        result = subprocess.run(argv, capture_output=True, timeout=timeout, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        raise DeploymentError("BOOTSTRAP_TIMEOUT", f"{stage} 超时；已停止等待，可查看环境状态后重试") from exc
    if result.returncode:
        raise DeploymentError("BOOTSTRAP_PROCESS_FAILED", f"{stage} 失败（退出码 {result.returncode}）；未输出可能含敏感信息的 stderr")
    return result


def _probe(python, packages, timeout):
    result = _run([str(python), "-I", "-B", "-c", PROBE, json.dumps([p["name"] for p in packages])], timeout, "Python 环境检查")
    return json.loads(result.stdout.decode("utf-8"))


def _supported(probe, lock):
    return tuple(lock["python"]["minimum"]) <= tuple(probe["python"][:2]) < tuple(lock["python"]["maximum_exclusive"])


def _verified(probe, lock, target):
    if (not _supported(probe, lock) or Path(probe["prefix"]).resolve() != target or
            probe["prefix"] == probe["base_prefix"] or probe["user_site"] is not False or
            not probe.get("site_packages") or
            any(not Path(p).resolve().is_relative_to(target) for p in probe["site_packages"])):
        return False
    return all((found := probe["packages"].get(p["name"])) and found["version"] == p["version"]
               and Path(found["location"]).resolve().is_relative_to(target) for p in lock["packages"])


def _owner(target, expected):
    if not target.exists():
        return None
    try:
        data = json.loads((target / MARKER).read_text(encoding="utf-8"))
        if not all(data.get(key) == value for key, value in expected.items()):
            raise ValueError("ownership mismatch")
        if data.get("status") not in {"CREATING", "INSTALLING", "READY"}:
            raise ValueError("unknown status")
        return data
    except (OSError, ValueError, AttributeError) as exc:
        raise DeploymentError("ENVIRONMENT_CONFLICT", "安装目标已存在，但不属于本项目/当前依赖锁；保留原目录，请在总配置选择新的空环境路径") from exc


def _wheel(package, cache, timeout):
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / package["filename"]
    if path.exists():
        if path.is_symlink() or path.stat().st_size != package["size_bytes"]:
            raise DeploymentError("WHEEL_HASH_MISMATCH", "已存在的 wheel 缓存大小不符或为链接；保留文件，未安装")
        raw = path.read_bytes()
    else:
        # Bound both socket waiting and payload size. Never run a source build or remote script.
        with urlopen(package["url"], timeout=timeout) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.netloc != "files.pythonhosted.org":
                raise DeploymentError("WHEEL_SOURCE_INVALID", "wheel 下载被重定向到非批准来源")
            raw = response.read(package["size_bytes"] + 1)
    if len(raw) != package["size_bytes"] or hashlib.sha256(raw).hexdigest() != package["sha256"]:
        raise DeploymentError("WHEEL_HASH_MISMATCH", "wheel 大小或 SHA256 与锁文件不一致，未安装")
    if not path.exists():
        with path.open("xb") as stream:
            stream.write(raw)
    return path


def bootstrap(config, *, install=False):
    result = {"schema_version": 1, "operation": "bootstrap", "ok": False,
              "model_call_count": 0, "install_requested": install, "steps": [],
              "config_modified": False, "knowledge_files_modified": False,
              "note": "只准备项目 Python 依赖；不安装 Zotero/Codex/Poppler、不登录账号、不注册每日调度、不推送 Git"}
    try:
        lock, digest = load_dependency_lock(config)
        settings = config.deployment
        root = config.paths.project_root.resolve()
        target = (settings.environment_dir or root / ".venv").resolve()
        cache = (settings.wheel_cache_dir or config.paths.runtime_dir / "wheel-cache").resolve()
        if target == root or not target.is_relative_to(root) or not cache.is_relative_to(root):
            raise DeploymentError("DEPLOYMENT_PATH_INVALID", "安装目录和缓存必须位于项目内，且环境不得是项目根目录")
        python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        expected = {"schema_version": 1, "owner": "hydro-platform", "project_root": str(root),
                    "environment_dir": str(target), "lock_sha256": digest}
        result.update(environment_dir=str(target), python_executable=str(python), lock_sha256=digest,
                      packages=[{"name": p["name"], "version": p["version"], "sha256": p["sha256"]} for p in lock["packages"]])
        owner = _owner(target, expected)
        base = shutil.which(settings.base_python or sys.executable)
        if base is None:
            raise DeploymentError("BASE_PYTHON_NOT_FOUND", "找不到 deployment.base_python 或当前 Python")
        base_probe = _probe(base, [], settings.install_timeout_seconds)
        if not _supported(base_probe, lock):
            raise DeploymentError("PYTHON_VERSION_UNSUPPORTED", "基础 Python 版本不在依赖锁允许范围内")
        result["base_python"] = {"executable": base, "version": base_probe["python"]}
        if not install:
            result.update(ok=True, status="PLAN", existing_status=owner["status"] if owner else "ABSENT")
            return result
        # One installer per configured environment; lock follows environment even if runtime changes.
        with PipelineRunLock(target.parent / (target.name + ".bootstrap.lock")):
            owner = _owner(target, expected)
            if owner and owner["status"] == "READY":
                probe = _probe(python, lock["packages"], settings.install_timeout_seconds)
                if not _verified(probe, lock, target):
                    raise DeploymentError("ENVIRONMENT_DRIFT", "已有项目环境的依赖或隔离状态发生变化；未自动覆盖，请选择新的环境目录")
                result.update(ok=True, status="REUSED", verification=probe)
                return result
            if owner is None:
                target.mkdir(parents=True, exist_ok=False)
                with (target / MARKER).open("x", encoding="utf-8") as stream:
                    json.dump({**expected, "status": "CREATING"}, stream)
            if owner is None or owner["status"] == "CREATING":
                _run([base, "-I", "-B", "-m", "venv", str(target)], settings.install_timeout_seconds, "创建项目虚拟环境")
                atomic_text(target / MARKER, json.dumps({**expected, "status": "INSTALLING"}))
                result["steps"].append("VENV_CREATED")
            for package in lock["packages"]:
                _wheel(package, cache, settings.download_timeout_seconds)
            requirements = target / "hydro-requirements.lock.txt"
            atomic_text(requirements, "\n".join(f"{p['name']}=={p['version']} --hash=sha256:{p['sha256']}" for p in lock["packages"]) + "\n")
            _run([str(python), "-I", "-B", "-m", "pip", "--isolated", "--disable-pip-version-check",
                  "install", "--no-index", "--no-deps", "--only-binary=:all:", "--require-hashes",
                  "--find-links", str(cache), "-r", str(requirements)], settings.install_timeout_seconds, "安装已核对的本地 wheel")
            _run([str(python), "-I", "-B", "-m", "pip", "--isolated", "--disable-pip-version-check", "check"],
                 settings.install_timeout_seconds, "核对依赖完整性")
            probe = _probe(python, lock["packages"], settings.install_timeout_seconds)
            if not _verified(probe, lock, target):
                raise DeploymentError("ENVIRONMENT_VERIFICATION_FAILED", "安装后版本或隔离验证未通过，未切换生产配置")
            atomic_text(target / MARKER, json.dumps({**expected, "status": "READY", "verification": probe}, indent=2))
            result.update(ok=True, status="INSTALLED", verification=probe)
            result["steps"].append("HASH_LOCKED_DEPENDENCIES_VERIFIED")
        return result
    except (DeploymentError, TaskStoreError, OSError, ValueError, TypeError, KeyError) as exc:
        result.update(status="FAILED", error={"code": getattr(exc, "code", "BOOTSTRAP_LOCAL_OR_DOWNLOAD_ERROR"),
            "message": str(exc) if isinstance(exc, (DeploymentError, TaskStoreError)) else
            "环境配置、文件访问或下载失败；未切换生产环境，保留已有文件；检查锁文件、基础 Python、代理和目录权限"})
        return result
