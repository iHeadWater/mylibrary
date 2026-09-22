# 单篇论文命令行流程：输入 → 生成 → 校验

三个步骤都由普通终端运行 Python。**只有主体卡生成调用所选模型**；读取 Zotero/PDF、检查身份、校验字段与保存记录由代码执行。无需修改或提交 Codex/Claude 软件、模型本身和个人凭据。

## 一次安装

安装 Python 3.12–3.14、uv，在仓库根执行：

```powershell
uv sync --all-packages --locked
```

Windows 以下使用 `.\.venv\Scripts\python.exe`，macOS/Linux 替换为 `.venv/bin/python`。不要复制别人的 `.venv` 或登录文件。安装依赖需要联网。

合并前分支范围：#40 提供输入，#43 基于 #27 提供生成，#44 基于 #43 提供校验。单独拉取 #44 不包含尚未合并的 #40；三步连跑需要这些 PR 均可用，或先准备一份已有的单篇 READY JSON。

## 1. 本机 Zotero 输入：不调用模型

打开 Zotero，启用「允许此计算机上的其他应用程序与 Zotero 通信」，确保 PDF 已下载。

```powershell
python scripts/paper_input.py --show-config
python scripts/paper_input.py --user-library --query '论文题名或 DOI'
python scripts/paper_input.py --user-library --item-key ABCD1234 --output paper-input.json
```

此脚本只用标准库，无需安装模型客户端。用候选中确认的 Key 替换示例；群组库将 `--user-library` 改为 `--group-id 群组数字ID`。输入默认值在 `configs/paper-input.toml`，可用参数或 `HYDRO_PLATFORM_ZOTERO_*` 环境变量覆盖，不读模型总配置。PDF 路径由 Zotero 返回。只有单篇 READY 记录进入下一步。

## 2. 主体卡生成：由命令驱动所选模型

选择 Codex 或 Claude，安装所选 CLI 并完成自己的登录或 API 环境认证。**不用同时安装两种 CLI**。

```powershell
.\.venv\Scripts\python.exe -m hydro_platform ai-config --ai-provider claude --json
.\.venv\Scripts\python.exe -m hydro_platform evidence-generate --paper-input paper-input.json --ai-provider claude --json
# 使用 Codex 时将 claude 换成 codex
```

Codex 使用仓库已有沙箱阅读流程，需要本机 Poppler 工具；Claude 使用原生 PDF Read，不需要 Poppler。Python/pypdf 已由项目安装。Claude 需支持隔离模式和结构化输出，本次测试版本为 2.1.278。

`configs/ai.toml` 是公开默认值。后端、模型、程序位置、超时和 PDF 工具均可覆盖；默认模型留空，使用所选 CLI 默认值。优先级：命令行 → 进程环境变量 → `.env` → TOML → 内置默认值。常用变量为 `HYDRO_PLATFORM_AI_PROVIDER` / `_MODEL` / `_EXECUTABLE` / `_TIMEOUT_SECONDS`（均以 `HYDRO_PLATFORM_AI` 开头）。凭据交由所选 CLI 管理，不放入该 TOML。[详细配置](subject-card-draft.md)。

产物根调用 #27 的同一解析器：`--output-root` → `HYDROLITAGENT_LITERATURE_ROOT`（支持 `.env`）→ `configs/paths.toml` → 仓库 `outputs/`。用 `ai-config --json` 查实际落点；不写死作者路径、不清理外部云盘目录。

输出里的 `draft_path` 是下一步输入。结果是待校验草稿，不会因模型完成而自动标为正确或正式发布。

## 3. 草稿校验：不运行模型

```powershell
.\.venv\Scripts\python.exe scripts/paper_validate.py --paper-input paper-input.json --draft '上一步返回的 draft_path'
```

不需要模型客户端登录、Zotero 在线或原 PDF 可访问。校验代码检查字段、身份、引用编号、物理页范围及版本指纹；识别 Codex 和 Claude 的不同读取记录，不重新调用模型。报告追加到草稿旁 `validations/<ID>/validation.json`。用 `--report-dir` 或 `HYDRO_PLATFORM_VALIDATION_REPORT_DIR` 改位置。

独立校验脚本只依赖项目源码（可从完整环境运行），不需要 AI SDK 或 CLI。成功退出码 0，校验/保存失败 3。PASS 表示已实现的确定性规则通过，不证明科学结论正确。错误应由后续修正工作处理，不能为了让示例通过而伪造内容。

## 无私人配置的校验示例

```powershell
.\.venv\Scripts\python.exe scripts/paper_validate.py --draft hydro-platform/automation/examples/subject-card-validation/draft.json --paper-input hydro-platform/automation/examples/subject-card-validation/paper-input.json --report-dir outputs/validation-demo
```

这是合成数据，用来演示校验入口；不包含真实论文结论或本机凭据。
