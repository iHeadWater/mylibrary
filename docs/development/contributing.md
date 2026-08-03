# 贡献指南

## 开发环境

```bash
# 安装项目 + 开发依赖
uv pip install -e ".[dev]"

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
