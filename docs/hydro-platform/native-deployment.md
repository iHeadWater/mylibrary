# 项目内 PDF 工具安装

目的：换机不再依赖旧电脑 Codex 缓存或 MiKTeX 的绝对路径。当前正式配置与示例使用项目内 Poppler；原有外部工具保留，不修改系统 PATH、Codex 权限、登录、论文或知识文件。

## 安装和日常使用

在仓库根目录的 PowerShell：

```powershell
uv run hydro-platform bootstrap --install --json
uv run hydro-platform bootstrap-native --json
uv run hydro-platform bootstrap-native --install --json
uv run hydro-platform doctor --json
```

Python 安装见 [deployment.md](deployment.md)。原生工具命令默认只读计划，只有 `--install` 才下载/解压；已有同版本完整安装返回 `REUSED`，不重装。doctor 在选择项目工具时检查全部安装文件指纹和三工具版本，不安装、不调用模型。

安装完成后的日常入口仍是 `uv run hydro-platform run-once --json`，无需每次安装或验证工具。本文的验证脚本不会进入日常制卡、主题或调度链路。

## 总配置

| 字段 | 当前值 / 用途 |
|---|---|
| `deployment.native_tools_dir` | `.tools/poppler`，项目独立安装目标 |
| `deployment.native_lock_file` | `automation/setup/native-tools.lock.json`，固定发布包来源、版本、大小、SHA256 |
| `deployment.native_cache_dir` | `.runtime/native-cache`，下载包及中断临时文件 |
| `deployment.download_timeout_seconds` | 30，下载套接字超时，不是整次安装期限 |
| `deployment.install_timeout_seconds` | 300，每个版本探测子进程的超时 |
| `card_generator.pdf_reader.pdfinfo_executable` | `.tools/poppler/Library/bin/pdfinfo.exe` |
| `card_generator.pdf_reader.pdftoppm_executable` | `.tools/poppler/Library/bin/pdftoppm.exe` |
| `card_generator.pdf_reader.pdftotext_executable` | `.tools/poppler/Library/bin/pdftotext.exe`；目前文字引擎为 pypdf，此工具仅备选引擎使用 |

全部项目相对路径基于 `paths.project_root`，不依赖命令行当前目录。更改安装目标后须在同一个总配置中同步修改三项读取路径；安装器本身不切换生产配置。环境、原生工具、两类缓存不得彼此嵌套或覆盖代码/知识/配置/锁文件。

## 来源与安装边界

- 固定 [v26.07.0-0 发布包](https://github.com/oschwartz10612/poppler-windows/releases/tag/v26.07.0-0)，SHA256 为 `a711b0563b06edc488583d28198b6734c5a494afbbd1b9d87d3d2866062fb7e2`，42,202,938 字节；来源记录在锁文件，不自动选择 latest。
- [打包维护者](https://github.com/oschwartz10612/poppler-windows)说明其打包 conda-forge 构建及依赖；这不是本项目编译的二进制，也不称为 Poppler 官方 Windows 安装包。保留全部552个文件及随包版权/许可文本，不把维护者仓库许可等同于全部依赖许可。
- 安装代码仅允许固定仓库 HTTPS 下载地址和已列出的 GitHub 资产重定向域名；大小和哈希正确后才解压/执行。无须 GitHub CLI、令牌或远程安装脚本。
- 解压前检查全部路径、大小、数量；拒绝越界、链接、Windows 保留名、数据流与大小写重复路径。解压时只发布相同或尚不存在的文件，不覆盖不同内容。
- `.hydro-native.json` 绑定项目、目标路径与锁哈希。未知已有目录、移动过的安装、文件漂移保留并报错。已完成安装逐文件校验后才运行固定 `-v` 命令；探测进程 PATH 仅含新工具与 Windows 系统目录。
- 单机互斥锁位于目标旁 `poppler.bootstrap.lock`；同版本的已知中断可续装。哈希和所有权文件不是抗同账号恶意修改的签名认证。
- `.tools/`、`.runtime/`、安装锁不进入 Git。锁文件、代码和文档需要进入备份；当前未自动提交/推送。自定义工具目录时也须加入忽略规则。

## 故障处理

| 结果 | 处理 |
|---|---|
| `NATIVE_ARCHIVE_HASH_MISMATCH` | 保留损坏缓存，不执行；核对来源，或配置新缓存目录重新下载 |
| `NATIVE_OWNERSHIP_CONFLICT` / `NATIVE_INSTALL_DRIFT` | 不删除、不覆盖；检查已有文件，或配置全新工具目录安装，验证后切换路径 |
| `NATIVE_INSTALL_FAILED` | 查看脱敏 failure_type/errno；网络或进程失败保留现状，修复后再运行，不无限自动重连 |
| `NATIVE_TOOL_PROBE_FAILED` | 当前工具无法独立运行或版本不符；不切正式路径，不通过放开沙箱绕过 |
| `NATIVE_PLATFORM_UNSUPPORTED` | 当前仅 Windows x86_64；ARM64、Linux、macOS 没有本安装器的验证 |
| 真实沙箱 PermissionError | 检查所选工具目录的本机权限；不要关闭沙箱或修改整个用户目录的权限 |

## 实际证据与未证明范围

1. 全新缓存的直接 HTTPS 下载、SHA256 核对、552文件安装与二次复用成功，记录在 `.runtime/native-trials/native-check-0vmu821i/verification.json`。该次整体验证是失败状态：验证器的私有临时目录拒绝沙箱账号执行工具，不能把安装成功冒充整体验证通过。
2. 修正验证目录按普通项目目录继承权限，不修改旧目录 ACL。另一次 fresh 下载失败，原失败报告保留。网络稳定性不在安装器成功保证范围。
3. 使用正式项目工具并排除旧原生工具 PATH，三篇16/17/43页全页文字提取、沙箱首图渲染均成功，三个PNG已查看，含图形摘要显示正常。45个原运行/知识文件、三份PDF及旧工具哈希不变，模型0；安装二次返回 REUSED。记录 `.runtime/native-trials/native-check-b79fc6b000f24883b3b5def246ab0e20/verification.json`，预览在 `.runtime/deployment-trials/deployment-check-i23qfqz5/`。验证后才切换正式与示例配置的三工具路径。

重复本机无模型验证：

```powershell
.\.venv\Scripts\python.exe hydro-platform\automation\verify_native_deployment.py --reuse-installed --item-key CEXH4PQA --item-key 7F8QLSNY --item-key JUKFEIFC
```

去掉 `--reuse-installed` 会新建独立下载缓存及工具目录，重新下载约42MB。它是显式部署演练，不是日常步骤；报告保留在 `.runtime/native-trials/`，不覆盖旧失败记录。

上述下载证据与沙箱兼容证据来自分开的运行，不宣称同一次 fresh 全链路通过。仍未证明干净异机、真实关机/登录恢复、所有 PDF 或模型科学理解；基础 Python、Zotero、Codex 及私人账号仍需准备。总体边界见[验证地图](tests.md)，换机步骤见[换机恢复](recovery.md)。

配置切换后复验：当时 503 项自动测试通过（28.358 秒），doctor 12 项通过。`verify_zotero_readiness.py` 使用真实已就绪库和隔离知识副本，3卡跳过、6主题步骤复用，第二次调度 ALREADY_COMPLETED，模型/应用启动调用0、原45文件与Zotero进程集合不变；报告 `.runtime/readiness-trials/readiness-check-cp1tpshc/verification.json`。工具路径改变没有触发旧主题重新生成。
