# 每日运行与 Windows 调度

`hydro-platform` 已实现 Windows 计划任务的预览、安装、读回校验、到期运行、有限补查和移除。`scheduler.enabled=true` 表示配置期望启用，不表示当前机器已有属于本仓库的计划任务。真实状态必须以 `schedule-status --json` 的读回结果为准。

## 任务清单

| 工作 | 触发 | 执行内容 | 幂等与重试 | 观察位置 |
| --- | --- | --- | --- | --- |
| 轻量到期检查 | 每日时点、按配置轮询、登录后延迟 | 判断今日时槽是否需要运行 | 同一时槽已完成则只读跳过 | `schedule-status --json` |
| 知识流水线 | 到期且未完成 | 进入与手动 `run-once` 相同的流程 | 失败或仍有等待时，按冷却和次数上限补查 | `.runtime/scheduler-state.json`、pipeline 报告 |
| 事件与日报 | 流水线结束 | 同步关键事件并刷新当日摘要 | 不因日报失败重做已成功卡片 | `paths.reports_dir/daily/` |

轮询间隔是检查间隔，不是每次都调用模型。Windows 不会自动登录账号、唤醒已关机电脑或保证 Zotero 附件已同步。

## 操作入口

```powershell
uv run hydro-platform schedule-plan --json
uv run hydro-platform schedule-status --json
uv run hydro-platform schedule-install --json
uv run hydro-platform schedule-tick --json
uv run hydro-platform schedule-remove --json
```

- `schedule-plan` 只生成预期定义，不注册、不调模型。
- `schedule-status` 读取 Windows 真实定义、上次结果、下次检查和本日时槽状态。
- `schedule-install` 安装或更新本项目的任务；预期定义已一致时不改动。
- `schedule-tick` 手动执行一次相同的到期判断，不绕过每日幂等保护。
- `schedule-remove` 只移除能证明归属于当前项目的任务，不删知识产物和依赖。

## 归属与冲突保护

计划任务的名称并不足以证明归属。程序还会核对任务描述中的所有权指纹、执行程序、参数、工作目录和当前配置。遇到同名但指向另一个克隆、另一份配置或未知任务时，`status`、`install`和`remove`必须返回 `SCHEDULE_OWNERSHIP_CONFLICT`，不覆盖、不删除、不杀死运行进程。

这个保护尤其适用于仓库迁移或封存后的旧计划任务。如果需要将调度迁移到新克隆，应将它作为独立的迁移操作：先确认旧任务的归属和停用窗口，再决定是变更 `task_name` 还是经明确授权移除旧任务。不得因为新分支配置了同名任务就自动接管。

## 配置与安全

| `scheduler` 字段 | 作用 |
| --- | --- |
| `enabled` | 是否允许安装和到期执行 |
| `task_name` | Windows 任务名；改名不会自动删除旧名称 |
| `daily_time` | 每日时槽分界，使用电脑本地时间 |
| `poll_interval_minutes` | Windows 轻量检查间隔 |
| `retry_interval_minutes` | 流水线失败或待处理后的补查冷却 |
| `max_attempts_per_slot` | 同一日任务的尝试上限，包含首次 |
| `logon_delay_seconds` | 用户登录后的等待时间 |
| `execution_time_limit_seconds` | Windows 对整个进程的可选时限；`0`表示不另加限制 |
| `powershell_executable`、`command_timeout_seconds` | 管理计划任务的固定程序和超时 |

安装时使用当前 Windows 用户的普通交互令牌，不保存 Windows 密码，不修改 ExecutionPolicy，不自动提权。模型凭据仍来自本机 Codex 登录。计划任务不执行 Git 提交或推送，也不把候选主题晋级为正式主题。

## 验证边界

自动测试覆盖日界线、冷却与次数、锁互斥、定义等价与漂移、外来同名任务保护和配置拒绝。每台机器仍需通过 `schedule-status` 确认任务归属和实际运行状态。真实关机/重新登录、云端 PDF 同步延迟和干净异机恢复仍是未验证项，见[验证地图](tests.md)。
