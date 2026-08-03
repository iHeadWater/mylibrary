# 安装配置

## 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) 包管理器
- Zotero 桌面版（至少运行过一次，生成本地数据库）

## 安装项目

```bash
git clone git@github.com:OuyangWenyu/hydro_ai_papers.git
cd hydro_ai_papers
uv pip install -e .
```

## 配置 Zotero

### 1. 创建 Zotero API Key

访问 [zotero.org/settings/keys](https://www.zotero.org/settings/keys)：

1. 点击 **Create New Private Key**
2. 勾选 **Allow library access** 和 **Allow notes access**
3. 记录生成的 Key 和页面顶部显示的 **User ID**（数字）

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入以下 Zotero 相关变量：

```bash
# Zotero Web API（必需 — 读写文献库）
ZOTERO_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxx
ZOTERO_LIBRARY_ID=1234567
ZOTERO_LIBRARY_TYPE=user

# Zotero Local API（可选 — PDF 全文检索，需 Zotero Desktop 运行）
ZOTERO_LOCAL_API_URL=http://host.docker.internal:23119
```

| 变量 | 必需 | 说明 |
|------|------|------|
| `ZOTERO_API_KEY` | 是 | Zotero Web API 密钥 |
| `ZOTERO_LIBRARY_ID` | 是 | Zotero User ID（数字） |
| `ZOTERO_LIBRARY_TYPE` | 否 | `user`（默认）或 `group` |
| `ZOTERO_LOCAL_API_URL` | 否 | 本地全文检索 API 地址 |

### 3. 配置 Zotero 附件路径（用于论文入库）

论文入库脚本使用 Zotero 的 `attachments:` scheme 解析 PDF 路径。需要在 Zotero 桌面版中设置 **Linked Attachment Base Directory**：

1. Zotero → Preferences → Advanced → Files and Folders
2. 设置 **Linked Attachment Base Directory** 为你的 PDF 存储根目录

这样 `attachments:paper.pdf` 会自动解析为 `<base_dir>/paper.pdf`，在不同操作系统中保持路径一致。

## 配置论文入库（可选）

论文入库流水线需要额外的 Zotero 配置文件。创建 `~/.config/zot/config.toml`：

```toml
[zotero]
library_id = "1234567"
api_key = "xxxxxxxxxxxxxxxxxxxxxxxx"
```

可通过 `ZOTERO_CONFIG_PATH` 环境变量覆盖此路径。

## 验证安装

```bash
# 确认依赖安装成功
uv run python -c "import pyzotero; print('pyzotero OK')"
uv run python -c "from hydrolitagent.zotero import server; print('server OK')"

# 运行测试
uv run pytest tests/test_zotero_server.py -v
```
