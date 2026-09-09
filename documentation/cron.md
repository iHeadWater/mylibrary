# 每日运行与 Windows 调度

## 当前已启用

本机 Windows 任务 `HydroPlatform-qinjiajun` 已注册并启用，使用当前 Windows 用户的普通交互令牌。执行 `.venv/Scripts/pythonw.exe automation/scheduled_run.py --config ...`，不需要 Codex 对话窗口，也不保存 Windows 密码。Windows必须已登录；已加入Zotero缺失时单次启动与有限就绪等待，仍需有效Zotero/Codex账号和可用附件。不自动登录、不唤醒关机电脑；[启动/等待规则](zotero-readiness.md)。

| 工作 | 时间 / 入口 | 身份与秘密 | 限制与重试 | 观察位置 |
|---|---|---|---|---|
| 每日检查/补跑 | 日常时点09:00，30分钟一次轻量唤醒；登录后120秒再检查 | Windows 当前用户；模型仍使用本机 Codex 登录，任务参数不含密码/令牌 | Windows IgnoreNew + 调度锁 + 原流水线锁；只处理最近到期的一轮 | `schedule-status --json` |
| 到期的知识流水线 | `scheduled_tick` → 原 `run_once` | 原群组6618088、原提供者配置 | 全部完成后日内跳过；失败或仍有等待/延后则60分钟后补查，每个日任务最多3次；论文自身冷却/次数保护仍生效 | scheduler-state、pipeline-runs、theme-runs |
| 事件与日报 | 原 run_once 完成/失败后的监控路径 | 明确贡献者或系统身份，无额外模型 | 不追溯历史，不因日报失败重做成功卡片 | `reports/daily/YYYY-MM-DD.md` |

**30分钟是检查间隔，不是每30分钟重新调用模型。** `next_run_time` 是 Windows 下一次唤醒时间，可能早于09:00；`due_status=ALREADY_COMPLETED` 时只读状态即结束。手动 `run-once` 不受每日完成状态限制，仍可处理当天稍后新增的论文；不会重制旧卡。

日任务以本机时区的09:00为分界。09:00前开机，最多补最近一天到期的任务；不会为关机十天连续回放十轮。如果03:45补跑，slot_date可能是前一天，实际执行时间和日报仍记录当天。修改系统时间导致状态“来自未来”时停止并显示 CLOCK_REVERSED，不自动回放。

Windows 的 StartWhenAvailable 和登录触发用于补机会，具体启动可能延迟，不保证恢复后的某一秒立即运行。有关字段与默认值依据 [微软设置文档](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset?view=windowsserver2025-ps)、[StartWhenAvailable](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-startwhenavailable)、[登录触发](https://learn.microsoft.com/en-us/windows/win32/taskschd/logontrigger)。

## 操作入口

在项目根目录使用原有 Python 前缀：

```powershell
python automation/run.py schedule-plan --json
python automation/run.py schedule-status --json
python automation/run.py schedule-install --json
```

- plan：查询并预览，不注册、不运行模型。
- status：读回 Windows 真正的定义和状态，不只看配置；显示下次检查、上次系统返回码、日任务状态和补跑条件。注册存在与流水线成功分开报告。
- install：按总配置安装或更新；定义已一致则不改。只接受本项目/配置归属的同名任务；其他任务、运行中的任务拒绝覆盖。Windows 导出的默认值、省略字段、同一账号名称/SID、等价时长按官方语义比较，不机械比 XML 字符串。[默认值来源](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema)
- `schedule-tick --json`：手动执行一次相同的到期检查；到期才调用原流水线，不是强制忽略每日保护。
- `schedule-remove --json`：明确卸载本项目计划，保留全部知识、运行记录和依赖；以后可重新 install。运行中拒绝卸载，不自动杀处理进程。

暂停：总配置 `scheduler.enabled=false`，再执行 schedule-install。修改配置后新的唤醒本身也会跳过；不会中断已在运行的论文。重新启用设为true并再次install。修改 task_name 前先卸载旧名称；否则旧注册仍可能存在。换机器在完成基础环境、Zotero/Codex登录与 recover 后重新install，不复制 Windows 账号身份或密码。

## 总配置字段

| `scheduler` 字段 | 当前 / 默认含义 | 更改后 |
|---|---|---|
| enabled | 本机true；共享示例false | install使 Windows 状态一致；tick入口也检查开关 |
| task_name | 本机HydroPlatform-qinjiajun | 仅允许前缀HydroPlatform-及简单名称；先移除旧名称 |
| daily_time | 09:00，电脑本地时间 | install更新时间；不是 UTC 或日报偏移量 |
| poll_interval_minutes | 30；允许5–1440 | Windows轻量检查间隔；install |
| retry_interval_minutes | 60；允许1–1440 | 从失败结束起冷却，下一次唤醒检查；不立即循环 |
| max_attempts_per_slot | 3；允许1–24 | 包含首次尝试；到上限报告，不在本日继续调用流水线 |
| logon_delay_seconds | 120；允许0–3600 | 登录后延迟；install |
| execution_time_limit_seconds | 0，不另加 Windows 整轮截止 | 沿用每篇超时和有限队列；非0可由系统结束长任务，使用前评估未完成处理 |
| powershell_executable | powershell | 仅管理/查询 Windows 任务的程序，不是模型 shell |
| command_timeout_seconds | 30 | 每次管理/查询等待；超时先status查原任务，不能据此直接重复注册 |

环境路径来自 deployment；动作和脚本路径由项目根目录与总配置生成，不手写某台电脑的用户名路径。管理参数作为编码数据传递，不执行模型生成的 PowerShell；安装不提升到管理员、不修改 ExecutionPolicy。

## 状态、日志与安全

- `.runtime/scheduler-state.json`：群组/项目绑定、最近日任务、尝试次数、失败冷却和原流水线报告路径。损坏或别的群组记录会拒绝，不自动清零后再花模型额度。
- `PENDING`表示还有等待/延后，不是全部完成；即使run-once的ok为true，也不停止本日剩余预算内的补查。详见[状态规则](zotero-readiness.md)。
- `.runtime/scheduler-last-result.json`：最近真正进入流水线或发生错误的调度摘要；成功跳过不刷写。`RUNNING` 记录本身不是进程存活证明，应同时看 Windows native_state 或实际 CLI 实例。
- `model_call_count=null` 表示发生过制卡尝试但没有足够信息断言精确模型调用数，另列 generation_attempt_count / theme_model_call_count；零调用时明确0，不把预检失败算成真实模型调用。
- 不自动提交/推送 Git，不修改 Zotero。不设新的 AI 正文结构门槛；已有包和主题步骤由原流程复用。
- 凭据来自既有 Windows 用户环境与 Codex 登录。当前是单机部署约定，不是服务账号、跨机权限或云调度系统；没有Webhook端点。

## 用户故事与验收

### US-11B：每天自行处理并在恢复后补最近一轮

作为导师，我希望电脑在可用时自动处理目标库，让我不必每天记得输入命令。设计依据为本文件和 [统一运行](run-once.md)，不新增用户界面。

1. Windows启动固定仓库入口，无需人工发送 Codex 消息；实际进程使用已安装的项目解释器。
2. 时间、启停和重试参数来自总配置；对当前系统定义读回核对。
3. 同一日任务完成后再唤醒不进入流水线，多日离线仅补最近一轮。
4. 同时的触发被锁拦截；已有手动流水线占用不消耗调度尝试。
5. 失败保留已完成成果，冷却后有限重试；持续失败不无限调用模型。
6. 来源/PDF/旧卡/主题的保护保持原实现，不自动Git写入或晋级正式主题。

### US-11C：可检查、暂停和在新机重建计划

作为维护者，我希望知道是否真的注册和运行，以及如何安全停用，避免只有旧电脑记得运行规则。

1. plan只读；install幂等；同名其他任务拒绝修改或删除。
2. status区分缺失、定义漂移、禁用、上次返回码、最近运行与补跑状态。
3. 明确配置禁用可暂停新轮次，卸载仅移除本项目注册且不杀正在运行的任务。
4. 不保存 Windows 密码、不提权、不修改系统执行策略；任务依赖当前用户登录。
5. 安装/观察超时不意味着原任务未创建，先查询原名称和实际状态。
6. 真实探针与原任务触发留可检查证据；模拟时钟测试不能冒充关机/登录恢复验收。

## 已有证据与未证明范围

真实探针 `69534676ded0437c8706534f11e69ed4` 已由 Windows 启动 pythonw，返回码0，写入正确随机回执，随后移除；45个原运行/知识文件未变，无模型。报告 `.runtime/schedule-probes/verification-69534676ded0437c8706534f11e69ed4.json`。

正式任务已启用，并在2026-09-09 03:45:42通过 Windows 按需启动实际入口；本机状态COMPLETED，三张旧卡跳过、六个主题步骤复用，模型调用0。流水线报告 `.runtime/logs/pipeline-runs/20260908T194542-4c954373dab54f36a66715912a30bde5.json`。再次tick为ALREADY_COMPLETED；再次install只核对，不重复注册。

随后观察到Windows在2026-09-09 04:00:01自行触发检查：04:01的doctor回读LastTaskResult=0、Ready、下次检查04:30；调度状态仍是03:45完成的同一日任务，尝试次数仍为1，没有启动新一轮模型处理。这验证了实际定时轻量检查与已完成日任务跳过；不等于09:00到期生成或关机/登录补跑也已实测。

2026-09-09的09:00到期运行现已核实：scheduler-state记录09:00:02开始、09:00:03结束，slot_date为2026-09-09、attempt_count为1、COMPLETED；流水线报告 [2f68b7c99d1b49b6adff3710d724a82b](../.runtime/logs/pipeline-runs/20260909T010002-2f68b7c99d1b49b6adff3710d724a82b.json) 记录耗时1.48秒、扫描3篇、旧卡跳过3、主题步骤复用6、候选与回填各2、失败/等待/延后均0、模型调用0。日报也在09:00:03更新，日期和最近运行一致。这是实际日界线到期进入原流水线的证据，不是仅启动探针。

随后只读schedule-status回读真实Windows任务为ENABLED、定义一致、Ready、LastTaskResult=0、最近检查10:30:02、下次11:00；日任务仍是09:00完成的同一轮，尝试次数1，due_status=ALREADY_COMPLETED。读取前未手动执行tick、按需启动或更改调度。该结果证明了本次到期执行和其后跳过；本日无新增论文，因此不声称验证了定时上下文中新论文的模型生成，也不证明关机/登录、云端同步或异机恢复。

自动测试覆盖日界线、冷却/次数、崩溃保留尝试、互斥、配置拒绝、定义等价/漂移、外来任务保护。Zotero自动启动/有限等待和待处理補查已有代码及受控测试，真实已就绪库的隔离验证已过；尚未用真实关机/注销/唤醒、应用关闭、云端同步延迟验证全部恢复场景。新电脑完整部署仍需继续工程化。
