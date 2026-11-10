# mylibrary — 水文水资源科研工作台

[English](README.md) · **简体中文** · [在线文档](https://iheadwater.github.io/mylibrary/)

mylibrary 帮你把论文收进 Zotero，完成精读与整理，再产出可复用的证据卡、综述、文章和动画课。上游项目 [dailyinfo](https://github.com/iHeadWater/dailyinfo) 负责论文入库前的科研情报采集。

## 快速开始

克隆仓库后，在 Claude Code 或 Codex 等编码助手里打开 `mylibrary` 文件夹。所有命令都从仓库根目录运行。

```bash
git clone https://github.com/iHeadWater/mylibrary.git
cd mylibrary
uv sync --locked
cp .env.example .env
```

项目使用 Git、Python 3.12–3.14 和 [uv](https://docs.astral.sh/uv/)。`uv sync --locked` 根据 `uv.lock` 将单个 `hydrolitagent` 包的 Python 依赖安装到 `.venv`。按所用功能填写所需凭据。

| 功能 | 额外配置 |
|---|---|
| 通过 Web API 查询或写入 Zotero | Zotero API key 和文库 ID |
| 读取 Zotero 本地 PDF | 保持 Zotero Desktop 运行，并开启本地 API |
| 将 PDF 作为链接附件入库 | 配置 PDF 文件夹及 Zotero 的链接附件根目录 |
| 通过模型 API 生成文献卡 | 默认直连方式使用 `DEEPSEEK_API_KEY`，也可交给当前助手生成，无需单独的密钥 |
| 制作论文动画课 | 安装 Node.js 20+（含 npm）和 FFmpeg（含 FFprobe）。用 `uv sync --locked --extra paper-video` 安装 Python 依赖，再按[视频配置指南](docs/user-guide/paper-video.md)配置 Remotion。 |

详细配置见[安装指南](docs/getting-started/installation.md)。

## 可以让助手做什么

| 你可以这样说 | 交付结果 | 指南 |
|---|---|---|
| 把这篇论文下载并入库 | 解析 DOI、arXiv ID 或标题，建立带链接 PDF 附件的 Zotero 条目 | [论文入库](docs/user-guide/paper-pipeline.md) |
| 在我的 Zotero 库里找论文 | 搜索和读取文献条目、附件与批注 | [Zotero MCP 工具](docs/user-guide/mcp-tools.md) |
| 把这篇论文做成证据卡 | 读取 PDF，生成带出处的文献卡 | [文献卡与主题卡](docs/user-guide/cards/index.md) |
| 看看这些论文有哪些共同主题 | 从文献卡生成候选主题，整理结果供复核 | [主题池](docs/user-guide/cards/unified-theme-pool.md) |
| 做一期公众号文献周报 | 精读全文、按主题归类并起草文章 | [文献深度处理](docs/user-guide/literature.md) |
| 把这篇论文做成中文动画课 | 生成有声视频、字幕和可编辑工程 | [论文动画课](docs/user-guide/paper-video.md) |
| 统计这位学者或这个机构的发文 | 用 OpenAlex 确认身份并汇总发表记录 | [论文统计](docs/user-guide/scholars/index.md) |

也可以[在 Obsidian 里浏览阅读产物](docs/user-guide/cards/reading-in-obsidian.md)，或[检查当前模型和产物路径](docs/user-guide/cards/runtime-maintenance.md)。

## 命令行示例

```bash
# 启动 Zotero MCP 服务，端口 8002
uv run python -m hydrolitagent.zotero.server

# 下载 PDF 并同步到 Zotero
uv run python scripts/download_paper.py --doi "10.1016/j.jhydrol.2023.130249" --sync

# 定位 Zotero 论文并查看制卡配置
uv run hydrolitagent cards paper-input --user-library --item-key ABCD1234 --json
uv run hydrolitagent cards ai-config --json

# 构建阅读索引或查询学者发文
uv run hydrolitagent cards index --json
uv run hydrolitagent scholars resolve --name "Zhang San" --json
```

更多命令见[快速入门](docs/getting-started/quickstart.md)、[文献深度处理](docs/user-guide/literature.md)和[项目架构](docs/development/architecture.md)。项目助手技能位于 [skills/](skills/)。

## 文档与测试

```bash
uv run mkdocs serve
uv run mkdocs build --strict
uv run pytest
```

Zotero 集成测试需要本机 Zotero 正在运行，且库中有符合条件的测试文献。见[测试源码](tests/test_zotero_local_api_integration.py)。

## 贡献与许可证

欢迎通过 PR 提交贡献，请说明改动并确认有权分享所提交的材料。mylibrary 使用 **GNU Affero General Public License v3.0**。见 [LICENSE](LICENSE)。
