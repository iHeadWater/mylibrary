# 任务状态机

## 目的

任务状态机位于 Zotero/PDF 门禁与后续全文提取、证据包生成之间。它只负责记录每篇论文当前处于什么状态、防止重复处理，并为崩溃后的安全重试提供依据。

当前不会因为任务状态为 `READY_FOR_EXTRACTION` 就自动提取全文或生成证据包。

## 身份与唯一性

- `record_id`：`群组 ID + 父条目 Key`，代表一篇 Zotero 论文的长期跟踪记录；
- `task_id`：由 `群组 ID + 父条目 Key + PDF 附件 Key + PDF SHA-256` 计算；
- 同一论文更换 PDF 后，`record_id` 保持不变，`task_id` 改变，并重置为新输入待处理；
- PDF 尚不可用时没有完整输入指纹，因此 `task_id` 可以为 `null`。

## 状态

| 状态 | 含义 | 当前由谁产生 |
|---|---|---|
| `WAITING_FOR_PDF` | 父条目没有 PDF | `tasks-sync` |
| `WAITING_FOR_FILE_SYNC` | Zotero 有附件记录，本机尚无文件 | `tasks-sync` |
| `WAITING_FOR_FULLTEXT` | PDF 存在，Zotero 尚未提供全文索引 | `tasks-sync` |
| `WAITING` | 其他可重试等待情况 | `tasks-sync` |
| `BLOCKED` | 多 PDF、损坏文件或文字不可提取 | `tasks-sync` |
| `READY_FOR_EXTRACTION` | PDF 门禁通过，可以交给全文提取器 | `tasks-sync` |
| `PROCESSING` | 后续处理器已领取任务 | 任务领取接口 |
| `RETRY_PENDING` | 处理失败或租约过期，可以重试 | 任务完成接口或租约恢复 |
| `COMPLETED` | 后续处理器确认处理完成 | 任务完成接口；当前尚无真实处理器调用 |
| `REMOVED` | 父条目已不在目标共享库 | `tasks-sync` |

## 主要转换

```text
发现父条目
  ├─ 无 PDF ─────────────→ WAITING_FOR_PDF
  ├─ 文件未同步 ─────────→ WAITING_FOR_FILE_SYNC
  ├─ 全文未索引 ─────────→ WAITING_FOR_FULLTEXT
  ├─ PDF 不可安全处理 ───→ BLOCKED
  └─ PDF 门禁通过 ───────→ READY_FOR_EXTRACTION

READY_FOR_EXTRACTION ─领取→ PROCESSING
PROCESSING ─成功──────────→ COMPLETED
PROCESSING ─失败──────────→ RETRY_PENDING
PROCESSING ─租约过期──────→ RETRY_PENDING
RETRY_PENDING ─重新领取───→ PROCESSING

任意状态 ─PDF 输入变化────→ 按新 PDF 门禁结果重新确定状态
任意状态 ─父条目移除──────→ REMOVED
```

## 幂等规则

- 相同 Zotero 输入和相同门禁结果重复同步，不新建第二条任务，不重复写相同历史；
- 已经 `COMPLETED` 且输入指纹未变化的任务保持完成；
- PDF 附件 Key 或 SHA-256 变化时产生新的 `task_id`，处理次数清零；
- 任务清单损坏或群组不一致时拒绝覆盖；
- 更新通过临时文件和原子替换完成，避免留下半个 JSON 文件。

## 并发与崩溃恢复

- 更新任务清单前必须取得 `paths.lock_file` 指定的进程锁；
- 仍存活的进程持有的锁不会仅因时间较长而被删除；
- 原进程消失且锁超过 `tasks.lock_stale_seconds` 后，后续运行可以清理死锁；
- 处理器领取任务时获得租约令牌，同一任务在租约有效期内不能再次领取；
- 租约超过 `tasks.lease_seconds` 后，任务可以转为 `RETRY_PENDING` 并重新领取；
- 只有持有当前租约令牌的处理器能够标记成功或失败。

## 数据边界

任务清单和锁分别写入总配置中的 `paths.tasks_file` 和 `paths.lock_file`，默认位于 `.runtime/`，不进入 Git。教师可见的关键贡献事件和阻塞摘要以后由 US-09、US-13 产生，不能直接把完整本地任务文件当作绩效数据上传。

## 当前未接入

- US-05 证据包骨架；
- US-06 完整全文提取；
- 后续 AI 制卡处理器；
- 后台定时调度；
- 面向教师的共享状态摘要。
