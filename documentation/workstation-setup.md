# 一键安装与恢复入口

`setup` 将项目依赖安装、运行检查、状态对账和每日计划恢复串成一个有失败记录的流程。它不生成卡片/主题、不代登录、不修改总配置、不提交或推送Git。基础Python、Zotero和Codex仍须先准备，这不是整台电脑的静默安装器。

## 怎么运行

在项目根目录的 PowerShell：

```powershell
python automation/run.py setup --json
python automation/run.py setup --apply --json
```

第一条是只读预览：不下载、不创建运行区、不启动Zotero、不注册任务。它仍会检查当前本机程序、登录及共享库，所以不是离线清单。

第二条执行安装与恢复。完成或中断后均可重复同一条命令：完整环境复用，已保存卡片按来源对账，不删除未知目录、不为了恢复重调用AI。进度在stderr显示“安装进度”，最终stdout保留一个JSON；加 `--no-progress` 可关闭。

日常处理仍用 `python automation/run.py run-once --json`，或由已启用的每日计划运行。日常不需要反复执行setup。

## 开始前

- 已取回仓库源码、模板和共享成果；本地没有推送/备份的结果不能凭空恢复。
- 已安装支持的基础Python（依赖锁要求 >=3.12,<3.15）、Zotero和Codex；本人完成私人账号登录，共享库与PDF同步可用。程序不复制认证文件。
- 选择完整总配置；默认 `config/config.json`，另一个配置用 `--config` 或 `HYDRO_PLATFORM_CONFIG`，没有自动覆盖合并。
- 当前统一安装要求 `single_agent` / `local_path`，PDF Python指向 `deployment.environment_dir`，三项PDF工具指向 `deployment.native_tools_dir`。路径对不齐报 `SETUP_READER_BINDING_MISMATCH`，不偷偷改配置。自定义外部工具仍可用原来的分步入口。
- 只在指定制卡机启用 `scheduler.enabled`。另一台只是查看资料或做演练时应关闭，避免两台机器同时制卡；当前不是分布式授权系统。

## 实际顺序与副作用

### 另一台 Windows 电脑的手动复现

先用有私有仓库访问权的 GitHub 账号取回 `hanfandada/hydro-platform`。准备好上述基础软件、本人登录及 `qinjiajun` 共享库的本地 PDF 同步后，在新副本的根目录操作：

1. 首次复制 `config/config.json` 为 `config/config.local.json`；已有私人配置时不要覆盖。它是完整配置，不是增量覆盖文件，且已被 Git 忽略。
2. 在私人配置中将 `scheduler.enabled` 改为 `false`，先手动演练，不创建第二台机器的自动制卡计划。若要真正移交制卡职责，应先暂停原制卡机；当前跨机器没有共同任务锁。
3. 检查 `card_generator.proxy`：仓库配置的 `http://127.0.0.1:7897` 只适用于该端口确有代理的电脑。有代理则填写新电脑的实际地址；不需显式指定则将 `enabled` 设为 `false`，恢复继承该电脑环境。不会更改系统或 Codex 客户端设置。
4. 使用同一份私人配置执行下列命令。依赖和 PDF 工具会在新副本内重建，不要复制旧 `.venv`、`.tools`、`.runtime` 或账号凭据。

```powershell
python automation/run.py setup --config config/config.local.json --json
python automation/run.py setup --apply --config config/config.local.json --json
python automation/run.py run-once --config config/config.local.json --json
```

关闭调度时安装预期返回 `READY_MANUAL`。已有 7 张完整粗卡和主题成果随 Git 保存；同一文献库/PDF、模型及主题输入未变时，已有成果应复用，而不是再次制卡。恢复成功只是换机恢复验收；验证新电脑确实能调用模型制卡，还需由用户加入一篇有完整 PDF 的新论文，再运行同一个 `run-once`。不要删除现有卡片来强迫重生成，也不要把“复用了旧卡”当作新电脑已经生成过新卡。

### 安装流程

| 顺序 | 做什么 | 写入与失败边界 |
|---|---|---|
| 配置与安装计划 | 核对路径、环境所有权、依赖锁、基础Python | 只读；不覆盖未知环境/工具目录 |
| 程序、登录、Zotero就绪 | 检查Codex版本/登录；apply按zotero.startup单次启动与有限等待 | 不代登录、不改Zotero偏好或文献；失败先停止安装 |
| Python与PDF工具 | 使用现有bootstrap和bootstrap-native | 仅项目环境/工具/缓存；版本与哈希检查；完整安装REUSED |
| 环境检查 | doctor先不要求计划存在 | 无模型；新机缺计划不会挡住安装本身 |
| 本地状态恢复 | recover按共享库和已有证据包对账 | 只写派生任务、快照和日志；来源/人工改动冲突停止，不覆盖共享知识 |
| 每日计划 | scheduler.enabled=true时安装/核对本项目任务 | 归属错误拒绝；未启用则不创建或修改任务；不主动调用schedule-tick |
| 最终检查 | doctor按完整配置检查 | 区分计划已注册与实际触发已经验证；保留warning和待处理状态 |

安装自身模型调用0，但启用的Windows计划随后到期可调用原科研流水线并消耗额度。这一点不被“setup不调用模型”掩盖。

每个阶段前后核对同一总配置文件指纹，中途修改配置会停止；不会拼接两份配置继续。统一入口有独立互斥锁，各安装器、恢复器和调度器仍使用自己的保护；不会抢占正在制卡的租约。

## 看结果与继续

| 状态 | 含义 |
|---|---|
| `PLAN` | 当前预检通过，尚未安装/恢复，不等于部署完成 |
| `READY_SCHEDULED` | 项目安装、对账和计划定义检查通过；不等于真实关机/登录触发已验收 |
| `READY_MANUAL` | 环境与对账通过，配置没有启用调度，可以手动run-once |
| `BLOCKED` | 查看failed_step及该步骤result；前面已完成的步骤保留，修复后重复setup --apply |
| `CANCELLED` | 用户中止，退出码130；保留已有步骤，不做破坏性清理 |

READY不是全部论文已制卡，也不是科学质量认证。`recovered_state_counts`可含等待PDF或阻塞项，后续由原流水线处理。失败不自动重试、不无限重连；计划注册结果不确定时先 `schedule-status --json`，不要复制创建任务。报告在 `.runtime/logs/setup-runs/`，写报告失败时终端会提示，不声称此前动作已回滚。

## 验收证据与边界

- 523项自动测试通过（41.038秒）：新增16项setup测试、4项演练器测试；覆盖只读/副作用顺序、缺登录、下载/环境失败、配置变化、恢复冲突、调度失败、中止、日志失败、未知演练目录保护、UTF-8以及隔离Python下辅助模块导入。
- 同机新目录演练只复制源码/模板/共享知识，不复制旧`.runtime`、`.venv`、`.tools`、PDF或私人配置。首次重新下载安装Python依赖及Poppler、恢复3篇COMPLETED；再次执行两类安装均REUSED。
- 新目录完整入口两次均跳过3张旧卡、复用6个主题步骤，模型/启动/系统任务调用均被禁止且实际计数0。随后三篇16/17/43页全文提取和沙箱首图渲染通过，三张PNG已查看且可读，原45个运行/知识文件不变。
- 报告：`.runtime/setup-trials/relocated-903ecba2b46e40d8ac3e0e8b34d55ce0/verification.json`。演练器先后遇到中文输出编码和隔离模式辅助模块导入错误，修复后在原目录继续；旧失败报告保留，不把续跑说成首轮无故障。不是干净新电脑或新账号验证，原Zotero/Codex/基础Python仍在使用；没有创建第二个自动任务。
- 正式项目随后执行setup --apply成功，20秒左右返回READY_SCHEDULED：两类安装REUSED、3篇COMPLETED、已有HydroPlatform-qinjiajun计划核对通过、最终环境检查12项通过。卡片/主题/事件/日报/成员文件前后哈希一致；本地快照按恢复流程更新。报告 `.runtime/logs/setup-runs/ba6d20791c6947899d347d0584af1af3.json`。不是新增模型制卡或实际登录触发验证。

需要显式再次演练时运行 `python automation/verify_setup.py`。它会建立新项目副本并下载依赖，不是日常步骤。只有前一进程已确认退出，才用 `--resume <trial_root>`继续；不得因观察超时盲目重复启动。查看报告比重新跑科研模型更合适。

尚未证明：从零基础软件安装、干净异机的账号/沙箱/调度全链路，以及真实关机、重新登录和云端PDF同步延迟。剩余事项见 [工程化状态](engineering-status.md)，分步操作保留在 [Python部署](deployment.md)、[PDF工具](native-deployment.md)、[运行维护](runtime-maintenance.md)、[每日计划](cron.md)。
