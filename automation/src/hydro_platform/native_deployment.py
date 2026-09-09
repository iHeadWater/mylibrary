"""Hash-locked, project-owned Poppler installation. No system PATH, accounts or Git edits."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from hydro_platform.publication import atomic_text
from hydro_platform.tasks import PipelineRunLock, TaskStoreError

MARKER = ".hydro-native.json"
HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
RELEASE_ROOT = "https://github.com/oschwartz10612/poppler-windows/releases/download/"
TOOLS = {name: f"Library/bin/{name}.exe" for name in ("pdfinfo", "pdftoppm", "pdftotext")}


class NativeDeploymentError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _require(condition, code="NATIVE_LOCK_INVALID", message="原生依赖锁无效；不下载或执行未核对的工具"):
    if not condition:
        raise NativeDeploymentError(code, message)


def load_native_lock(config):
    raw = config.deployment.native_lock_file.read_bytes()
    data = json.loads(raw)
    _require(isinstance(data, dict) and data.get("schema_version") == 1)
    _require(data.get("name") == "poppler-windows" and data.get("platform") == "windows-x86_64")
    version = data.get("version")
    _require(isinstance(version, str) and re.fullmatch(r"[0-9]{2}\.[0-9]{2}\.[0-9]+", version))
    release = data.get("release")
    _require(isinstance(release, str) and re.fullmatch("v" + re.escape(version) + r"-[0-9]+", release))
    _require(data.get("filename") == "Release-" + release[1:] + ".zip")
    _require(data.get("url") == RELEASE_ROOT + release + "/" + data["filename"])
    _require(isinstance(data.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", data["sha256"]))
    for name, limit in (("size_bytes", 100_000_000), ("uncompressed_size_limit", 500_000_000), ("file_count_limit", 5000)):
        _require(type(data.get(name)) is int and 0 < data[name] <= limit)
    _require(data.get("archive_root") == "poppler-" + version and data.get("tools") == TOOLS)
    return data, hashlib.sha256(raw).hexdigest()


def _assert_local(path, root):
    path, root = Path(path).absolute(), Path(root).resolve()
    _require(path != root and path.resolve().is_relative_to(root), "NATIVE_PATH_INVALID", "原生工具路径超出项目或指向项目根目录")
    current = path
    while current != root:
        _require(not current.is_symlink() and not (hasattr(current, "is_junction") and current.is_junction()),
                 "NATIVE_PATH_REDIRECTED", "安装路径包含符号链接或目录联接，未写入")
        current = current.parent


def _binding(config, digest):
    return {"schema_version": 1, "owner": "hydro-platform-native", "project_root": str(config.paths.project_root.resolve()),
            "tools_dir": str(config.deployment.native_tools_dir.resolve()), "lock_sha256": digest}


def _owner(target, expected):
    if not target.exists():
        return None
    try:
        _require(not (target / MARKER).is_symlink(), "NATIVE_OWNERSHIP_CONFLICT", "原生工具所有权文件是链接")
        data = json.loads((target / MARKER).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or any(data.get(k) != v for k, v in expected.items()) or data.get("status") not in {"INSTALLING", "READY"}:
            raise ValueError("owner mismatch")
        return data
    except (OSError, ValueError) as exc:
        raise NativeDeploymentError("NATIVE_OWNERSHIP_CONFLICT", "原生工具目标已存在但不属于当前项目/锁；保留原目录，可配置新的安装目录") from exc


def _allowed_url(url):
    parsed = urlparse(url)
    return (parsed.scheme == "https" and parsed.hostname in HOSTS and parsed.port in {None, 443}
            and parsed.username is None and parsed.password is None)


class _ReleaseRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _require(_allowed_url(newurl), "NATIVE_DOWNLOAD_SOURCE_INVALID", "下载重定向离开批准的GitHub资产域名")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _digest_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _publish_bytes(path, raw, *, scratch_dir=None):
    """A crashed write can be retried; a different existing file is never replaced."""
    expected = hashlib.sha256(raw).hexdigest()
    if path.exists():
        _require(not path.is_symlink() and path.is_file() and path.stat().st_size == len(raw) and _digest_file(path) == expected,
                 "NATIVE_FILE_CONFLICT", "原生工具已有文件与锁定内容不同；保留修改，不覆盖")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch_dir = scratch_dir or path.parent
    scratch_dir.mkdir(parents=True, exist_ok=True)
    fd, scratch = tempfile.mkstemp(prefix=".native-", suffix=".tmp", dir=scratch_dir)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(scratch, path)
        except FileExistsError:
            _require(not path.is_symlink() and path.is_file() and _digest_file(path) == expected,
                     "NATIVE_FILE_CONFLICT", "原生工具文件在安装期间变化，未覆盖")
    finally:
        Path(scratch).unlink(missing_ok=True)  # Only this invocation's exact single temporary file.


def _archive(lock, cache, timeout):
    path = cache / lock["filename"]
    if path.exists():
        _require(path.is_file() and not path.is_symlink() and path.stat().st_size == lock["size_bytes"]
                 and _digest_file(path) == lock["sha256"], "NATIVE_ARCHIVE_HASH_MISMATCH", "原生工具缓存大小或SHA256不符；保留文件，不安装")
        return path
    opener = build_opener(_ReleaseRedirects())
    request = Request(lock["url"], headers={"User-Agent": "hydro-platform/1"})
    with opener.open(request, timeout=timeout) as response:
        _require(_allowed_url(response.geturl()), "NATIVE_DOWNLOAD_SOURCE_INVALID", "原生工具下载来源不符")
        raw = response.read(lock["size_bytes"] + 1)
    _require(len(raw) == lock["size_bytes"] and hashlib.sha256(raw).hexdigest() == lock["sha256"],
             "NATIVE_ARCHIVE_HASH_MISMATCH", "原生工具下载大小或SHA256不符；未解压或执行")
    _publish_bytes(path, raw)
    return path


def _archive_entries(archive, lock):
    entries, seen, total = [], set(), 0
    infos = archive.infolist()
    _require(0 < len(infos) <= lock["file_count_limit"], "NATIVE_ARCHIVE_INVALID", "归档文件数量超出锁定上限")
    for info in infos:
        raw = info.orig_filename
        parts = raw.rstrip("/").split("/")
        _require(not info.flag_bits & 1 and (info.external_attr >> 16) & 0o170000 in {0, stat.S_IFREG, stat.S_IFDIR},
                 "NATIVE_ARCHIVE_INVALID", "不解压加密文件、链接或特殊设备")
        _require(parts[0] == lock["archive_root"] and "\\" not in raw and
                 all(part and part not in {".", ".."} and part.rstrip(" .") == part and
                     not re.search(r'[<>:"|?*\x00-\x1f]', part) and
                     not re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part, re.I) for part in parts),
                 "NATIVE_ARCHIVE_PATH_INVALID", "归档路径越界或包含Windows危险名称")
        if len(parts) == 1:
            _require(info.is_dir(), "NATIVE_ARCHIVE_INVALID", "归档根不是目录")
            continue
        relative = PurePosixPath(*parts[1:]).as_posix()
        identity = relative.casefold()
        _require(identity not in seen and relative != MARKER, "NATIVE_ARCHIVE_INVALID", "归档存在重复路径或所有权文件")
        seen.add(identity)
        total += info.file_size
        _require(0 <= info.file_size <= lock["uncompressed_size_limit"] and total <= lock["uncompressed_size_limit"],
                 "NATIVE_ARCHIVE_INVALID", "归档解压大小超出锁定上限")
        entries.append((info, relative))
    files = {rel for info, rel in entries if not info.is_dir()}
    _require(set(TOOLS.values()).issubset(files), "NATIVE_ARCHIVE_INVALID", "归档缺少所需PDF工具")
    return entries


def _extract(archive_path, target, lock):
    files = {}
    scratch_dir = archive_path.parent / ".unpack"
    _assert_local(scratch_dir, archive_path.parent)
    with zipfile.ZipFile(archive_path) as archive:
        entries = _archive_entries(archive, lock)  # Validate all names before the first write.
        for info, relative in entries:
            path = target / relative
            _assert_local(path, target)
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            raw = archive.read(info)  # Zip CRC checked; aggregate size was bounded above.
            _publish_bytes(path, raw, scratch_dir=scratch_dir)
            files[relative] = {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
    return files


def _verify_files(target, files):
    _require(isinstance(files, dict) and set(TOOLS.values()).issubset(files), "NATIVE_INSTALL_DRIFT", "安装文件清单不完整")
    observed = set()
    for path in target.rglob("*"):
        _assert_local(path, target)
        if path.is_file() and path != target / MARKER:
            observed.add(path.relative_to(target).as_posix())
    _require(observed == set(files), "NATIVE_INSTALL_DRIFT", "原生工具存在新增或缺失文件；不执行、不自动覆盖")
    for relative, expected in files.items():
        path = target / relative
        _assert_local(path, target)
        _require(path.is_file() and path.stat().st_size == expected["size_bytes"] and _digest_file(path) == expected["sha256"],
                 "NATIVE_INSTALL_DRIFT", "原生工具文件指纹不符；不执行、不自动覆盖")


def _probe_tools(target, lock, timeout):
    results = {}
    env = dict(os.environ)
    # Version probes must not accidentally find DLLs in the old Codex/Conda PATH.
    env["PATH"] = str(target / "Library/bin") + os.pathsep + str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
    for name, relative in lock["tools"].items():
        process = subprocess.run([str(target / relative), "-v"], capture_output=True, timeout=timeout,
            check=False, cwd=target, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        text = (process.stdout + process.stderr).decode("utf-8", errors="replace")
        _require(process.returncode == 0 and re.search(r"^" + name + r" version " + re.escape(lock["version"]) + r"(?:\s|$)", text, re.M),
                 "NATIVE_TOOL_PROBE_FAILED", f"{name}不能独立运行或版本不符；未输出原始进程日志")
        results[name] = {"version": lock["version"], "executable": str(target / relative)}
    return results


def bootstrap_native(config, *, install=False, verify=False):
    result = {"schema_version": 1, "operation": "bootstrap_native", "ok": False,
        "install_requested": install, "model_call_count": 0, "config_modified": False,
        "knowledge_files_modified": False, "system_path_modified": False,
        "note": "只安装项目自有Poppler；不改全局环境、账号、Git或既有知识，验证后才由维护者切换配置"}
    try:
        _require(platform.system() == "Windows" and platform.machine().lower() in {"amd64", "x86_64"},
                 "NATIVE_PLATFORM_UNSUPPORTED", "当前锁定包仅支持Windows x86_64")
        lock, digest = load_native_lock(config)
        target, cache = config.deployment.native_tools_dir, config.deployment.native_cache_dir
        for path in (target, cache):
            _assert_local(path, config.paths.project_root)
        expected = _binding(config, digest)
        owner = _owner(target, expected)
        result.update(tools_dir=str(target), lock_sha256=digest, release=lock["release"],
            archive_sha256=lock["sha256"], existing_status=owner["status"] if owner else "ABSENT",
            tools={k: str(target / v) for k, v in lock["tools"].items()})
        if not install and not verify:
            return {**result, "ok": True, "status": "PLAN"}
        if verify:
            _require(owner and owner["status"] == "READY", "NATIVE_NOT_INSTALLED", "项目原生工具尚未完成安装")
            _verify_files(target, owner["files"])
            versions = _probe_tools(target, lock, config.deployment.install_timeout_seconds)
            return {**result, "ok": True, "status": "VERIFIED", "verification": versions, "file_count": len(owner["files"])}
        with PipelineRunLock(target.parent / (target.name + ".bootstrap.lock")):
            owner = _owner(target, expected)
            if owner and owner["status"] == "READY":
                _verify_files(target, owner["files"])
                versions = _probe_tools(target, lock, config.deployment.install_timeout_seconds)
                return {**result, "ok": True, "status": "REUSED", "verification": versions, "file_count": len(owner["files"])}
            archive = _archive(lock, cache, config.deployment.download_timeout_seconds)
            if owner is None:
                target.mkdir(parents=True, exist_ok=False)
                with (target / MARKER).open("x", encoding="utf-8") as stream:
                    json.dump({**expected, "status": "INSTALLING"}, stream)
            files = _extract(archive, target, lock)
            _verify_files(target, files)
            versions = _probe_tools(target, lock, config.deployment.install_timeout_seconds)
            atomic_text(target / MARKER, json.dumps({**expected, "status": "READY", "files": files,
                "verification": versions}, ensure_ascii=False, indent=2))
            result.update(ok=True, status="INSTALLED", verification=versions, file_count=len(files))
    except (NativeDeploymentError, TaskStoreError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        code = getattr(exc, "code", "NATIVE_INSTALL_FAILED")
        result.update(status="FAILED", error={"code": code if isinstance(code, str) else "NATIVE_INSTALL_FAILED",
            "message": str(exc) if isinstance(exc, (NativeDeploymentError, TaskStoreError)) else
            "原生工具安装或验证失败；保留已有文件，可检查配置/网络后重试，未切换生产路径",
            "diagnostic": {"failure_type": type(exc).__name__,
                           "errno": getattr(exc, "errno", None), "winerror": getattr(exc, "winerror", None)}})
    return result
