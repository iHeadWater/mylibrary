"""Path helpers for the literature CLI subpackage.

``PROJECT_ROOT`` 只在这里 re-export —— 层级算术本身归 ``hydrolitagent/_config.py``，
那个文件是仓库里唯一知道"往上是仓库根"的地方。

产物根是可配置的(优先级见 ``resolve_literature_root``),默认
``<repo>/outputs``。要指到 OneDrive / Google Drive / 坚果云等同步目录,
设环境变量 ``HYDROLITAGENT_LITERATURE_ROOT``,或改 ``configs/paths.toml``。
用 ``uv run hydrolitagent paths`` 查看实际解析结果。
"""

from pathlib import Path

from hydrolitagent._config import PROJECT_ROOT, resolve_literature_root as _resolve

__all__ = [
    "PROJECT_ROOT",
    "OUTPUT_ROOT",
    "WEEKLY_REVIEW_DIR",
    "PAPERS_DIR",
    "BILIBILI_DIR",
    "ZOTERO_DIR",
    "resolve_literature_root",
    "refresh",
]


def resolve_literature_root() -> Path:
    """按 环境变量 → ``configs/paths.toml`` → ``PROJECT_ROOT/outputs`` 解析产物根。

    额外补读一次 ``.env`` 但不写回 ``os.environ``:``literature/`` 下的模块
    (``download_pdf`` / ``bilibili_upload`` / ``zotero_notebooklm``)都不调用
    ``load_dotenv``,只认 ``os.environ`` 会让写在 ``.env`` 里的配置静默失效。
    """
    return _resolve(dotenv=None)


# 模块级常量,导入时求值。**必须保持是 Path 且是这个模块的属性**:
# ``zotero_notebooklm`` 用 ``from ... import OUTPUT_ROOT`` 绑定自己的模块全局,
# 三个测试靠 ``monkeypatch.setattr(zn, "OUTPUT_ROOT", ...)`` 改落点。
# 换成函数会让那条路子作废。
OUTPUT_ROOT = resolve_literature_root()

# 产物根下各子目录。刻意不是配置项 —— 这几个名字是与 skill、文档的契约,
# 配错了只会得到"配了个没人认识的名字"这种故障,而用户零收益。
WEEKLY_REVIEW_DIR = OUTPUT_ROOT / "weekly-review"
PAPERS_DIR = OUTPUT_ROOT / "papers"
BILIBILI_DIR = OUTPUT_ROOT / "bilibili-upload"
ZOTERO_DIR = OUTPUT_ROOT / "zotero"


def refresh() -> Path:
    """重新解析产物根,就地更新本模块的全部常量,返回新的根。

    给"导入之后才设环境变量"的长驻进程用。测试改落点请用
    ``monkeypatch.setattr``,不必依赖这个函数。
    """
    global OUTPUT_ROOT, WEEKLY_REVIEW_DIR, PAPERS_DIR, BILIBILI_DIR, ZOTERO_DIR
    OUTPUT_ROOT = resolve_literature_root()
    WEEKLY_REVIEW_DIR = OUTPUT_ROOT / "weekly-review"
    PAPERS_DIR = OUTPUT_ROOT / "papers"
    BILIBILI_DIR = OUTPUT_ROOT / "bilibili-upload"
    ZOTERO_DIR = OUTPUT_ROOT / "zotero"
    return OUTPUT_ROOT
