# 单篇 Zotero 论文输入

从**你自己的 Zotero 库**里定下一篇论文，产出一份 **READY 记录**（JSON），交给下一步去制卡。

这一步**只读 Zotero 和本机 PDF**，只用 Python 标准库 —— 不需要模型账号、API key 或安装任何东西
（用脚本那条时连 `uv sync` 都不需要）。

**前提**

- Zotero Desktop 正在运行，并在「设置 → 高级」勾选「允许此计算机上的其他应用程序与 Zotero 通信」。
- 这篇论文的 PDF **已经下载到本机**（这一步只读，不下载、不入库）。
- Python 3.12–3.14；命令一律**从仓库根**执行。

## 两种用法，按你要做的事选一个

它们不是同一件事的两种写法，而是**产物不同**：

| 你要做的事 | 命令 |
|---|---|
| 在终端**看一眼**记录（装了包即可） | `uv run hydrolitagent cards paper-input --user-library --item-key ABCD1234 --json` |
| 把记录**存成文件**交给下一步 | `uv run python scripts/paper_input.py --user-library --item-key ABCD1234 --output paper-input.json` |

还不确定用哪一篇时先搜候选（只返回候选，**不替你选第一篇**）：

```bash
uv run hydrolitagent cards paper-input --user-library --query '论文题名或 DOI' --json
uv run python scripts/paper_input.py --show-config    # 只看当前生效的配置
```

- `--user-library` 读**你自己的**文库；读**共享群组库**时去掉它，改用 `--group-id <数字ID>`。
- 只有脚本那条有 `--output`（写 UTF-8 JSON）。它的好处是不受终端重定向影响 ——
  用 `>` 重定向在 PowerShell 里会改变编码。
- `--item-key` 可以重复给多个：这是批处理，单篇失败不中断其余。

## 默认值与覆盖

默认值来自随仓库提交的 `configs/paper-input.toml` —— **不预设任何人的群组或路径**。

| 设置 | 默认 | 命令行 | 环境变量 |
|---|---|---|---|
| Zotero 地址 | `http://127.0.0.1:23119` | `--base-url` | `HYDROLITAGENT_CARDS_ZOTERO_BASE_URL` |
| 群组 | 不预设 | `--group-id` | `HYDROLITAGENT_CARDS_ZOTERO_GROUP_ID` |
| 超时 | 5 秒 | `--timeout` | `HYDROLITAGENT_CARDS_ZOTERO_TIMEOUT` |
| 配置文件 | 仓库 `configs/paper-input.toml` | `--config` | `HYDROLITAGENT_CARDS_PAPER_INPUT_CONFIG` |

**优先级**：命令行 → 进程环境变量 → 配置文件 → 内置默认值。

- 配置文件支持 TOML，也兼容旧 JSON 格式（读 `zotero` / `pdf_gate` 两段）。
  **模型相关字段不会被读** —— 这一步不碰模型，也不读平台总配置（`HYDROLITAGENT_CARDS_CONFIG`）。
- 不传 `--config` 时，按**仓库里**那个默认文件解析；传了相对路径，则按**当前目录**解析。
- 只读**进程环境变量**：不会自动加载 `.env`。

## 产出的记录

`--output` 存的是**输入记录**（READY 记录），**不是精读产物**。草稿最终写到哪里由下一步决定，
查当前落点用 `uv run hydrolitagent cards ai-config --json`。

| 结果 | 含义 |
|---|---|
| `SELECTION_REQUIRED` | 搜索命中多篇 —— 需要你用 `--item-key` 指定哪一篇 |
| `READY` | 身份明确且**只有一个**可读 PDF —— 附文库、父条目、附件、PDF 路径 / 大小 / SHA-256 |
| （返回原因） | 缺 PDF / 有多个 PDF / 文件读不了 |
| `IMPORT_REQUIRED` | 只在 `--demo` 且演示论文尚未导入时 —— 附 Connector 抓取链接 |

- PDF 路径由 **Zotero 返回**，脚本不自己找。**Zotero 没建全文索引也能 `READY`** —— 下一步直接读 PDF。
- `--demo` 只查内置的公开演示论文，不下载、不修改你的文库。
- 重复 `--item-key` 的批处理结果里，问题逐条列在 `problems` 中。
  批处理的**外层 JSON 不能直接喂给下一步** —— 要取其中各篇的 READY 记录。
- **退出码**：`0` = 成功（含「需要你选」这种情况）；`3` = 失败。
- 全程只连你配置的 Zotero 地址、只读本地文件，**不调用任何模型**。

## 验证

```bash
uv run pytest tests/test_paper_input.py
```

覆盖候选选择、个人 / 群组库、父条目与附件、缺 PDF / 多 PDF、全文未索引、批处理、配置覆盖。
真实演示记录留在本机，不入库。
