# 单篇 Zotero 论文输入

此命令只用 Python 标准库，不需要 AI 客户端、SDK、模型账号或 API key。打开 Zotero Desktop，启用「允许此计算机上的其他应用程序与 Zotero 通信」，将 PDF 下载到本机。从仓库根执行：

```powershell
python scripts/paper_input.py --show-config
python scripts/paper_input.py --user-library --query '论文题名或 DOI'
python scripts/paper_input.py --user-library --item-key ABCD1234 --output paper-input.json
```

Python 支持 3.12–3.14。将 Key 替换为候选中确认的条目；群组库改用 `--group-id 你的群组数字ID`。`--output` 写 UTF-8 JSON，避免 Windows 重定向产生不同编码。此步无需安装 pip 依赖。

## 公开默认值与覆盖

参照 #27 的文件默认值与环境变量覆盖方式，提交 `configs/paper-input.toml`，不预设作者群组或路径。输入只读取 Zotero/PDF 门禁配置，不再加载或校验平台的模型配置，也不读取 `HYDROLITAGENT_CARDS_CONFIG`。

| 设置 | 默认 | 参数 / 环境变量 |
|---|---|---|
| Zotero 地址 | `http://127.0.0.1:23119` | `--base-url` / `HYDROLITAGENT_CARDS_ZOTERO_BASE_URL` |
| 群组 | 不预设 | `--group-id` / `HYDROLITAGENT_CARDS_ZOTERO_GROUP_ID` |
| 超时 | 5 秒 | `--timeout` / `HYDROLITAGENT_CARDS_ZOTERO_TIMEOUT` |
| 配置文件 | 仓库 `configs/paper-input.toml` | `--config` / `HYDROLITAGENT_CARDS_PAPER_INPUT_CONFIG` |

优先级：参数 → 进程环境变量 → 配置文件 → 内置默认值。输入配置支持 TOML，也兼容旧 JSON 的 `zotero` / `pdf_gate` 字段；AI 字段不会被读取。默认配置从脚本所在仓库解析，显式相对配置路径从命令当前目录解析。输入 PR 不依赖 #27，因此只读进程环境变量，不自动读 `.env`。

PDF 路径由 Zotero 返回；此步骤不生成精读产物。`--output` 是操作者指定的输入记录位置，后续草稿产物根由 #27/#43 管理。已有完整平台环境也可用 `python -m hydrolitagent.cards paper-input --user-library --item-key ABCD1234 --json`，同样无需模型配置。

## 状态与边界

搜索返回 `SELECTION_REQUIRED`，不自动选择第一篇；单篇身份明确且仅一个可读 PDF 返回 `READY`，附文库、父条目、附件、PDF 路径/大小/SHA-256。缺 PDF、多个 PDF 或文件不可读会返回原因。全文未索引仍可 READY，后续直接读 PDF。

`--demo` 查询公开演示论文；未导入时返回 `IMPORT_REQUIRED` 和 Connector 抓取链接，不下载、不修改文库。重复 `--item-key` 是批处理，不因单篇失败而中断；取其各篇 READY 记录进入后续单篇流程，不能直接传批处理外层 JSON。

独立脚本成功或候选退出码 0，失败 3；批处理问题逐条列在 `problems` 中。仅连接配置的 Zotero 地址并读本地文件，不调用任何模型。

## 验证

```powershell
uv run pytest tests/test_paper_input.py
```

覆盖候选选择、个人/群组、父条目/附件、缺失/多个 PDF、未索引全文、批处理及配置覆盖；真实演示记录保留本机，不提交个人文件。
