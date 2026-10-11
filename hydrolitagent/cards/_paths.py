"""包内路径的**单一锚点**。

为什么单独一个模块：搬迁前，包内有 7 处用 `Path(__file__).resolve().parents[N]` 推算
平台根与资产目录，而且层级各不相同（`parents[2]`/`[3]`/`[4]`，取决于文件嵌几层）。
文件一挪，这些**不会报错**，只会指向错误的位置 —— 等到 `load_config` 找不到配置、
模板目录为空时才暴露。

改成从这一个模块取常量后，**文件在包内怎么挪都不会算错**。
新增路径引用一律从这里取，不要再写 `parents[N]`。
"""

from __future__ import annotations

from pathlib import Path

# 本包目录：<repo>/hydrolitagent/cards/
PACKAGE_DIR = Path(__file__).resolve().parent

# 包内只读资产树：templates/ prompts/ schemas/ examples/ config/
ASSETS_DIR = PACKAGE_DIR / "assets"

# 仓库根：<repo>
REPO_ROOT = PACKAGE_DIR.parents[1]

# 常用资产子目录
TEMPLATES_DIR = ASSETS_DIR / "templates"
PROMPTS_DIR = ASSETS_DIR / "prompts"
SCHEMAS_DIR = ASSETS_DIR / "schemas"
EXAMPLES_DIR = ASSETS_DIR / "examples"
CONFIG_DIR = ASSETS_DIR / "config"

# 默认总配置
DEFAULT_CONFIG_PATH = CONFIG_DIR / "config.json"

__all__ = [
    "PACKAGE_DIR",
    "ASSETS_DIR",
    "REPO_ROOT",
    "TEMPLATES_DIR",
    "PROMPTS_DIR",
    "SCHEMAS_DIR",
    "EXAMPLES_DIR",
    "CONFIG_DIR",
    "DEFAULT_CONFIG_PATH",
]
