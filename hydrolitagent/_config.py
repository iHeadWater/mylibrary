from __future__ import annotations

import ast
import os
import re
import warnings
from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


def _parse_value(value: str) -> Any:
    value = value.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    if re_match := re.fullmatch(r"-?\d+", value):
        return int(re_match.group(0))
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value.strip('"')


def _split_table_name(name: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_quote = False
    for ch in name:
        if ch == '"':
            in_quote = not in_quote
            continue
        if ch == "." and not in_quote:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return [part for part in parts if part]


def _minimal_toml_loads(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    current = root
    pending_key = ""
    pending_value_lines: list[str] = []
    bracket_balance = 0

    def assign(key: str, raw_value: str) -> None:
        current[key.strip().strip('"')] = _parse_value(raw_value)

    for original in text.splitlines():
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if pending_key:
            pending_value_lines.append(line)
            bracket_balance += line.count("[") - line.count("]")
            if bracket_balance <= 0:
                assign(pending_key, "\n".join(pending_value_lines))
                pending_key = ""
                pending_value_lines = []
            continue
        if line.startswith("[") and line.endswith("]"):
            current = root
            for part in _split_table_name(line[1:-1]):
                current = current.setdefault(part, {})
            continue
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        raw_value = raw_value.strip()
        if raw_value.startswith("[") and raw_value.count("[") > raw_value.count("]"):
            pending_key = key
            pending_value_lines = [raw_value]
            bracket_balance = raw_value.count("[") - raw_value.count("]")
            continue
        assign(key, raw_value)
    return root


def load_toml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if tomllib is not None:
        with path.open("rb") as f:
            return tomllib.load(f)
    return _minimal_toml_loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# 仓库根。层级算术只在这里做一次:hydrolitagent/_config.py → 仓库根。
# literature/_paths.py 曾自己算过一次(parent 三次),同一个事实两处维护。
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PATHS_CONFIG = PROJECT_ROOT / "configs" / "paths.toml"
DEFAULT_LITERATURE_ROOT = PROJECT_ROOT / "outputs"
LITERATURE_ROOT_ENV = "HYDROLITAGENT_LITERATURE_ROOT"

# 外部产物根的长度告警线。Windows MAX_PATH 是 260,留 80 字符给产物子树
# ——`outputs/graph` 那种 229 字符的相对路径会撞墙,而短目录名不会。
EXTERNAL_ROOT_LENGTH_BUDGET = 180


class PathConfigError(RuntimeError):
    """``configs/paths.toml`` 格式错,或提交进仓库的配置写出了工作区外。"""


def read_dotenv_values(env_file: str | Path | None = None) -> dict[str, str]:
    """读取 ``<repo>/.env`` 的键值,**不修改 os.environ**。

    语义与 python-dotenv 的 ``override=False`` 一致:调用方自行让 os.environ 优先。
    文件不存在返回 ``{}`` —— ``.env`` 是可选的、不进 Git 的本机文件。

    存在这个函数是因为 literature/ 下的模块(download_pdf / bilibili_upload /
    zotero_notebooklm)都不调用 ``load_dotenv``,只读 ``os.environ`` 会让写在
    ``.env`` 里的配置静默失效。
    """
    path = Path(env_file) if env_file is not None else PROJECT_ROOT / ".env"
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if not key:
            continue

        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            # 未加引号时,` #` 之后是注释。要求前面有空白,免得吃掉路径里的 `#`。
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        values[key] = value
    return values


def load_paths_config(path: str | Path | None = None) -> dict[str, Any]:
    """返回 ``configs/paths.toml`` 的 ``[literature]`` 表。

    文件不存在或没有该表 → ``{}``(裸检出仍能跑);该表不是 table → ``PathConfigError``。
    刻意不缓存:文件只有几行,而按路径缓存会让同一个路径被改写后拿到旧值
    ——测试里正是这个模式,省下的解析时间换不来这个麻烦。
    """
    config_path = Path(path) if path is not None else DEFAULT_PATHS_CONFIG
    if not config_path.is_file():
        return {}

    try:
        parsed = load_toml(config_path)
    except (OSError, ValueError) as exc:
        raise PathConfigError(f"{config_path} 无法解析:{exc}") from exc

    section = parsed.get("literature")
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise PathConfigError(
            f"{config_path} 的 [literature] 必须是 table,实际是 {type(section).__name__}"
        )
    return section


def _as_root(value: str | Path) -> Path:
    """相对路径一律相对 ``PROJECT_ROOT`` 解析;绝对路径原样展开用户目录。"""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        # 死共享/不可达路径上 resolve 可能失败;当作"不在内部"处理,
        # 由调用方给出外部路径的告警。
        return False


def resolve_literature_root(
    *,
    root: str | Path | None = None,
    config_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    dotenv: Mapping[str, str] | None = None,
    warn: bool = True,
) -> Path:
    """解析精读产物根。

    优先级(高到低):显式 ``root`` → ``HYDROLITAGENT_LITERATURE_ROOT`` →
    ``configs/paths.toml`` 的 ``[literature].root`` → ``PROJECT_ROOT/outputs``。

    ``env`` / ``dotenv`` 可注入,让测试不必依赖进程真实环境(仓库根有活的 .env)。
    未注入时 ``env`` 读 ``os.environ``,``dotenv`` 补读 ``.env`` 但不写回。
    """
    if root is not None:
        # 显式参数即调用方的意图,不做外部检查。
        return _as_root(root)

    environ = os.environ if env is None else env
    file_values = read_dotenv_values() if dotenv is None else dotenv
    # os.environ 优先:同一套 override=False 语义。
    raw = environ.get(LITERATURE_ROOT_ENV) or file_values.get(LITERATURE_ROOT_ENV)
    if raw:
        # env 指向外部路径**本身就是显式 opt-in** —— 再要一个开关,而那个
        # 开关又不能提交进仓库,是自相矛盾。
        return _finalize(_as_root(raw), external_opt_in=True, warn=warn)

    section = load_paths_config(config_path)
    configured = section.get("root")
    if configured:
        if not isinstance(configured, str):
            raise PathConfigError(
                f"[literature].root 必须是字符串,实际是 {type(configured).__name__}"
            )
        resolved = _as_root(configured)
        declared = section.get("external") is True
        if not _is_within(resolved, PROJECT_ROOT) and not declared:
            raise PathConfigError(
                f"[literature].root 指向工作区外({resolved}),"
                "提交进仓库的配置不得如此;确需外部位置时必须显式写出 "
                "[literature] external = true"
            )
        return _finalize(resolved, external_opt_in=declared, warn=warn)

    return DEFAULT_LITERATURE_ROOT


def _finalize(path: Path, *, external_opt_in: bool, warn: bool) -> Path:
    """外部根的长度预算告警。是告警不是报错——短路径也可能合法地落在长根下。"""
    if not warn:
        return path
    if external_opt_in and len(str(path)) > EXTERNAL_ROOT_LENGTH_BUDGET:
        warnings.warn(
            f"产物根 {path} 长 {len(str(path))} 字符,已超过 "
            f"{EXTERNAL_ROOT_LENGTH_BUDGET} 的预算;Windows 上路径上限是 260,"
            "较深的产物子树可能写入失败",
            stacklevel=3,
        )
    return path
