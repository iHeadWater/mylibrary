# 项目依赖安装与同机隔离验证

如果要连同状态/调度一起恢复，使用 [setup统一入口](workstation-setup.md)。本页保留单独安装Python环境的操作，PDF工具仍可单独安装。

已实现项目级 Python 环境安装、版本与 wheel 哈希核对、重复安装复用及真实 PDF 兼容性验证；Poppler 另由 [项目原生工具安装器](native-deployment.md) 提供。**尚不是一键完成整台新电脑部署**：基础 Python、Zotero、Codex 登录仍需准备，每日计划另行注册。安装器不修改总配置、不操作 Git、不调用模型。

## 当前可以直接运行

在项目根目录的 PowerShell 中：

```powershell
python automation/run.py bootstrap --json
python automation/run.py bootstrap --install --json
.\.venv\Scripts\python.exe automation/run.py bootstrap-native --install --json
.\.venv\Scripts\python.exe automation/run.py doctor --json
```

第一条只读计划，不创建目录、不下载；第二条明确安装到 `deployment.environment_dir`，第三条安装项目 PDF 工具。`INSTALLED` 表示本次完成，`REUSED` 表示检查通过且没有再次下载/安装。最后一条检查群组、工具、账号与依赖，不调用模型。日常原有 `python automation/run.py run-once --json` 仍可用，总配置会将 PDF 工作交给新的项目 Python；也可用上面的 `.venv` 解释器运行统一入口。无需激活虚拟环境或修改系统 PATH。

可通过 `--config` 选择完整总配置；相对工具路径基于 `paths.project_root`。示例面向 Windows，自定义环境目录时需同步修改 `card_generator.pdf_direct_trial.python_executable`；安装器不偷偷切换生产配置。

## 单一配置入口

| 总配置字段 | 含义与默认值 | 保护边界 |
|---|---|---|
| `deployment.environment_dir` | 项目 Python 环境，`.venv` | 仅项目内，不得与源码、配置、知识或 Git 目录重叠；未知已有目录拒绝接管 |
| `deployment.dependency_lock_file` | `automation/setup/dependencies.lock.json` | 版本、来源、大小、SHA256；受 Git 版本管理，不能放在环境/缓存内 |
| `deployment.wheel_cache_dir` | `.runtime/wheel-cache` | 不进入 Git；下载包先核对哈希，损坏缓存保留并报错 |
| `deployment.base_python` | `null` 使用启动命令的解释器 | 可填已有基础 Python；不负责安装基础 Python |
| `deployment.install_timeout_seconds` | 300 秒 | 每个本机安装/检查子进程的等待上限，不是完整安装总耗时 |
| `deployment.download_timeout_seconds` | 30 秒 | 下载套接字超时，不是整次安装总耗时 |
| `card_generator.pdf_direct_trial.python_executable` | `.venv/Scripts/python.exe` | 正式制卡、精读和路径读取实验共用；当前已验证后切换 |

锁文件当前只含 `pypdf==6.18.0`。安装使用核对后的本地 wheel、`pip --isolated --no-index --no-deps --require-hashes --only-binary=:all:`；不执行远程脚本、不从源码构建、不将项目安装到全局环境。[pip 安全安装文档](https://pip.pypa.io/en/stable/topics/secure-installs/)

Python 推荐版本为 `.python-version` 的 3.12.14，支持 >=3.12,<3.15；安装记录实际版本，不承诺所有电脑解释器完全相同。此前 6.10.0 的 [PyPI 安全公告元数据](https://pypi.org/pypi/pypdf/6.10.0/json) 列出多项耗时或内存耗尽问题，因此采用 [6.18.0 的官方包及哈希](https://pypi.org/pypi/pypdf/6.18.0/json)。新版本查询时未列出漏洞，不代表不存在风险，也不是此前 Codex 网络断线的原因诊断。

## 重复、故障与换机

- 安装目标 `.hydro-environment.json` 绑定项目路径、环境路径和依赖锁哈希。未知目录、移动过的环境或不同锁报 `ENVIRONMENT_CONFLICT`，不覆盖、不删除。
- 中断的本项目同版本安装可以续装；已完成环境发生漂移报 `ENVIRONMENT_DRIFT`，不自动升级。升级时选择新环境目录，验证后再切换读取器路径。
- 缓存哈希不符报 `WHEEL_HASH_MISMATCH`，保留文件，不安装；可在总配置选择新缓存目录重试。
- 互斥锁位于环境旁 `*.bootstrap.lock`，进程退出由操作系统释放，不是多机锁。默认 `.venv`、缓存和锁不进 Git；自定义环境目录时必须加入忽略规则。
- 不复制 `.venv` 到另一台电脑，应重新创建；这是 Python 官方对虚拟环境可移植性的限制，本项目也拒绝直接接管搬动后的环境。[venv 文档](https://docs.python.org/3/library/venv.html)
- Python 的 bootstrap 不安装 Poppler；另运行 bootstrap-native。两者均不变更账号、不注册调度。换机仍需准备外部前提，再按 [恢复说明](recovery.md) 对账；本地未推送成果不等于远端备份。

## 真实 PDF 验证（可选，不进入日常调度）

```powershell
.\.venv\Scripts\python.exe automation/verify_deployment.py --item-key CEXH4PQA --item-key 7F8QLSNY --item-key JUKFEIFC
```

必须已有任务、证据包及原始 PDF。脚本只读 Zotero，在内存中选择项目 Python，不改总配置；逐页提取文字但只保存字符数，调用固定沙箱检查首图渲染，并记录源哈希和现有知识文件哈希。报告在 `.runtime/deployment-trials/`。无模型调用、无摘录任务、无内容质量门槛，不是日常制卡附加负担。

实测：新环境 Python 3.14.6 / pypdf 6.18.0，二次安装 REUSED。三篇全文 16/17/43 页、109203/90597/201495 个提取字符，沙箱首图渲染均通过，三张首图可读。45 个原运行/知识文件及三份 PDF 未变。报告 `.runtime/deployment-trials/deployment-check-75iqophq/verification.json`。实际配置随后切换项目 Python，doctor 9 项通过。

新环境下全量416项测试也通过。再以新环境执行 `automation/verify_runtime_recovery.py`，新运行目录恢复三篇 COMPLETED，第二轮任务零变化，原45文件未变；报告 `.runtime/recovery-trials/recovery-check-4p5szrk6/verification.json`。

这只证明同机新 Python 环境与样本兼容，未证明干净新机器、所有 PDF、模型理解或科学质量。每日计划已在本机启用，安装与验证边界见[调度手册](cron.md)；完整换机及其余待验收场景见[工程化缺口](engineering-status.md)。
