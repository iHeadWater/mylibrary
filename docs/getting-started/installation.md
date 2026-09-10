# 安装配置

## 环境要求

- Python **3.12–3.14**（`requires-python = ">=3.12,<3.15"`；`docker/Dockerfile` 用 `python:3.12-slim`）
- [uv](https://docs.astral.sh/uv/) 包管理器
- Zotero 桌面版（至少运行过一次，生成本地数据库）

## 安装项目

```bash
git clone git@github.com:OuyangWenyu/mylibrary.git
cd mylibrary
uv sync --all-packages
```

> **本仓库是 uv workspace，含两个成员**：`hydrolitagent`（根包）与 `hydro-platform`。二者共享同一个 `.venv` 和同一个 `uv.lock`。
>
> 必须用 `uv sync --all-packages` —— 裸 `uv sync` 只装根包的依赖，`uv run hydro-platform …` 会不可用。
>
> 装好之后，两条能力线的入口分别是 `uv run hydrolitagent …` 与 `uv run hydro-platform …`；分别做什么见[用户指南总览](../user-guide/index.md)。注意 `hydro-platform` 的**运行时为 Windows-only**。

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
# 只填 host 根；/api/users/0 由 server 自己补。
#   服务器容器内 -> http://host.docker.internal:23119
#   裸 host      -> http://127.0.0.1:23119（host.docker.internal 不解析）
# 旧名 ZOTERO_LOCAL_API_URL 仍兼容。
ZOTERO_LOCAL_BASE_URL=http://host.docker.internal:23119

# GDrive 论文文件夹（论文入库必需 — 见下节）
GDRIVE_PAPERS_PATH=G:\我的云端硬盘\Documents\Papers\Zotero_Papers
```

| 变量 | 必需 | 说明 |
|------|------|------|
| `ZOTERO_API_KEY` | 是 | Zotero Web API 密钥 |
| `ZOTERO_LIBRARY_ID` | 是 | Zotero User ID（数字） |
| `ZOTERO_LIBRARY_TYPE` | 否 | `user`（默认）或 `group` |
| `ZOTERO_LOCAL_BASE_URL` | 否 | 本地全文检索 API 地址(host 根，如 `http://127.0.0.1:23119`)。旧名 `ZOTERO_LOCAL_API_URL` 仍兼容 |
| `GDRIVE_PAPERS_PATH` | 论文入库是 | GDrive 论文文件夹（= Linked Attachment Base Directory） |

### 3. 配置 Zotero 附件路径（用于论文入库）

论文入库使用 Zotero 的 `attachments:` scheme 解析 PDF 路径。请在 Zotero 桌面版中设置 **Linked Attachment Base Directory** 为与 `GDRIVE_PAPERS_PATH` **相同的路径**：

1. Zotero → Preferences → Advanced → Files and Folders
2. 设置 **Linked Attachment Base Directory** = `GDRIVE_PAPERS_PATH`
3. 确保 ZotMoov / 「自动重命名并移动附件」对该文件夹**关闭**

这样 `attachments:paper.pdf` 会自动解析为 `<GDRIVE_PAPERS_PATH>/paper.pdf`，跨系统路径一致。

## 配置论文入库

论文入库（`download_paper.py` / `zotero_sync`）用上面的 `.env` 即可——**裸 host 无需 TOML**。
（可选）若要与 myopenclaw 容器共用同一套凭据文件，可另建 `~/.config/zot/config.toml`，脚本会优先读它：

```toml
[zotero]
library_id = "1234567"
api_key = "xxxxxxxxxxxxxxxxxxxxxxxx"
```

无 TOML 时自动回退 `.env`。容器（myopenclaw hermes）路径不变：读 `/opt/data/.config/zot/config.toml`。
可通过 `ZOTERO_CONFIG_PATH` 环境变量覆盖此路径。

## 验证安装

```bash
# 确认依赖安装成功
uv run python -c "import pyzotero; print('pyzotero OK')"
uv run python -c "from hydrolitagent.zotero import server; print('server OK')"

# 运行测试
uv run pytest tests/test_zotero_server.py -v

# 论文入库链路自检（验证 .env / Zotero API / GDrive 目录并给出一次性设置提示）
uv run python scripts/download_paper.py --setup-check
```
