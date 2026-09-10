"""Structural guards for the ``hydro-platform`` repository restructure.

These tests encode the TARGET state of the restructure, not the current state:

* the platform's code and reusable assets live under a top-level ``hydro-platform/``
  directory (``automation/``, ``templates/``, ``config/`` + ``pyproject.toml``);
* the platform's documentation moves into ``docs/hydro-platform/`` and the
  platform's own README files are dropped;
* every generated artefact (evidence packs, themes, reports, activity ledgers,
  member files) stops being tracked by git and is produced into a workspace-local
  ``.venv``-adjacent runtime instead of being committed - both the OUTCOME (test 1:
  nothing generated is tracked) and the MECHANISM (the ignore rules that keep it
  from being committed in the first place) are guarded, because the outcome check
  alone only fires after the damage is done;
* environment creation is owned by ``uv`` (``uv sync``), and the platform only
  verifies the resulting environment.

They therefore FAIL on a branch where the platform is still rooted at the repo
root. That is expected and intended: the suite is RED until the restructure lands.
Each test only inspects the working tree/``git`` state and never touches the
network, Zotero, Codex or any other external service.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

# --------------------------------------------------------------------------------------
# Constants describing the target layout
# --------------------------------------------------------------------------------------

# ``tests/test_repo_structure.py`` -> repo root is the parent of the ``tests`` directory.
REPO_ROOT = Path(__file__).resolve().parent.parent

PLATFORM_ROOT = REPO_ROOT / "hydro-platform"
PLATFORM_SRC = PLATFORM_ROOT / "automation" / "src"
DOCS_ROOT = REPO_ROOT / "docs"

# Only these tracked paths may live under ``hydro-platform/``.
ALLOWED_PLATFORM_PREFIXES = (
    "hydro-platform/automation/",
    "hydro-platform/templates/",
    "hydro-platform/config/",
)
ALLOWED_PLATFORM_FILES = ("hydro-platform/pyproject.toml",)

# Generated output: never tracked, in either the old or the new location.
FORBIDDEN_PLATFORM_PREFIXES = (
    "hydro-platform/evidence-packs/",
    "hydro-platform/themes/",
    "hydro-platform/reports/",
    "hydro-platform/activity/",
    "hydro-platform/members/",
)

# Runtime products / machine-local state that the ignore rules must cover, and the
# tracked source and reusable assets that must stay visible to git.
PLATFORM_IGNORED_PATHS = (
    "hydro-platform/evidence-packs/EV-EXAMPLE/card.md",
    "hydro-platform/themes/_registry.json",
    "hydro-platform/reports/daily/2026-09-09.json",
    "hydro-platform/activity/ledger.json",
    "hydro-platform/members/README.md",
    "hydro-platform/.runtime/tasks.json",
    "hydro-platform/.tools/poppler/Library/bin/pdfinfo.exe",
    "hydro-platform/config/config.local.json",
)

PLATFORM_NOT_IGNORED_PATHS = (
    "hydro-platform/automation/src/hydro_platform/tasks.py",
    "hydro-platform/templates/evidence-cards/_catalog.json",
    "hydro-platform/config/config.json",
    "hydro-platform/pyproject.toml",
    ".gitignore",
)

# ``str.startswith`` accepts a tuple; keep the prefix tuples in a form pytest can print.
_FORBIDDEN_PLATFORM_PREFIXES = tuple(FORBIDDEN_PLATFORM_PREFIXES)

PLATFORM_TESTS_DIR = PLATFORM_ROOT / "automation" / "tests"
REPO_TESTS_DIR = REPO_ROOT / "tests"

MIN_PLATFORM_TEST_FILES = 30

# The platform's importable package, in both Path and tracked-path (posix) form.
PLATFORM_PACKAGE_DIR = PLATFORM_SRC / "hydro_platform"
PLATFORM_PACKAGE_PREFIX = PLATFORM_PACKAGE_DIR.relative_to(REPO_ROOT).as_posix() + "/"

# Minimum amount of real platform content that must have moved for the structural
# guards below to mean anything (see ``_tracked_platform_paths`` and test 7).
MIN_PLATFORM_SOURCE_FILES = 20

PLATFORM_DOCS_DIR = DOCS_ROOT / "hydro-platform"
MIN_PLATFORM_DOC_FILES = 5

# ``deployment.py`` must not install wheels into the environment itself; ``uv`` owns it.
WHEEL_INSTALL_CALL = re.compile(
    r"\b_?(?:[a-z_]*install[a-z_]*wheel[a-z_]*|_wheel[a-z_]*)\s*\(",
    re.IGNORECASE,
)
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
    """Tracked paths under ``hydro-platform/``, with a non-vacuity precondition.

    Every assertion in tests 1 and 3 is phrased as "no tracked path under
    ``hydro-platform/`` looks like X", which is *vacuously* true whenever the
    platform is not actually there. The precondition therefore demands that the
    platform's real source tree has moved - at least
    ``MIN_PLATFORM_SOURCE_FILES`` tracked ``.py`` files under
    ``hydro-platform/automation/src/hydro_platform/`` - and NOT merely that a path
    with the right directory name exists.

    This specificity is deliberate and must not be loosened: a merge that lands
    only ``hydro-platform/pyproject.toml`` (packaging metadata), or an empty
    ``hydro-platform/`` skeleton, would otherwise satisfy a weak precondition and
    flip these guards green while the platform's code and its generated products
    are still sitting at the repo root - i.e. while the restructure has not
    happened at all.
    """

    tracked = _git_ls_files()
    platform_paths = [path for path in tracked if path.startswith("hydro-platform/")]

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
        "mean anything - a directory of that name, or a lone pyproject.toml, is not "
        "enough. Found under hydro-platform/:\n  "
        + ("\n  ".join(sorted(platform_paths)) or "(nothing)")
    )
    return platform_paths


def _dig(data: object, *keys: str) -> object:
    """Walk nested JSON keys, failing with a readable message when one is missing."""

    current = data
    for index, key in enumerate(keys):
        assert isinstance(current, dict), (
            f"expected an object at '{'.'.join(keys[:index])}' in hydro-platform config, "
            f"found {type(current).__name__}"
        )
        assert key in current, (
            f"hydro-platform config is missing the required key '{'.'.join(keys[: index + 1])}'"
        )
        current = current[key]
    return current


def _load_platform_config() -> dict:
    """Load ``<repo root>/hydro-platform/config/config.json``."""

    config_path = PLATFORM_ROOT / "config" / "config.json"
    assert config_path.is_file(), (
        f"expected the hydro-platform config at {config_path}, but it does not exist.\n"
        "The platform's configuration must move with the platform into "
        f"{PLATFORM_ROOT / 'config'}."
    )
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        pytest.fail(f"{config_path} is not valid JSON: {exc}")


def _resolve_against_platform(raw: str) -> Path:
    """Resolve a config path: absolute stays as-is, relative is anchored at hydro-platform/."""

    path = Path(raw)
    if not path.is_absolute():
        path = PLATFORM_ROOT / path
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

    Under ``hydro-platform/`` the only tracked paths may be the platform's reusable
    assets (``automation/``, ``templates/``, ``config/``) plus the single file
    ``hydro-platform/pyproject.toml``. In particular nothing from
    ``evidence-packs/``, ``themes/``, ``reports/``, ``activity/`` or ``members/``
    may be tracked - those are runtime products written into the workspace.

    Non-vacuity: the precondition requires the platform's real source tree to be
    tracked under ``hydro-platform/`` (at least ``MIN_PLATFORM_SOURCE_FILES``
    ``.py`` files in its package) - the platform must have actually moved, not
    merely a directory name existing - otherwise the assertions below are
    vacuously true while the platform still sits at the repo root.
    """

    platform_paths = _tracked_platform_paths()

    offenders = [
        path for path in platform_paths if path.startswith(_FORBIDDEN_PLATFORM_PREFIXES)
    ]
    assert not offenders, (
        "generated output is still tracked by git under hydro-platform/ "
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
        "unexpected tracked path under hydro-platform/ - only "
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

    Documentation lives in ``docs/hydro-platform/``; zero tracked files whose
    basename is ``README.md`` (in any case variant) may live under
    ``hydro-platform/``.

    Non-vacuity: the precondition requires the platform's real source tree to be
    tracked under ``hydro-platform/`` (at least ``MIN_PLATFORM_SOURCE_FILES``
    ``.py`` files in its package) - the platform must have actually moved, not
    merely a directory name existing - otherwise the assertion below is vacuously
    true while the platform still sits at the repo root.
    """

    platform_paths = _tracked_platform_paths()

    offenders = sorted(
        path for path in platform_paths if Path(path).name.lower() == "readme.md"
    )
    assert not offenders, (
        "README files are still tracked under hydro-platform/ - platform docs belong in "
        f"{DOCS_ROOT / 'hydro-platform'}:\n  " + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------------------
# 4. CLI default config path
# --------------------------------------------------------------------------------------


def test_config_path_contract() -> None:
    """Requirement: the CLI resolves its default config to ``hydro-platform/config/config.json``.

    Importing the package from ``hydro-platform/automation/src`` must expose
    ``hydro_platform.cli.DEFAULT_CONFIG_PATH`` pointing at the platform's own
    ``config/config.json`` (which moves with the platform), not at the repo-root
    ``config/`` directory.
    """

    assert PLATFORM_SRC.is_dir(), (
        f"the platform source tree must live at {PLATFORM_SRC}, but that directory "
        "does not exist"
    )

    sys.path.insert(0, str(PLATFORM_SRC))
    try:
        try:
            from hydro_platform.cli import DEFAULT_CONFIG_PATH  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001 - reported as a test failure below
            pytest.fail(
                f"cannot import 'hydro_platform.cli' from {PLATFORM_SRC}: {exc!r}.\n"
                "The importable package must live under "
                "hydro-platform/automation/src so that the CLI (and this contract) "
                "resolve inside the platform directory."
            )
    finally:
        try:
            sys.path.remove(str(PLATFORM_SRC))
        except ValueError:  # pragma: no cover - defensive
            pass

    expected = (PLATFORM_ROOT / "config" / "config.json").resolve()

    actual = Path(DEFAULT_CONFIG_PATH)
    if not actual.is_absolute():
        actual = REPO_ROOT / actual
    actual = actual.resolve()

    assert actual == expected, (
        f"hydro_platform.cli.DEFAULT_CONFIG_PATH must resolve to {expected}, "
        f"got {actual} (raw value: {DEFAULT_CONFIG_PATH!r})"
    )


# --------------------------------------------------------------------------------------
# 5. environment directory lives in the workspace .venv
# --------------------------------------------------------------------------------------


def test_environment_dir_in_workspace_venv() -> None:
    """Requirement: config points the runtime environment at ``<repo root>/.venv``.

    ``deployment.environment_dir`` must resolve (relative to ``hydro-platform/``)
    to ``<repo root>/.venv``, and
    ``card_generator.pdf_direct_trial.python_executable`` must live inside that
    same ``.venv`` - no environment is created outside the workspace.
    """

    config = _load_platform_config()

    raw_environment_dir = _dig(config, "deployment", "environment_dir")
    assert isinstance(raw_environment_dir, str), (
        "deployment.environment_dir must be a string, got "
        f"{type(raw_environment_dir).__name__}"
    )

    expected_environment_dir = (REPO_ROOT / ".venv").resolve()
    environment_dir = _resolve_against_platform(raw_environment_dir)
    assert environment_dir == expected_environment_dir, (
        "deployment.environment_dir must resolve to "
        f"{expected_environment_dir} (relative to {PLATFORM_ROOT}), got "
        f"{environment_dir} from raw value {raw_environment_dir!r}"
    )

    raw_python_executable = _dig(
        config, "card_generator", "pdf_direct_trial", "python_executable"
    )
    assert isinstance(raw_python_executable, str), (
        "card_generator.pdf_direct_trial.python_executable must be a string, got "
        f"{type(raw_python_executable).__name__}"
    )

    python_executable = _resolve_against_platform(raw_python_executable)
    assert _is_within(python_executable, expected_environment_dir), (
        "card_generator.pdf_direct_trial.python_executable must resolve under "
        f"{expected_environment_dir}, got {python_executable} from raw value "
        f"{raw_python_executable!r}"
    )


# --------------------------------------------------------------------------------------
# 6. uv owns the environment
# --------------------------------------------------------------------------------------


def test_bootstrap_defers_to_uv() -> None:
    """Requirement: ``uv`` owns the environment; the platform only verifies it.

    ``hydro_platform/deployment.py`` must no longer contain a wheel-install code
    path that writes into the environment directory (no ``"install"`` subprocess
    invocation carrying wheel material, no ``_wheel(``/wheel-install helper), and
    its bootstrap entrypoint must tell the operator to run ``uv sync``.
    """

    deployment_py = PLATFORM_SRC / "hydro_platform" / "deployment.py"
    assert deployment_py.is_file(), (
        f"expected the deployment module at {deployment_py}, but it does not exist.\n"
        "The platform code (including its deployment/bootstrap module) must live under "
        f"{PLATFORM_ROOT}."
    )

    source = deployment_py.read_text(encoding="utf-8")
    lines = source.splitlines()

    install_lines = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(lines, start=1)
        if QUOTED_INSTALL_ARG.search(line) and WHEEL_MATERIAL.search(line)
    ]
    assert not install_lines, (
        "deployment.py still installs wheels itself - uv owns the environment and the "
        "platform must only verify it. Offending 'install' + wheel invocation(s):\n  "
        + "\n  ".join(install_lines)
    )

    wheel_helper = WHEEL_INSTALL_CALL.search(source)
    assert wheel_helper is None, (
        "deployment.py still defines/calls a wheel-install helper "
        f"({wheel_helper.group(0)!r} at offset {wheel_helper.start()}); environment "
        "creation must be delegated to `uv sync`"
    )

    assert UV_SYNC_HINT in source, (
        "the bootstrap entrypoint must tell the operator to run "
        f"`{UV_SYNC_HINT}` - the literal {UV_SYNC_HINT!r} does not appear anywhere in "
        f"{deployment_py}"
    )


# --------------------------------------------------------------------------------------
# 7. docs links stay inside docs/
# --------------------------------------------------------------------------------------


def test_docs_have_no_escaping_links() -> None:
    """Requirement: documentation links never escape ``docs/``.

    Every ``](../...)`` markdown link inside ``<repo root>/docs/`` must still
    resolve to a path under ``<repo root>/docs/`` after being resolved relative to
    the file that contains it. External ``http(s)://`` links and ``#anchor`` links
    are fine.

    The precondition pins down that the platform's OWN docs have arrived
    (``docs/hydro-platform/`` with at least ``MIN_PLATFORM_DOC_FILES`` markdown
    files) rather than accepting any markdown anywhere under ``docs/``. That
    specificity is deliberate and must not be loosened: the repo already has an
    unrelated ``docs/`` tree, so a weaker precondition is *vacuously* satisfied
    before the restructure and would keep this guard green throughout the whole
    refactor. The scan itself stays whole-tree, so inherited docs are covered too.
    """

    platform_docs_dir = DOCS_ROOT / "hydro-platform"
    assert platform_docs_dir.is_dir(), (
        f"the platform's documentation must live at {platform_docs_dir}, but that "
        "directory does not exist - the platform docs have not moved"
    )

    platform_markdown_files = sorted(platform_docs_dir.rglob("*.md"))
    assert len(platform_markdown_files) >= MIN_PLATFORM_DOC_FILES, (
        f"only {len(platform_markdown_files)} markdown file(s) found under "
        f"{platform_docs_dir} (at least {MIN_PLATFORM_DOC_FILES} are required).\nThe "
        "rest of docs/ belongs to the wider project and would satisfy a weaker "
        "precondition vacuously - the platform's own docs must actually be there."
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


def test_pytest_collects_both_suites() -> None:
    """Requirement: one ``pytest`` run collects the repo suite and the platform suite.

    ``hydro-platform/automation/tests`` must exist with at least 30 ``test_*.py``
    files, ``tests/`` must hold at least one test module besides this file, and the
    repo-root ``pyproject.toml`` (when present) must declare
    ``[tool.pytest.ini_options].testpaths`` covering both directories.
    """

    assert PLATFORM_TESTS_DIR.is_dir(), (
        f"the platform test suite must live at {PLATFORM_TESTS_DIR}, but that directory "
        "does not exist"
    )
    platform_test_files = sorted(PLATFORM_TESTS_DIR.glob("test_*.py"))
    assert len(platform_test_files) >= MIN_PLATFORM_TEST_FILES, (
        f"expected at least {MIN_PLATFORM_TEST_FILES} test_*.py files under "
        f"{PLATFORM_TESTS_DIR}, found {len(platform_test_files)}"
    )

    assert REPO_TESTS_DIR.is_dir(), f"{REPO_TESTS_DIR} does not exist"
    this_file = Path(__file__).resolve()
    repo_test_files = [
        path
        for path in sorted(REPO_TESTS_DIR.glob("test_*.py"))
        if path.resolve() != this_file
    ]
    assert repo_test_files, (
        f"{REPO_TESTS_DIR} must contain at least one test_*.py file besides "
        "test_repo_structure.py; the repo-level suite would otherwise be empty"
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
        f"{pyproject_path} must declare a [tool.pytest.ini_options] section so that a "
        "single `pytest` run covers both suites"
    )

    testpaths = ini_options.get("testpaths")
    assert testpaths, (
        f"{pyproject_path} must declare [tool.pytest.ini_options].testpaths with both "
        f"'tests' and '{PLATFORM_TESTS_DIR.relative_to(REPO_ROOT).as_posix()}'"
    )

    normalized = {str(entry).replace("\\", "/").strip("/").removeprefix("./") for entry in testpaths}
    expected_entries = (
        "tests",
        PLATFORM_TESTS_DIR.relative_to(REPO_ROOT).as_posix(),
    )
    missing = [entry for entry in expected_entries if entry not in normalized]
    assert not missing, (
        f"pyproject.toml [tool.pytest.ini_options].testpaths is missing {missing}; "
        f"it must include both suites (found {sorted(normalized)})"
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
    this is meaningful before ``hydro-platform/`` is even created. It is evaluated
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
