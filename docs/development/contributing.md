# 贡献指南

## 开发环境

```bash
# 安装依赖（含 dev 组；workspace 成员已取消，现在等价于装根包）
uv sync --all-packages

# 确认测试通过
uv run pytest tests/test_zotero_server.py tests/test_paper_to_zotero.py -v
```

## 运行测试

```bash
# 全部测试
uv run pytest -v

# 仅 Zotero MCP Server 测试
uv run pytest tests/test_zotero_server.py -v

# 仅 paper-to-zotero 测试
uv run pytest tests/test_paper_to_zotero.py -v

# 单个测试类
uv run pytest tests/test_zotero_server.py::TestZoteroSearch -v

# 覆盖率
uv run pytest --cov=hydrolitagent/zotero --cov-report=term-missing
```

## 测试模式

所有测试使用：

- **pytest** 框架
- **unittest.mock**（MagicMock、AsyncMock、patch）模拟外部依赖
- **AAA 模式**（Arrange → Act → Assert）

### 模拟外部依赖

测试文件顶部的 stub 模式确保模块在依赖未安装时也能导入：

```python
# 在导入被测模块之前 stub 外部包
import sys
from unittest.mock import MagicMock

_pyzotero_module = MagicMock()
sys.modules["pyzotero"] = _pyzotero_module
sys.modules["pyzotero.zotero"] = _pyzotero_module.zotero

from hydrolitagent.zotero import server
```

### 测试命名

```python
class TestZoteroSearch:
    def test_search_returns_formatted_items(self, mock_zot_client, ...):
        ...

    def test_search_handles_empty_results(self, mock_zot_client, ...):
        ...

    def test_search_handles_api_error(self, mock_zot_client):
        ...
```

## 添加新 MCP 工具

向 `server.py` 添加新工具的标准步骤：

### 1. 编写工具函数

```python
@mcp.tool()
async def zotero_new_tool(param: str, limit: int = 10) -> str:
    """One-line description of what this tool does.

    Longer description of the tool's purpose, what it returns,
    and any important notes about usage.
    """
    if not param:
        return _make_error("zotero_new_tool", "param is required")
    if not _zot:
        return _make_error("zotero_new_tool", "Web API client not initialized")
    try:
        # 实现逻辑
        result = await asyncio.to_thread(_zot.some_method, param, limit=limit)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("zotero_new_tool failed: %s", e)
        return _make_error("zotero_new_tool", str(e))
```

### 2. 编写测试

在 `tests/test_zotero_server.py` 中创建新的 Test Class：

```python
class TestZoteroNewTool:
    def test_returns_expected_format(self, mock_zot_client):
        ...

    def test_missing_param_returns_error(self, mock_zot_client):
        ...

    def test_handles_api_error(self, mock_zot_client):
        ...

    def test_handles_no_client(self):
        with patch.object(server, "_zot", None):
            result_json = asyncio.run(server.zotero_new_tool(param="test"))
        result = json.loads(result_json)
        assert result["error"] is True
```

### 3. 更新文档

在 `docs/user-guide/mcp-tools.md` 中添加新工具的文档段落。

## 代码风格

- 遵循 **PEP 8**
- 所有函数签名使用 **type annotations**
- **docstring** 描述每个工具的用途、参数和返回值
- 使用 `_make_error()` 统一错误返回格式
- 使用 `_format_item()` 统一条目输出格式
- 日志使用 `logging` 模块（不用 `print()`）

## 版本号与发布

版本号**不写在 `pyproject.toml` 里**。构建后端是 `hatchling` + `hatch-vcs`，
`version` 是 dynamic 的，由 **git tag** 推导：

| 仓库状态 | 推导出的版本 |
|---|---|
| 正好在 `v0.0.1` 标签上 | `0.0.1` |
| `v0.0.1` 之后第 13 个提交 | `0.0.2.dev13` |
| 拿不到任何 tag（如源码 tarball） | `fallback-version`（当前 `0.0.0`） |

所以**不需要手工改版本号**。发版三步：

```bash
git tag v0.0.2                 # 1. 打标签
git push origin v0.0.2         # 2. 推标签（顺带推 main）
```

3. 剩下的自动完成：

```text
push tag
  → Release checks（.github/workflows/release-checks.yml）
      校验 tag 与安装版本一致（要求 tag == v<installed version>）
  → 绿了之后，Release workflow（.github/workflows/release.yml）自动创建 GitHub Release
      正文由 GitHub 依据 PR/提交生成
```

两个容易踩的点：

- **标签名必须是 `vX.Y.Z`**，且与推导出的包版本一致，否则 `Release checks` 直接失败。
- CI 里 checkout 必须 `fetch-depth: 0`。浅克隆看不到 tag，hatch-vcs 会退回
  `fallback-version`，于是 tag 与版本对不上——这个坑已经踩过并写进 workflow。

本地查看当前推导出的版本：

```bash
uv run python -c "import importlib.metadata as m; print(m.version('hydrolitagent'))"
```

> 如果读到的是旧版本号，多半是仓库根残留了 `hydrolitagent.egg-info`（setuptools 时代的产物），
> 它会盖过 venv 里的 dist-info。删掉即可。

## 构建文档站点

```bash
# 本地预览（热重载）
uv run mkdocs serve

# 构建静态站点
uv run mkdocs build

# 严格模式（检查 broken links）
uv run mkdocs build --strict
```

## 发布在线文档

在线文档地址：[Hydro AI Papers](https://iheadwater.github.io/mylibrary/)。
它只展示 `docs/` 构建出的静态网页，不运行 Zotero 或 AI 制卡服务。

### 日常更新

1. 修改 `docs/` 中的 Markdown；增加页面时，在根目录 `mkdocs.yml` 的 `nav` 中补上导航。
2. 在仓库根目录运行 `uv sync --locked`，再运行 `uv run mkdocs build --strict`。
3. 用 `uv run mkdocs serve` 本地检查排版、链接与流程图；检查完成后按 `Ctrl+C` 停止预览。
4. 按课题组约定提交修改。PR 会运行文档构建检查，但不会发布；文档相关修改进入 `main` 后自动发布。
5. 在仓库 **Actions → Documentation** 查看构建和部署结果，再打开在线文档确认新内容。

工作流监听 `docs/`、`mkdocs.yml`、依赖与自身配置的变更；其他代码变更不会触发文档发布。
如需主动重新发布，可在 **Actions → Documentation → Run workflow** 选择 `main`。
手动运行其他分支只构建、不部署。

### 仓库首次设置

- 在 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。
- 发布工作流使用 `github-pages` 环境；如果设置环境保护规则，允许 `main` 部署。
- 在仓库右侧 **About → Website** 填写 `https://iheadwater.github.io/mylibrary/`。
- `mkdocs.yml` 的 `site_url` 必须与实际站点地址一致，包括末尾 `/`。

工作流使用仓库 `uv.lock` 安装依赖，只上传 `site/` 目录；不需要添加 Zotero、DeepSeek 等业务密钥。
不要把 `site/` 或 `.venv/` 提交到 Git，它们已被忽略。

### 出错与回退

严格构建失败时，先看 **Build documentation** 的日志，修复问题后再提交；构建失败不会发布新版本。
构建通过但部署失败时，检查 Pages 发布来源、工作流权限与 `github-pages` 环境是否等待审批。
如果已发布的文档需要回退，用 `git revert <需要撤销的提交号>` 创建撤销提交并推送 `main`；
工作流会重新构建和发布。不要用强制推送删除课题组的提交历史。

## 版本管理与 GitHub Release

本项目用 **uv** 管理固定版本：`pyproject.toml` 的 `[project].version` 是唯一版本来源，
`uv.lock` 与安装环境由 uv 同步。沿用 setuptools 构建方式，不混用基于 Git tag 的动态版本。
首次 GitHub Release 从 `v0.0.1` 开始；此前文件里的 `0.1.0` 未创建对应 tag 或 Release。

### 开发下一版

先明确下一版要解决的问题、验收条件及升级类型，再实施小步修改。只选择下面的一种：

```powershell
# 小修复：例如 0.0.1 -> 0.0.2
uv version --bump patch

# 新能力：例如 0.0.1 -> 0.1.0
uv version --bump minor

# 不兼容的重大变化：例如 0.0.1 -> 1.0.0
uv version --bump major
```

这些是互斥示例，不要连续执行三条。版本选择由维护者判断；uv 负责递增版本、更新锁文件和同步环境，
不是每提交一次代码就自动升版本。`0.x` 阶段接口仍在演化，发布说明要明确兼容性变化。
需要设定精确版本时用 `uv version <版本号>`，不要手改 `uv.lock`。

### 发布步骤（在仓库根目录执行）

下面的 `0.0.1` / `v0.0.1` 是首发示例，后续必须替换为实际待发布版本。

```powershell
# 安装锁定依赖，并验收
$env:PYTHONUTF8 = "1"
uv sync --locked
uv run pytest -rs
uv run hydrolitagent cards --help
uv run python scripts/paper_validate.py --draft hydrolitagent/cards/assets/examples/subject-card-validation/draft.json --paper-input hydrolitagent/cards/assets/examples/subject-card-validation/paper-input.json --report-dir outputs/release-validation
uv run mkdocs build --strict
uv version --short

# 维护者审阅本版变更与发布说明后提交，并推送 main（或按团队约定合并 PR）
# 注意：git add 只列本次要发布的文件，不使用 git add . 混入其他人的改动。
# git add -- <本次文件列表>
# git commit -m "chore: prepare release v0.0.1"
git push origin main
```

确认 **Actions → Release checks** 的主线检查成功后，记下已经验收的完整提交 SHA。
对这个确定的提交打 tag，而不是对可能已被他人推进的远端最新主线盲目打 tag：

```powershell
# 把 <已验收提交SHA> 替换为该提交的完整 SHA
git tag -a v0.0.1 <已验收提交SHA> -m "mylibrary v0.0.1"
git push origin refs/tags/v0.0.1
```

再次确认该 tag 的 **Release checks** 成功，再创建 GitHub Release。
首发说明在 [v0.0.1 发布说明](../releases/v0.0.1.md)；后续各版新增自己的说明文件。

```powershell
gh release create v0.0.1 --repo iHeadWater/mylibrary --verify-tag --title "mylibrary v0.0.1" --notes-file docs/releases/v0.0.1.md
```

发布说明必须写清本版能力、安装入口、验收结果、跳过项与已知边界；不能把离线示例通过写成真实论文生成通过。
测试中的跳过项保留原因，不通过排除失败用例来宣称全绿。
`Release checks` 自动核对项目版本、安装版本与 tag，并运行测试、离线示例和严格文档构建。
它不替维护者选择版本号，也不自动创建 Release。

`Release checks` 在 Ubuntu / macOS / Windows 三平台跑同一套测试，Windows 使用 `pwsh`、Unix 使用 `bash`，
**不安装 Poppler** —— PDF→Markdown 由 PyMuPDF 完成，CI 另有一步显式 import 它来证明转换器可用。
三平台都使用 UTF-8 模式（`PYTHONUTF8=1`）；CI 测试步骤的 `TEMP` / `TMP` 指向 runner 标准临时目录，
避免托管用户的短路径别名与解析后的完整路径在断言中混用。原测试及业务代码不因 CI 失败而被排除或削弱。

本项目目前只发布 **GitHub tag + Release**，不上传 PyPI，不需要 `uv publish`、PyPI 密钥或 Trusted Publishing，
也不要求制作 wheel/sdist 发布附件。用户通过源码快照与 uv 使用。
已公开的 tag/Release 不通过删除重建来移动版本；发布错误时说明问题并发布修正版。
