# Zotero 启动、等待与待处理补查

## 当前行为

`run-once` 在整轮互斥锁内进入 `zotero_readiness.ensure_zotero_ready`。当前总配置已启用；定时任务调用同一入口，不需要增加日常命令。`doctor`、`preflight`、`recover` 和 `run-once --dry-run` 不启动应用、不做自动等待。

1. Zotero和指定共享库已经可读：立即继续，不重启、不固定等待120秒。
2. 明确未发现Zotero进程：若配置允许，本轮只启动一次本机 `zotero.exe`；使用无shell参数列表及隐藏窗口启动请求，不加其他配置档或账号参数。应用本身仍可能显示登录或错误窗口。
3. 进程已有但API未就绪、目标群组暂不可见：只轮询，不再启动另一个实例。每5秒检查，默认总等待预算120秒，受整轮剩余时限进一步约束。
4. 无权限、接口格式错误等非等待问题直接报告；超时报告 `ZOTERO_READY_TIMEOUT`，保留原因代码，不制卡、不修改任务。

**本地API可访问不等于云端同步已完成。** 当前没有可靠的云端“全部同步完成”信号；不会用等待几秒或群组非空冒充同步证明。Zotero自身按用户已有设置同步；程序不改偏好、不代登录、不调用写库接口。

## 总配置

所有字段在 `hydro-platform/config/config.json` 的 `zotero.startup` 中，由 `config.py` 读取。修改后下一轮生效；不需要重新注册Windows任务。

| 字段 | 当前值 / 含义 | 边界 |
|---|---|---|
| enabled | true，启用就绪等待 | false恢复原单次预检；旧配置省略本节默认false |
| launch_if_missing | true，允许缺失时启动 | false只等待，不启动；不影响已打开Zotero的读取 |
| executable | null，按PATH和Windows常用安装目录查找 | 可填写完整zotero.exe路径；相对路径以项目根目录为基准。显式路径无效不偷偷换另一个程序，不附加命令参数 |
| wait_timeout_seconds | 120秒 | 有限正数，最多600秒；只限制应用/API等待，不代表等待所有附件下载 |
| poll_interval_seconds | 5秒 | 有限正数，最多30秒，不得超过等待预算 |

`doctor`启用时额外核对启动程序能否定位，仍不启动或重启Zotero。禁用自动启动不会移除系统程序、退出应用或更改同步设置。

## PDF等待和完成状态

| 观察结果 | 本轮制卡与主题 | 后续 |
|---|---|---|
| 尚未添加PDF：PDF_MISSING | 不制这张卡；已有完整粗卡仍可生成主题，避免被长期缺文献拖住 | 保留等待项，有限补查 |
| PDF尚未到本机：PDF_FILE_NOT_SYNCED | 不制这张卡；暂缓自动主题，避免用同步中的不完整卡片集反复生成批次 | 后续扫描文件就绪后继续 |
| 尚无全文索引：FULLTEXT_NOT_INDEXED | 当前既有门禁保持，不制卡；暂缓自动主题 | 后续扫描索引就绪后继续；不是独立全文覆盖证明 |
| 其他任务正处理、冷却中、达到本轮数量/时间限额 | 保留等待/延后项，已有结果不重制 | 冷却后按原来源与重复检查续跑 |
| 所有可处理项完成且无等待/延后 | 正常完成；相同主题输入复用已保存步骤 | 当日调度跳过 |

有等待/延后但没有运行错误时，`run-once`返回 `ok=true, status=COMPLETED_WITH_PENDING`，并给出数量；这表示本轮正常结束，**不是全队列完成**。调度保存 `PENDING`，从本轮结束起按 `scheduler.retry_interval_minutes` 冷却后补查。报告给老师时也显示“仍有等待或延后项”。

当前每个日任务含首次最多3次，无论是在等待还是失败，都不无限进入流水线；到上限显示 `ATTEMPTS_EXHAUSTED`，保留全部待处理项，下一日再查。论文自身的累计模型次数保护继续生效。手动 `run-once` 可随时主动再扫描，已有卡和完成主题步骤不重做。

本轮扫描是固定队列；扫描之后才进入本地库的新条目，或本日达到补查上限后才补齐的PDF，默认下一日处理。当前不承诺实时或云端最新全量覆盖。

## 日志与故障定位

- `pipeline-runs/*.json` 的 `zotero_readiness.startup`：是否尝试启动、进程ID、轮询次数、等待时间和预算。启动器退出可能只是交接给另一进程，以后续API探测为准，不仅凭退出码判失败。
- `scheduler-state.json`：`PENDING`、`pending_count`、`next_retry_at`、次数及流水线报告路径。`schedule-status`显示等待警告，不把可用的计划定义当作全队列成功。
- 常见错误：`ZOTERO_EXECUTABLE_NOT_FOUND`（配置路径/安装缺失）、`ZOTERO_START_FAILED`（进程创建失败）、`ZOTERO_READY_TIMEOUT`（有限等待已到）、`GROUP_PERMISSION_DENIED`（账号权限）。不在错误后自动重置或重复制卡。

## 验证方式与剩余边界

`test_zotero_readiness.py` 覆盖已就绪不启动、仅一次启动、API/群组延迟、有限预算、权限失败、配置拒绝和隐藏窗口参数；`test_pipeline.py`、`test_scheduled.py` 覆盖待 PDF 后续补齐、旧卡复用、冷却和次数；`test_doctor.py` 保证只定位程序而不启动应用。可运行：

```powershell
uv run pytest hydro-platform/automation/tests/test_zotero_readiness.py hydro-platform/automation/tests/test_scheduled.py hydro-platform/automation/tests/test_doctor.py -q
uv run python hydro-platform/automation/verify_zotero_readiness.py
```

隔离验收只针对当前机器与已有成果复用，不代生成科研内容，也不能证明真实附件从云端下载中恢复、关机后重新登录、干净新机首次登录或科学质量。相关：[调度](cron.md)、[验证地图](tests.md)。
