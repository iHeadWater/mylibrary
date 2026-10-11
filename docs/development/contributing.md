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
