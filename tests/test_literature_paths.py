"""精读产物根的解析与可配置性。

分三组:
- 解析优先级(环境变量 → configs/paths.toml → 内置默认);
- 模块常量必须可 monkeypatch —— zotero_notebooklm 的三个测试依赖这一点;
- CLI 的 ``paths`` 子命令。

解析类测试一律显式注入 ``env=`` / ``dotenv=``,不依赖进程真实环境:仓库根有活的
``.env``,读到它会让断言随开发者的机器而变。
"""

from __future__ import annotations

import json
import os

import pytest

from hydrolitagent import cli
from hydrolitagent._config import (
    LITERATURE_ROOT_ENV,
    PathConfigError,
    read_dotenv_values,
    resolve_literature_root,
)
from hydrolitagent.literature import _paths as paths_mod


def _config(tmp_path, body: str):
    """写一份临时 paths.toml,返回它的路径。"""
    path = tmp_path / "paths.toml"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 解析优先级
# ---------------------------------------------------------------------------


def test_env_var_wins_over_committed_config(tmp_path):
    """环境变量压过仓库里的默认配置 —— 每台机器用自己的落点。"""
    config = _config(tmp_path, '[literature]\nroot = "outputs"\nexternal = false\n')
    cloud = tmp_path / "cloud"

    resolved = resolve_literature_root(
        config_path=config, env={LITERATURE_ROOT_ENV: str(cloud)}, dotenv={}
    )

    assert resolved == cloud


def test_committed_config_used_when_env_absent(tmp_path):
    """没有环境变量时用配置文件的值,相对路径相对仓库根解析。"""
    config = _config(tmp_path, '[literature]\nroot = "sync/products"\n')

    resolved = resolve_literature_root(config_path=config, env={}, dotenv={})

    assert resolved == paths_mod.PROJECT_ROOT / "sync" / "products"


def test_defaults_to_repo_outputs_when_unconfigured(tmp_path):
    """配置文件缺失时回落到内置默认 —— 裸检出必须还能跑。"""
    resolved = resolve_literature_root(
        config_path=tmp_path / "missing.toml", env={}, dotenv={}
    )

    assert resolved == paths_mod.PROJECT_ROOT / "outputs"


def test_external_root_in_config_file_requires_explicit_opt_in(tmp_path):
    """提交进仓库的配置不得指向仓库外 —— 它会改变所有用户的默认落点。"""
    # A real absolute path outside the repository on every platform: a
    # hard-coded drive letter is only absolute on Windows.
    elsewhere = tmp_path.parent / "elsewhere-external"
    config = _config(tmp_path, f'[literature]\nroot = "{elsewhere.as_posix()}"\n')

    with pytest.raises(PathConfigError, match="external"):
        resolve_literature_root(config_path=config, env={}, dotenv={})


def test_external_root_allowed_when_declared_in_config_file(tmp_path):
    """显式写了 external = true 就放行 —— 意图是写明的。"""
    elsewhere = tmp_path.parent / "elsewhere-external"
    config = _config(
        tmp_path,
        f'[literature]\nroot = "{elsewhere.as_posix()}"\nexternal = true\n',
    )

    resolved = resolve_literature_root(config_path=config, env={}, dotenv={})

    assert resolved.as_posix().endswith("elsewhere-external")


def test_external_root_via_env_var_needs_no_second_switch(tmp_path):
    """环境变量指向仓库外本身就是显式 opt-in。

    再要一个开关是自相矛盾的:那个开关写在配置文件里就不可能提交进仓库。
    """
    cloud = tmp_path / "outside" / "cloud"

    resolved = resolve_literature_root(
        config_path=tmp_path / "missing.toml",
        env={LITERATURE_ROOT_ENV: str(cloud)},
        dotenv={},
    )

    assert resolved == cloud


def test_env_var_in_env_file_is_honoured(tmp_path):
    """`.env` 里的产物根必须生效。

    回归守卫:literature/ 下的模块(download_pdf / bilibili_upload /
    zotero_notebooklm)都不调用 load_dotenv,只读 os.environ 会让写在
    .env 里的配置静默失效。
    """
    from_dotenv = tmp_path / "from-dotenv"

    resolved = resolve_literature_root(
        config_path=tmp_path / "missing.toml",
        env={},
        dotenv={LITERATURE_ROOT_ENV: str(from_dotenv)},
    )

    assert resolved == from_dotenv


def test_os_environ_beats_env_file(tmp_path):
    """同一套 override=False 语义:真实环境优先于 .env。"""
    resolved = resolve_literature_root(
        config_path=tmp_path / "missing.toml",
        env={LITERATURE_ROOT_ENV: str(tmp_path / "from-environ")},
        dotenv={LITERATURE_ROOT_ENV: str(tmp_path / "from-dotenv")},
    )

    assert resolved == tmp_path / "from-environ"


def test_explicit_argument_beats_everything(tmp_path):
    """显式参数是调用方的直接意图。"""
    resolved = resolve_literature_root(
        root=tmp_path / "explicit",
        config_path=_config(tmp_path, '[literature]\nroot = "outputs"\n'),
        env={LITERATURE_ROOT_ENV: str(tmp_path / "from-environ")},
        dotenv={},
    )

    assert resolved == tmp_path / "explicit"


def test_malformed_toml_raises_path_config_error(tmp_path):
    """畸形 TOML 要报明确的错,而不是抛裸的 TOMLDecodeError。"""
    config = _config(tmp_path, '[literature\nroot = "outputs"\n')

    with pytest.raises(PathConfigError):
        resolve_literature_root(config_path=config, env={}, dotenv={})


def test_non_string_root_raises_path_config_error(tmp_path):
    """root 写成了数字是配置错误,不是"没配置"。"""
    config = _config(tmp_path, "[literature]\nroot = 5\n")

    with pytest.raises(PathConfigError, match="root"):
        resolve_literature_root(config_path=config, env={}, dotenv={})


def test_missing_literature_table_falls_back_to_default(tmp_path):
    """有配置文件但没有 [literature] 表 —— 按未配置处理,不报错。"""
    config = _config(tmp_path, "[something_else]\nkey = 1\n")

    resolved = resolve_literature_root(config_path=config, env={}, dotenv={})

    assert resolved == paths_mod.PROJECT_ROOT / "outputs"


def test_shipped_config_resolves_to_repo_outputs():
    """仓库里那份真实配置,解析结果必须是 <repo>/outputs。

    防漂移:configs/paths.toml 被改了而代码默认值没跟上时,这条会红。
    """
    resolved = resolve_literature_root(env={}, dotenv={})

    assert resolved == paths_mod.PROJECT_ROOT / "outputs"


# ---------------------------------------------------------------------------
# read_dotenv_values:解析本身
# ---------------------------------------------------------------------------


def test_read_dotenv_values_does_not_mutate_environ(tmp_path):
    """读取 .env 不得有副作用 —— 它只返回一个 dict。"""
    env_file = tmp_path / ".env"
    env_file.write_text("SOME_ROOT=/tmp/x\n", encoding="utf-8")
    before = dict(os.environ)

    values = read_dotenv_values(env_file)

    assert values["SOME_ROOT"] == "/tmp/x"
    assert dict(os.environ) == before


def test_read_dotenv_values_strips_inline_comments(tmp_path):
    """`KEY=value  # 注释` 里注释不是值的一部分。

    cli.py 里原先那份手写解析不做这件事,会把注释一起当成路径。
    """
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PLAIN=/data/out   # 这是注释\n"
        'QUOTED="/data/has # hash"\n'
        "HASHY=/data/a#b\n",
        encoding="utf-8",
    )

    values = read_dotenv_values(env_file)

    assert values["PLAIN"] == "/data/out"
    # 引号里的 # 是值的一部分
    assert values["QUOTED"] == "/data/has # hash"
    # 前面没有空白的 # 也是值的一部分 —— 路径里可以有 #
    assert values["HASHY"] == "/data/a#b"


def test_read_dotenv_values_handles_missing_file(tmp_path):
    """`.env` 是可选的,不存在就是空。"""
    assert read_dotenv_values(tmp_path / "nope.env") == {}


# ---------------------------------------------------------------------------
# 模块常量必须是 Path 且可 monkeypatch
# ---------------------------------------------------------------------------


def test_output_root_is_a_module_level_path():
    """zotero_notebooklm 的三个测试依赖这个形状。

    它若变成函数,`monkeypatch.setattr(zn, "OUTPUT_ROOT", tmp_path)` 就废了。
    """
    assert isinstance(paths_mod.OUTPUT_ROOT, type(paths_mod.PROJECT_ROOT))
    assert paths_mod.OUTPUT_ROOT.is_absolute()


def test_subdirectory_constants_derive_from_output_root():
    """子目录常量必须都挂在产物根下 —— 换根时它们一起走。"""
    for name in ("WEEKLY_REVIEW_DIR", "PAPERS_DIR", "BILIBILI_DIR", "ZOTERO_DIR"):
        path = getattr(paths_mod, name)
        assert path.parent == paths_mod.OUTPUT_ROOT, f"{name} 不在产物根下"


def test_zotero_notebooklm_output_dir_is_still_patchable(monkeypatch, tmp_path):
    """三个现有测试的写法,这里再钉一遍:patch OUTPUT_ROOT 必须改得动落点。"""
    import datetime as dt

    from hydrolitagent.literature import zotero_notebooklm as zn

    monkeypatch.setattr(zn, "OUTPUT_ROOT", tmp_path)
    paths = zn.make_paths(dt.date(2026, 9, 10))

    assert paths.output_dir == tmp_path / "zotero" / "2026-09-10"


def test_bilibili_output_dir_is_still_patchable(monkeypatch, tmp_path):
    """bilibili_upload 同理:OUTPUT_DIR 是模块属性,不是内联字面量。"""
    from hydrolitagent.literature import bilibili_upload as bu

    monkeypatch.setattr(bu, "OUTPUT_DIR", tmp_path)

    assert bu.OUTPUT_DIR == tmp_path


def test_refresh_updates_every_constant(monkeypatch, tmp_path):
    """refresh() 要就地更新全部常量,而不是只更新根。"""
    import importlib

    monkeypatch.setenv(LITERATURE_ROOT_ENV, str(tmp_path / "refreshed"))
    importlib.reload(paths_mod)
    try:
        assert paths_mod.OUTPUT_ROOT == tmp_path / "refreshed"
        assert paths_mod.PAPERS_DIR == tmp_path / "refreshed" / "papers"
        assert paths_mod.WEEKLY_REVIEW_DIR == tmp_path / "refreshed" / "weekly-review"
    finally:
        # 归还一个干净的模块,免得污染同进程里的其他测试。
        monkeypatch.delenv(LITERATURE_ROOT_ENV, raising=False)
        importlib.reload(paths_mod)


# ---------------------------------------------------------------------------
# download_pdf 的旧名兼容
# ---------------------------------------------------------------------------


def test_mylibrary_pdf_root_still_wins_over_product_root(monkeypatch, tmp_path):
    """旧名 MYLIBRARY_PDF_ROOT 对 papers/ 的优先级仍在 —— 不要静默改掉。"""
    from hydrolitagent.literature.download_pdf import default_pdf_dir

    monkeypatch.setenv("MYLIBRARY_PDF_ROOT", str(tmp_path))

    assert default_pdf_dir(root=tmp_path / "cloud") == tmp_path


def test_default_pdf_dir_accepts_explicit_root(monkeypatch, tmp_path):
    """没有旧名变量时,显式 root 决定落点。"""
    from hydrolitagent.literature.download_pdf import default_pdf_dir

    monkeypatch.delenv("MYLIBRARY_PDF_ROOT", raising=False)

    assert default_pdf_dir(root=tmp_path / "cloud") == tmp_path / "cloud"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_paths_payload_has_every_subdirectory():
    """paths 子命令要报出根 + 四个子目录 —— skill 靠它解析实际落点。"""
    payload = cli._paths_payload()

    for key in ("project_root", "literature_root", "weekly_review", "papers", "bilibili", "zotero"):
        assert key in payload, f"paths payload 缺少 {key}"


def test_paths_subcommand_emits_json(capsys):
    """--json 是机器可读的那一半,必须是合法 JSON。"""
    args = cli.build_parser().parse_args(["paths", "--json"])

    cli._print_paths(as_json=args.json)

    payload = json.loads(capsys.readouterr().out)
    assert payload["literature_root"]
    assert payload["weekly_review"].endswith("weekly-review")


def test_paths_subcommand_prints_human_readable(capsys):
    """不带 --json 时给人看。"""
    args = cli.build_parser().parse_args(["paths"])

    cli._print_paths(as_json=args.json)

    out = capsys.readouterr().out
    assert "产物根" in out
    assert "周报产物" in out
