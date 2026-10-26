"""Structural guards for the layer boundaries of ``hydrolitagent/cards``.

The cards package is being decoupled from any single model provider. Two rules
make that decoupling checkable without running anything:

* ``domain/`` may not depend on ``adapters`` / ``application`` /
  ``card_generators`` and may not import ``subprocess`` -- the domain must stay
  pure data and rules;
* the shared layers (``domain/``, ``ports/``, ``application/``) may not name a
  concrete provider or a Poppler executable. The only exemption is the
  historical on-disk method string ``claude_pdf_read``, which must keep its
  exact spelling so old drafts stay readable.

These tests read source files and ASTs only. They never import the modules under
test and never touch Zotero, a model CLI or the network.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDS_DIR = REPO_ROOT / "hydrolitagent" / "cards"

# Import targets the domain layer is not allowed to reach.
FORBIDDEN_DOMAIN_IMPORTS = (
    "hydrolitagent.cards.adapters",
    "hydrolitagent.cards.application",
    "hydrolitagent.cards.card_generators",
)
# ``subprocess`` is an executable-discovery concern, i.e. an adapter concern.
FORBIDDEN_DOMAIN_ROOTS = ("subprocess",)

PROVIDER_WORDS = ("codex", "claude", "openai")

# ``source_access.py`` owns the on-disk contract. ``claude_pdf_read`` is a
# historical artifact method and ``CLAUDE_PDF_READ`` is the constant holding it;
# both must be spelled that way. Everything else in the shared layers is
# provider-free. The exemption is per-file and per-literal on purpose -- a blank
# "this file is exempt" rule would let new provider branches slip in.
PROVIDER_WORD_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "domain/source_access.py": ("CLAUDE_PDF_READ", "claude_pdf_read"),
}

# Layers that must stay provider-neutral, relative to ``hydrolitagent/cards``.
SHARED_LAYERS = ("domain", "ports", "application")


def _python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def _module_name(path: Path) -> str:
    """Dotted module name of ``path`` (``__init__`` collapses onto its package)."""

    parts = list(path.relative_to(REPO_ROOT).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package_of(path: Path) -> list[str]:
    """Package parts used as the anchor for relative imports in ``path``."""

    parts = _module_name(path).split(".")
    return parts if path.name == "__init__.py" else parts[:-1]


def _imported_targets(path: Path, node: ast.AST) -> list[str]:
    """Absolute module names an ``import`` statement can resolve to."""

    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []
    module = node.module or ""
    if node.level:
        package = _package_of(path)
        keep = len(package) - (node.level - 1)
        prefix = package[:keep] if keep > 0 else []
        resolved = ".".join(prefix + ([module] if module else []))
    else:
        resolved = module
    targets = [resolved] if resolved else []
    # ``from X import y`` may import the submodule ``X.y``; both are candidates.
    targets.extend(
        f"{resolved}.{alias.name}" for alias in node.names
        if resolved and alias.name != "*"
    )
    return targets


def _is_within(target: str, prefix: str) -> bool:
    return target == prefix or target.startswith(prefix + ".")


def _imports_of(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        for target in _imported_targets(path, node):
            found.append((getattr(node, "lineno", 0), target))
    return found


# --------------------------------------------------------------------------------------
# 1. domain/ never imports adapters, application, card_generators or subprocess
# --------------------------------------------------------------------------------------


def test_domain_does_not_import_outer_layers() -> None:
    """The domain must stay at the bottom of the dependency graph.

    Non-vacuity: the domain package must exist and hold real modules, otherwise
    the assertion below is trivially true.
    """

    domain_dir = CARDS_DIR / "domain"
    assert domain_dir.is_dir(), f"domain 层不存在：{domain_dir}"
    files = _python_files(domain_dir)
    assert len(files) >= 3, (
        f"domain 层只有 {len(files)} 个模块；没有真实模块时这条守卫没有意义"
    )

    offenders: list[str] = []
    for path in files:
        for lineno, target in _imports_of(path):
            if any(_is_within(target, name) for name in FORBIDDEN_DOMAIN_IMPORTS) or any(
                _is_within(target, root) for root in FORBIDDEN_DOMAIN_ROOTS
            ):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno} -> {target}"
                )

    assert not offenders, (
        "domain 层反向依赖了外层或执行层模块；domain 只能包含纯规则与数据：\n  "
        + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------------------
# 1a. workflow modules may build adapters lazily, never at module level
# --------------------------------------------------------------------------------------


def _top_level_imports(path: Path) -> list[tuple[int, str]]:
    """Imports executed at import time only (module body, not function bodies)."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for target in _imported_targets(path, node):
                found.append((getattr(node, "lineno", 0), target))
    return found


@pytest.mark.parametrize("relative", ["themes.py", "theme_pool_runner.py"])
def test_theme_modules_do_not_import_adapters_at_module_level(relative: str) -> None:
    """The theme workflows take adapter factories; concrete adapters are lazy.

    A function-level import is allowed (it is the stage-1 transitional seam),
    but a module-level one makes the whole cards package import a provider as
    soon as themes are touched -- the exact coupling this migration removes.
    """

    path = CARDS_DIR / relative
    assert path.is_file(), f"缺少模块：{path}"

    offenders = [
        f"{relative}:{lineno} -> {target}"
        for lineno, target in _top_level_imports(path)
        if "codex" in target.lower() or "claude" in target.lower()
    ]
    assert not offenders, (
        "主题流程在模块层 import 了具体 provider；应改为接收 factory 并在函数内惰性构造：\n  "
        + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------------------
# 1b. application/ orchestrates ports; it must not reach into concrete adapters
# --------------------------------------------------------------------------------------


def test_application_does_not_import_adapters() -> None:
    """The orchestration layer may depend on ports and domain, never on adapters.

    ``application/`` does not exist in stage 1, so the guard skips visibly. It
    activates automatically once the layer is created, which is the point: the
    rule has to exist before the code that could break it.
    """

    app_dir = CARDS_DIR / "application"
    if not app_dir.is_dir():
        pytest.skip("application 层尚未建立（阶段 1）；建立后本守卫自动生效")

    offenders: list[str] = []
    for path in _python_files(app_dir):
        for lineno, target in _imports_of(path):
            if _is_within(target, "hydrolitagent.cards.adapters"):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno} -> {target}"
                )

    assert not offenders, (
        "application 层直接依赖了 adapters；应改为依赖 ports 并由 composition 注入：\n  "
        + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------------------
# 2. shared layers never name a provider or a Poppler executable
# --------------------------------------------------------------------------------------


def _provider_word_hits(path: Path, text: str) -> list[tuple[int, str]]:
    relative = path.relative_to(CARDS_DIR).as_posix()
    for literal in PROVIDER_WORD_ALLOWLIST.get(relative, ()):
        text = text.replace(literal, "")
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        lowered = line.lower()
        for word in PROVIDER_WORDS:
            if word in lowered:
                hits.append((lineno, f"{word}: {line.strip()}"))
    return hits


def test_shared_layers_are_provider_free() -> None:
    """No provider name and no Poppler executable may appear in shared layers.

    ``ports`` and ``application`` are skipped until they exist, so this guard
    turns itself on as the migration adds them instead of silently covering
    nothing.

    The allowlist is literal-scoped (see ``PROVIDER_WORD_ALLOWLIST``): the
    historical method string ``claude_pdf_read`` stays readable, but any other
    provider wording in that same file would still fail.
    """

    checked: list[Path] = []
    offenders: list[str] = []
    for layer in SHARED_LAYERS:
        directory = CARDS_DIR / layer
        if not directory.is_dir():
            continue
        for path in _python_files(directory):
            checked.append(path)
            text = path.read_text(encoding="utf-8")
            for lineno, hit in _provider_word_hits(path, text):
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno} {hit}")

    assert checked, "没有找到任何共享层模块；这条守卫会在空集上通过"
    assert not offenders, (
        "共享层出现了 provider 名称或 Poppler 工具名；它们只应存在于 adapters/：\n  "
        + "\n  ".join(offenders)
    )


def test_provider_allowlist_is_still_needed() -> None:
    """Keep the exemption honest: it must describe a literal that still exists.

    If ``claude_pdf_read`` ever moves out of ``source_access.py`` (or is spelled
    differently), the allowlist entry becomes dead weight and should be removed
    rather than quietly widening the rule above.
    """

    for relative, literals in PROVIDER_WORD_ALLOWLIST.items():
        path = CARDS_DIR / relative
        assert path.is_file(), f"白名单指向的文件不存在：{relative}"
        text = path.read_text(encoding="utf-8")
        for literal in literals:
            assert literal in text, (
                f"{relative} 已不再包含 {literal!r}；请删除这条白名单而不是留着放宽规则"
            )


# --------------------------------------------------------------------------------------
# 3. stage 6a: the removed PDF-direct-read helpers must not come back
# --------------------------------------------------------------------------------------

# Assembled from fragments on purpose: this guard must not itself reintroduce the
# literals it forbids, or a repository-wide grep would flag the guard.
LEGACY_PDF_NAMES = (
    "pdf" + "info",
    "pdf" + "toppm",
    "pdf" + "totext",
    "pdf_" + "sandbox",
    "codex_" + "local_pdf",
)
# Historical reads under ``legacy/`` stay allowed; they decode old artifacts.
LEGACY_PDF_ALLOWED_PREFIXES = ("hydrolitagent/cards/legacy/",)


def test_cards_package_does_not_reference_removed_pdf_helpers() -> None:
    """The platform converts PDFs with Python; it must not shell out to PDF tools.

    ``legacy/`` is exempt because it only decodes artifacts written by the old
    pipeline. Any new hit means the deleted direct-read path came back.
    """

    offenders: list[str] = []
    scanned = 0
    for path in sorted(CARDS_DIR.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if any(relative.startswith(prefix) for prefix in LEGACY_PDF_ALLOWED_PREFIXES):
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8").lower()
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name in LEGACY_PDF_NAMES:
                if name in line:
                    offenders.append(f"{relative}:{lineno} {name}")

    assert scanned, "没有扫描到任何 cards 模块；这条守卫会在空集上通过"
    assert not offenders, (
        "hydrolitagent/cards 仍引用已删除的 PDF 直读工具：\n  " + "\n  ".join(offenders)
    )


if __name__ == "__main__":  # pragma: no cover - manual invocation convenience
    raise SystemExit(pytest.main([__file__]))
