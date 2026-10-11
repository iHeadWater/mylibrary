"""Structural guards for the ``hydro-platform`` repository restructure.

These tests encode the TARGET state of the restructure, not the current state:

* the platform's code and reusable assets live inside ``hydrolitagent/cards/``
  (modules + ``assets/``) -- the top-level ``hydro-platform/`` directory is gone;
* the platform's documentation is organised by audience under ``docs/``
  (``user-guide/cards/``、``development/platform/``)
  and the platform's own README files are dropped;
* every generated artefact (evidence packs, themes, reports, activity ledgers,
  member files) stops being tracked by git and is produced into a workspace-local
  ``.venv``-adjacent runtime instead of being committed - both the OUTCOME (test 1:
  nothing generated is tracked) and the MECHANISM (the ignore rules that keep it
  from being committed in the first place) are guarded, because the outcome check
  alone only fires after the damage is done;

They therefore FAIL on a branch where the platform is still rooted at the repo
root. That is expected and intended: the suite is RED until the restructure lands.
Each test only inspects the working tree/``git`` state and never touches the
network, Zotero, Codex or any other external service.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

# --------------------------------------------------------------------------------------
# Constants describing the target layout
# --------------------------------------------------------------------------------------

# ``tests/test_repo_structure.py`` -> repo root is the parent of the ``tests`` directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
# ── 文献卡与主题卡平台（原 hydro-platform，已并入 hydrolitagent/cards）──
# 代码与只读资产在包内；运行产物在仓库根（见路径契约测试）。
CARDS_PACKAGE_DIR = REPO_ROOT / "hydrolitagent" / "cards"
CARDS_ASSETS_DIR = CARDS_PACKAGE_DIR / "assets"
DOCS_ROOT = REPO_ROOT / "docs"

# 包根。旧「平台根」概念（一个独立的 hydro-platform/ 项目目录）已随合并消失，
# 因此 PLATFORM_ROOT 指向包本身，而**运行产物根**是仓库根。
PLATFORM_ROOT = CARDS_PACKAGE_DIR

# 包内允许被跟踪的路径前缀。包内除了代码就是 assets/，其余一律不该入库。
ALLOWED_PLATFORM_PREFIXES = (
    "hydrolitagent/cards/",
)
ALLOWED_PLATFORM_FILES = ()

# 运行产物：一律落仓库根，且必须被 ignore 规则覆盖。
FORBIDDEN_PLATFORM_PREFIXES = (
    "evidence-packs/",
    "themes/",
    "reports/",
    "activity/",
    "members/",
    ".runtime/",
    ".tools/",
)

# 必须被 ignore 命中的运行产物/本机状态，与必须**保持入库**的代码与资产。
PLATFORM_IGNORED_PATHS = (
    "evidence-packs/EV-EXAMPLE/card.md",
    "themes/_registry.json",
    "reports/daily/2026-09-09.json",
    "activity/ledger.json",
    "members/README.md",
    ".runtime/tasks.json",
    ".tools/poppler/Library/bin/pdfinfo.exe",
    "hydrolitagent/cards/assets/config/config.local.json",
)

PLATFORM_NOT_IGNORED_PATHS = (
    "hydrolitagent/cards/tasks.py",
    "hydrolitagent/cards/assets/templates/evidence-cards/_catalog.json",
    # 负向控制：`themes/` 之类的运行产物规则不得锚错层级而吞掉只读资产。
    "hydrolitagent/cards/assets/templates/themes/pool-discovery.md",
    "hydrolitagent/cards/assets/config/config.json",
    ".gitignore",
)

# --------------------------------------------------------------------------------------
# 人读那一支(原王新宇线)的产物:默认落在仓库根,落点由 paths.artifact_root 决定
# --------------------------------------------------------------------------------------

ARTIFACT_ROOT_DIRS = ("证据卡", "主题", "运行记录", "文献链接")
ARTIFACT_IGNORED_PATHS = tuple(f"{name}/示例.md" for name in ARTIFACT_ROOT_DIRS)

REQUIRED_RESEARCH_SKILLS = (
    "skills/hydrology-evidence-cards/SKILL.md",
    "skills/hydrology-theme-synthesis/SKILL.md",
)

RESEARCH_DOCS_DIRS = (
    "主题模板",
)

_FORBIDDEN_PLATFORM_PREFIXES = tuple(FORBIDDEN_PLATFORM_PREFIXES)

# 两套测试已在本次合并中并为一套，统一在仓库根 tests/。
PLATFORM_TESTS_DIR = REPO_ROOT / "tests"
REPO_TESTS_DIR = REPO_ROOT / "tests"
MIN_PLATFORM_TEST_FILES = 20

PLATFORM_PACKAGE_DIR = CARDS_PACKAGE_DIR
PLATFORM_PACKAGE_PREFIX = "hydrolitagent/cards/"
MIN_PLATFORM_SOURCE_FILES = 20

# 平台文档已按读者拆到三处（原 docs/hydro-platform/ 随 10-10-docs-restructure 消失）。
# 三个目录必须都在，且合计篇数不得少于下界 —— 守卫防的是「搬丢了」。
#
# 21 → 20（2026-10-11，任务 10-11-cards-docs-altitude）：本轮**主动**把
# `single-paper-quickstart.md`（623 行分步教程）的公共前提抽到 `getting-started/installation.md`、
# 其余删除；删的是页不是内容，公共前提那一页还在（只是换到了 getting-started/）。
# 这是有意的结构调整，不是搬迁丢失 —— 因此改数字，**不减断言**。
PLATFORM_DOC_DIRS = (
    DOCS_ROOT / "user-guide" / "cards",
    DOCS_ROOT / "development" / "platform",
)
MIN_PLATFORM_DOC_FILES = 20

QUOTED_INSTALL_ARG = re.compile(r"""["']install["']""")
WHEEL_MATERIAL = re.compile(
    r"\.whl\b|--require-hashes|--no-index|--find-links|\bwheels?\b",
    re.IGNORECASE,
)
UV_SYNC_HINT = "uv sync"

MARKDOWN_LINK = re.compile(r"\]\(\s*([^)\s]+)")


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``git`` inside the repo root and return the completed process."""

    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _git_ls_files(*pathspecs: str) -> list[str]:
    """Return the tracked paths of the repository (optionally filtered by pathspec)."""

    result = _run_git("ls-files", *pathspecs)
    assert result.returncode == 0, (
        f"`git ls-files {' '.join(pathspecs)}` failed in {REPO_ROOT} "
        f"(exit {result.returncode}): {result.stderr.strip()}"
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _tracked_platform_paths() -> list[str]:
    """Tracked paths under ``hydrolitagent/cards/``, with a non-vacuity precondition.

    Every assertion in tests 1 and 3 is phrased as "no tracked path under
    ``hydrolitagent/cards/`` looks like X", which is *vacuously* true whenever the
    platform is not actually there. The precondition therefore demands that the
    platform's real source tree has moved - at least
    ``MIN_PLATFORM_SOURCE_FILES`` tracked ``.py`` files under
    ``hydrolitagent/cards/`` - and NOT merely that a path
    with the right directory name exists.

    This specificity is deliberate and must not be loosened: a merge that lands
    only a lone packaging file, or an empty
    ``hydrolitagent/cards/`` skeleton, would otherwise satisfy a weak precondition and
    flip these guards green while the platform's code and its generated products
    are still sitting at the repo root - i.e. while the restructure has not
    happened at all.
    """

    tracked = _git_ls_files()
    platform_paths = [
        path for path in tracked if path.startswith("hydrolitagent/cards/")
    ]

    source_files = [
        path
        for path in platform_paths
        if path.startswith(PLATFORM_PACKAGE_PREFIX) and path.endswith(".py")
    ]
    assert len(source_files) >= MIN_PLATFORM_SOURCE_FILES, (
        "non-vacuity precondition failed: `git ls-files` reports "
        f"{len(source_files)} tracked .py file(s) under '{PLATFORM_PACKAGE_PREFIX}' "
        f"(at least {MIN_PLATFORM_SOURCE_FILES} are required).\nThe platform's actual "
        f"source tree must have moved to {PLATFORM_ROOT} before the assertions below "
        "mean anything - a directory of that name, or a lone packaging file, is not "
        "enough. Found under hydrolitagent/cards/:\n  "
        + ("\n  ".join(sorted(platform_paths)) or "(nothing)")
    )
    return platform_paths


def _dig(data: object, *keys: str) -> object:
    """Walk nested JSON keys, failing with a readable message when one is missing."""

    current = data
    for index, key in enumerate(keys):
        assert isinstance(current, dict), (
            f"expected an object at '{'.'.join(keys[:index])}' in the cards config, "
            f"found {type(current).__name__}"
        )
        assert key in current, (
            f"the cards config is missing the required key '{'.'.join(keys[: index + 1])}'"
        )
        current = current[key]
    return current


def _load_platform_config() -> dict:
    """Load the shipped total config at ``hydrolitagent/cards/assets/config/config.json``."""

    config_path = CARDS_ASSETS_DIR / "config" / "config.json"
    assert config_path.is_file(), (
        f"expected the package config at {config_path}, but it does not exist.\n"
        "The platform's configuration must travel with the package inside its "
        f"assets dir: {CARDS_ASSETS_DIR / 'config'}."
    )
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        pytest.fail(f"{config_path} is not valid JSON: {exc}")


def _resolve_against_platform(raw: str) -> Path:
    """Resolve a config path: absolute stays as-is, relative is anchored at ``paths.project_root``.

    ``config.json`` 的 23 个路径字段全部相对 ``paths.project_root`` 解析，而
    ``project_root`` 现在是**仓库根**（不再是原来的 ``hydro-platform/``），因此相对
    路径的锚点是 ``REPO_ROOT``。
    """

    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def _is_within(path: Path, parent: Path) -> bool:
    """True when ``path`` is ``parent`` itself or lives underneath it."""

    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_ignored(path: str) -> bool:
    """Ask git whether ``path`` matches an ignore rule (rules only, index ignored).

    ``--no-index`` is deliberate: without it git exempts *tracked* paths from
    ``check-ignore`` (exit 1 even when a rule matches), which would make the
    "source code must not be swallowed" negative control a no-op for exactly the
    files it has to protect. The flag makes this a pure evaluation of the ignore
    rules, which is the mechanism under test; whether the file is also tracked is
    covered by test 1.
    """

    result = _run_git("check-ignore", "-q", "--no-index", "--", path)
    assert result.returncode in (0, 1), (
        f"`git check-ignore -- {path}` failed (exit {result.returncode}): "
        f"{result.stderr.strip()}"
    )
    return result.returncode == 0


# --------------------------------------------------------------------------------------
# 1. generated artefacts are untracked
# --------------------------------------------------------------------------------------


def test_repo_no_generated_artifacts_tracked() -> None:
    """Requirement: generated output must never be committed.

    Inside the ``hydrolitagent/cards/`` package the only tracked paths may be the
    platform's code (``*.py``) and its reusable assets (``assets/``). In particular
    nothing from ``evidence-packs/``, ``themes/``, ``reports/``, ``activity/`` or
    ``members/`` may be tracked - those are runtime products written into the repo
    root.

    Non-vacuity: the precondition requires the platform's real source tree to be
    tracked under ``hydrolitagent/cards/`` (at least ``MIN_PLATFORM_SOURCE_FILES``
    ``.py`` files in its package) - the platform must have actually moved, not
    merely a directory name existing - otherwise the assertions below are
    vacuously true while the platform still sits at the repo root.
    """

    platform_paths = _tracked_platform_paths()

    # 运行产物根已从 hydro-platform/ 移到仓库根，而 platform_paths 全是
    # ``hydrolitagent/cards/`` 前缀，永远匹配不到根级的运行产物目录。若仍对
    # platform_paths 判这里，这条 OUTCOME 守卫会退化成恒真 —— 因此改对**全部**
    # 被跟踪路径判：产物一旦被误提交，无论落在哪都必须立刻暴露。
    offenders = [
        path for path in _git_ls_files() if path.startswith(_FORBIDDEN_PLATFORM_PREFIXES)
    ]
    assert not offenders, (
        "generated output is still tracked by git "
        "(these paths must be produced at runtime into an ignored workspace dir):\n  "
        + "\n  ".join(sorted(offenders))
    )

    unexpected = [
        path
        for path in platform_paths
        if path not in ALLOWED_PLATFORM_FILES
        and not path.startswith(ALLOWED_PLATFORM_PREFIXES)
    ]
    assert not unexpected, (
        "unexpected tracked path under hydrolitagent/cards/ - only "
        f"{ALLOWED_PLATFORM_PREFIXES} and {ALLOWED_PLATFORM_FILES} are allowed:\n  "
        + "\n  ".join(sorted(unexpected))
    )


# --------------------------------------------------------------------------------------
# 2. a single .gitignore
# --------------------------------------------------------------------------------------


def test_repo_single_gitignore() -> None:
    """Requirement: exactly one ``.gitignore`` is tracked, and it sits at the repo root.

    The restructure consolidates ignore rules: the platform must not carry its own
    nested ``.gitignore`` files after the move.
    """

    tracked = _git_ls_files()
    gitignores = sorted(path for path in tracked if Path(path).name == ".gitignore")

    assert len(gitignores) == 1, (
        f"expected exactly 1 tracked .gitignore in the repository, found "
        f"{len(gitignores)}:\n  " + "\n  ".join(gitignores)
    )
    assert gitignores == [".gitignore"], (
        f"the single tracked .gitignore must be at the repo root ('.gitignore'), "
        f"found {gitignores[0]!r}"
    )


# --------------------------------------------------------------------------------------
# 3. no README inside the platform
# --------------------------------------------------------------------------------------


def test_repo_no_platform_readme() -> None:
    """Requirement: the platform ships no README files of its own.

    Documentation lives under ``docs/``（平台文档已归入 ``user-guide/cards/`` 与
    ``development/platform/``）；zero tracked files whose basename is ``README.md``
    (in any case variant) may live under the ``hydrolitagent/cards/`` package tree.

    Non-vacuity: the precondition requires the platform's real source tree to be
    tracked under ``hydrolitagent/cards/`` (at least ``MIN_PLATFORM_SOURCE_FILES``
    ``.py`` files in its package) - the platform must have actually moved, not
    merely a directory name existing - otherwise the assertion below is vacuously
    true while the platform still sits at the repo root.
    """

    platform_paths = _tracked_platform_paths()

    offenders = sorted(
        path for path in platform_paths if Path(path).name.lower() == "readme.md"
    )
    assert not offenders, (
        "README files are still tracked under hydrolitagent/cards/ - platform docs belong in "
        f"{DOCS_ROOT / 'user-guide' / 'cards'} 或 {DOCS_ROOT / 'development' / 'platform'}"
        ":\n  " + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------------------
# 4. CLI default config path
# --------------------------------------------------------------------------------------


def test_config_path_contract() -> None:
    """Requirement: the CLI resolves its default config to the package's own assets.

    ``hydrolitagent.cards.cli.DEFAULT_CONFIG_PATH`` must point at
    ``hydrolitagent/cards/assets/config/config.json`` —— 配置随包走，不指向仓库根的
    ``config/`` 目录（那里是工具链线的配置）。
    """

    from hydrolitagent.cards.cli import DEFAULT_CONFIG_PATH

    expected = (CARDS_ASSETS_DIR / "config" / "config.json").resolve()

    actual = Path(DEFAULT_CONFIG_PATH)
    if not actual.is_absolute():
        actual = REPO_ROOT / actual
    actual = actual.resolve()

    assert actual == expected, (
        f"hydrolitagent.cards.cli.DEFAULT_CONFIG_PATH must resolve to {expected}, "
        f"got {actual} (raw value: {DEFAULT_CONFIG_PATH!r})"
    )

# --------------------------------------------------------------------------------------
# 5. environment directory lives in the workspace .venv
# --------------------------------------------------------------------------------------
def test_docs_have_no_escaping_links() -> None:
    """Requirement: documentation links never escape ``docs/``.

    Every ``](../...)`` markdown link inside ``<repo root>/docs/`` must still
    resolve to a path under ``<repo root>/docs/`` after being resolved relative to
    the file that contains it. External ``http(s)://`` links and ``#anchor`` links
    are fine.

    The precondition pins down that the platform's OWN docs have arrived
    (``PLATFORM_DOC_DIRS`` holding at least ``MIN_PLATFORM_DOC_FILES`` markdown
    files in total) rather than accepting any markdown anywhere under ``docs/``. That
    specificity is deliberate and must not be loosened: the repo already has an
    unrelated ``docs/`` tree, so a weaker precondition is *vacuously* satisfied
    before the restructure and would keep this guard green throughout the whole
    refactor. The scan itself stays whole-tree, so inherited docs are covered too.
    """

    platform_markdown_files: list[Path] = []
    for platform_docs_dir in PLATFORM_DOC_DIRS:
        assert platform_docs_dir.is_dir(), (
            f"the platform's documentation must live at {platform_docs_dir}, but that "
            "directory does not exist - the platform docs have not moved"
        )
        platform_markdown_files.extend(sorted(platform_docs_dir.rglob("*.md")))
    assert len(platform_markdown_files) >= MIN_PLATFORM_DOC_FILES, (
        f"only {len(platform_markdown_files)} markdown file(s) found across "
        f"{[str(d.relative_to(REPO_ROOT)) for d in PLATFORM_DOC_DIRS]} (at least "
        f"{MIN_PLATFORM_DOC_FILES} are required).\nThe rest of docs/ belongs to the "
        "wider project and would satisfy a weaker precondition vacuously - the "
        "platform's own docs must actually be there."
    )

    markdown_files = sorted(DOCS_ROOT.rglob("*.md"))

    docs_root_resolved = DOCS_ROOT.resolve()
    offenders: list[str] = []

    for markdown_file in markdown_files:
        text = markdown_file.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            target = match.group(1).strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1].strip()
            if not target.startswith("../"):
                continue
            path_part = target.split("#", 1)[0].split("?", 1)[0]
            if not path_part:
                continue
            resolved = (markdown_file.parent / path_part).resolve()
            if not _is_within(resolved, docs_root_resolved):
                offenders.append(
                    f"{markdown_file.relative_to(REPO_ROOT).as_posix()} -> {target} "
                    f"(resolves to {resolved})"
                )

    assert not offenders, (
        "markdown links escape the docs/ directory:\n  " + "\n  ".join(sorted(offenders))
    )


# --------------------------------------------------------------------------------------
# 8. pytest collects both suites
# --------------------------------------------------------------------------------------


def test_pytest_collects_the_merged_suite() -> None:
    """Requirement: one ``pytest`` run collects the merged suite.

    本次合并把平台测试从 ``hydro-platform/automation/tests/`` 并入仓库根 ``tests/``。
    该目录必须至少有 ``MIN_PLATFORM_TEST_FILES`` 个 ``test_*.py``，且仓库根
    ``pyproject.toml``（存在时）的 ``testpaths`` 必须**恰好**覆盖 ``tests``。

    非空性：只留一个占位文件也算通过的话，这个断言就没有意义了。
    """

    assert PLATFORM_TESTS_DIR.is_dir(), (
        f"合并后的测试套件必须在 {PLATFORM_TESTS_DIR}，但该目录不存在"
    )
    test_files = sorted(PLATFORM_TESTS_DIR.glob("test_*.py"))
    assert len(test_files) >= MIN_PLATFORM_TEST_FILES, (
        f"{PLATFORM_TESTS_DIR} 下至少应有 {MIN_PLATFORM_TEST_FILES} 个 test_*.py，"
        f"实际 {len(test_files)} 个"
    )

    assert not (REPO_ROOT / "hydro-platform").is_dir(), (
        "两套测试已合并到 tests/；hydro-platform/ 不应再存在"
    )

    pyproject_path = REPO_ROOT / "pyproject.toml"
    if not pyproject_path.is_file():
        return
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover - defensive
        pytest.fail(f"{pyproject_path} is not valid TOML: {exc}")
    ini_options = pyproject.get("tool", {}).get("pytest", {}).get("ini_options")
    assert ini_options is not None, (
        f"{pyproject_path} must declare a [tool.pytest.ini_options] section"
    )
    testpaths = ini_options.get("testpaths")
    assert testpaths, f"{pyproject_path} must declare testpaths"
    normalized = sorted(
        str(e).replace("\\", "/").strip("/").removeprefix("./") for e in testpaths
    )
    assert normalized == ["tests"], (
        f"两套已合并，testpaths 应为 ['tests']，实际 {normalized}"
    )

# --------------------------------------------------------------------------------------
# 9. the ignore rules themselves (the mechanism behind test 1)
# --------------------------------------------------------------------------------------


def test_platform_output_dirs_are_ignored() -> None:
    """Requirement: ignore rules must cover the platform's runtime products.

    This guards the MECHANISM (the ignore rules) while
    ``test_repo_no_generated_artifacts_tracked`` guards the OUTCOME ("nothing
    generated is tracked"). Both are needed: the outcome check only fires after a
    product has already been committed - too late - so without this test the rules
    could be deleted and the suite would stay green until damage was done.

    ``git check-ignore`` also decides on paths that do not exist on disk yet, so
    this is meaningful before the cards package tree is even created. It is evaluated
    with ``--no-index`` (pure rule evaluation), see ``_is_ignored``.

    Positive cases: evidence packs, themes, reports, activity ledgers, member
    files, runtime state, local tool installs and the machine-local config must all
    be ignored. Negative control: the platform's source code, templates, committed
    config and pyproject - and the root ``.gitignore`` itself, which must stay
    tracked - must NOT be ignored, so an over-broad rule cannot silently swallow
    them.
    """

    not_ignored = [path for path in PLATFORM_IGNORED_PATHS if not _is_ignored(path)]
    assert not not_ignored, (
        "these platform runtime paths are NOT covered by any git ignore rule and "
        "could therefore be committed by accident:\n  " + "\n  ".join(not_ignored)
    )

    wrongly_ignored = [path for path in PLATFORM_NOT_IGNORED_PATHS if _is_ignored(path)]
    assert not wrongly_ignored, (
        "these tracked source/asset paths ARE matched by an ignore rule - the rules "
        "are too broad and would swallow real code or the repository's own "
        ".gitignore:\n  " + "\n  ".join(wrongly_ignored)
    )


# --------------------------------------------------------------------------------------
# 10. 人读那一支的产物:默认位置不入库,且规则必须覆盖它
# --------------------------------------------------------------------------------------


def test_research_workflow_artifacts_are_ignored_and_untracked() -> None:
    """要求:人读那一支(原王新宇线)的产物默认不入库,且 ignore 规则必须覆盖默认位置。

    落点本身由 ``paths.artifact_root`` 决定(默认仓库根,可指向共享盘),
    所以这里只守卫**默认位置**:与平台产物同一原则,分两处:
    - OUTCOME:四个默认产物目录下不得有任何被跟踪的文件;
    - MECHANISM:默认位置必须被 ignore 规则命中——否则规则被删掉也要等到
      产物已经被提交才会暴露。

    非空性:合并必须真的发生过,否则下面的断言会在空集上通过。因此同时断言
    两个科研 skill 与中文规范目录确实存在、确实被跟踪、且**没有**被 ignore。
    最后一项也是负向控制:防止过宽的规则(例如整目录 ``docs/``)误吞随合并
    一起搬进来的规范文档。
    """

    tracked_artifacts = _git_ls_files(*ARTIFACT_ROOT_DIRS)
    assert not tracked_artifacts, (
        "科研产物默认位置仍在被 git 跟踪——它们是运行产物,应只存在于本地或共享盘"
        "(落点由 paths.artifact_root 决定):\n  " + "\n  ".join(sorted(tracked_artifacts))
    )

    not_ignored = [path for path in ARTIFACT_IGNORED_PATHS if not _is_ignored(path)]
    assert not not_ignored, (
        "这些科研产物默认路径没有任何 ignore 规则覆盖,可能被误提交;"
        "若产物根指向仓库外,规则无副作用,但默认位置必须仍然受控:\n  "
        + "\n  ".join(not_ignored)
    )

    tracked = set(_git_ls_files("skills", "docs"))

    for path in REQUIRED_RESEARCH_SKILLS:
        assert (REPO_ROOT / path).is_file(), (
            f"缺少 {path}——说明两分支合并没有发生,本测试会在空集上通过"
        )
        assert path in tracked, f"{path} 存在但未被 git 跟踪"
        assert not _is_ignored(path), (
            f"{path} 被 ignore 规则命中——规则过宽,会吞掉 skill 源码"
        )

    for name in RESEARCH_DOCS_DIRS:
        rel = f"docs/user-guide/cards/{name}"
        assert (REPO_ROOT / rel).is_dir(), f"缺少随合并搬入的规范目录 {rel}"
        assert not _is_ignored(f"{rel}/示例.md"), (
            f"ignore 规则命中 {rel}/ ——规则过宽,会吞掉随合并搬入的规范文档"
        )


# --------------------------------------------------------------------------------------
# 11. 精读产物根:可配置,但**默认**位置必须仍受 ignore 规则控制、且不入库
# --------------------------------------------------------------------------------------


LITERATURE_ROOT_SAMPLE = "outputs/weekly-review/2026-08-04/cards/sample.md"
PATHS_CONFIG_REL = "configs/paths.toml"
LITERATURE_CONFIG = REPO_ROOT / PATHS_CONFIG_REL

# 凭据绝不能进这个文件 —— 它是要随仓库分发的。
SECRET_KEY_RE = re.compile(r"api[_-]?key|secret|token|password|passwd", re.IGNORECASE)

# 曾经写成单数 `output/` 的三份 prompt 文本。它们的单数是错的:没有代码创建
# 那个目录。归一成复数后在这里做负向控制,防止改回去。
PLURAL_ROOT_SKILLS = (
    "skills/weekly-review/SKILL.md",
    "skills/weekly-review/agents/openai.yaml",
    "skills/bilibili-upload/SKILL.md",
)


def test_literature_output_root_is_configurable_ignored_and_untracked() -> None:
    """要求:精读产物根可配置,但**默认**落点必须仍受 ignore 规则控制、且不入库。

    与科研产物守卫(见上一条)同一原则,分两处:
    - MECHANISM:默认位置必须被 ignore 规则命中 —— 规则被删掉就要立刻暴露,
      而不是等到产物已经被提交进仓库;
    - OUTCOME:默认位置下不得有任何被跟踪的文件。

    非空性:同时要求承载配置的文件确实存在、确实被跟踪、且**没**被 ignore。
    否则"配置面已落地"这句话在配置文件缺失或不被分发时会平凡为真。

    最后断言提交进仓库的那份配置是**安全的默认值**:它会被所有用户继承,
    指向仓库外就不是默认值而是缺陷。
    """

    # ── MECHANISM ──
    assert _is_ignored(LITERATURE_ROOT_SAMPLE), (
        "精读产物的默认位置没有任何 ignore 规则覆盖,可能被误提交;"
        f"规则应命中 {LITERATURE_ROOT_SAMPLE}"
    )

    # ── OUTCOME ──
    tracked = _git_ls_files("outputs")
    assert not tracked, (
        "outputs/ 下仍有被跟踪的文件 —— 精读产物是运行产物,应只存在于本地或共享盘:\n  "
        + "\n  ".join(sorted(tracked))
    )

    # ── 非空性:配置面本身必须落地且随仓库分发 ──
    assert LITERATURE_CONFIG.is_file(), (
        f"{PATHS_CONFIG_REL} 不存在 —— 配置面没有落地,上面的断言会在空集上为真"
    )
    assert PATHS_CONFIG_REL in _git_ls_files("configs"), (
        f"{PATHS_CONFIG_REL} 没有被 git 跟踪 —— 它必须随仓库分发,"
        "否则每个用户都拿不到默认值"
    )
    assert not _is_ignored(PATHS_CONFIG_REL), (
        f"{PATHS_CONFIG_REL} 被 ignore 规则命中 —— 它必须随仓库分发"
    )

    # ── 提交的配置必须是安全的默认值 ──
    shipped = tomllib.loads(LITERATURE_CONFIG.read_text(encoding="utf-8"))["literature"]
    assert shipped["external"] is False, (
        "提交进仓库的 paths.toml 不得指向工作区外 —— 它会让所有用户的产物落到同一个外部位置"
    )
    root = Path(shipped["root"])
    assert not root.is_absolute(), "提交的 root 必须是相对路径"
    assert root == Path("outputs"), (
        "提交的默认 root 必须与 ignore 规则覆盖的位置一致,否则默认产物会入库"
    )
    leaked = [key for key in shipped if SECRET_KEY_RE.search(key)]
    assert not leaked, f"{PATHS_CONFIG_REL} 里出现疑似凭据键: {leaked}"

    # ── 防漂移:代码默认值必须与提交的配置一致 ──
    from hydrolitagent._config import resolve_literature_root

    assert resolve_literature_root(env={}, dotenv={}) == REPO_ROOT / "outputs", (
        "代码解析出的默认产物根与 configs/paths.toml 不一致 —— 同一个事实只能有一个答案"
    )


def test_skill_literals_use_the_plural_outputs_root() -> None:
    """负向控制:22 处单数 ``output/`` 已归一为 ``outputs/``,防止改回去。

    ``output/`` 从来都是错的:没有代码创建它,``_paths.OUTPUT_ROOT`` 是
    ``outputs/``,且多数文档写的就是复数。这三份是 prompt 文本,改回去不会有
    测试以外的任何东西报警 —— 所以要在这里钉住。
    """

    for rel in PLURAL_ROOT_SKILLS:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "output/weekly-review" not in text, (
            f"{rel} 又出现了单数 output/ —— 它会让 agent 写到一个仓库里不存在的目录"
        )
        assert "outputs/weekly-review" in text, (
            f"{rel} 缺少复数形式的默认字面量 —— 未配置的检出需要它作为回退锚点"
        )
