# 每日摘要

同一天一对文件：

- YYYY-MM-DD.md：给老师阅读。
- YYYY-MM-DD.json：结构化数据，方便程序检查、恢复和后续汇总。

内容包括当日新增事件、完成卡片、等待/阻塞、最近运行及主题处理状态。日期划分来自 activity_reporting.utc_offset_minutes；当前为 UTC+08:00。

run-once 自动刷新；也可在项目根目录运行：

    python automation/run.py daily-report --json

这条命令不调用模型，不会为缺卡自动制卡，也不注册计划。每日触发已由 Windows 计划实现，状态以 schedule-status 为准。

不要在生成的 Markdown 里写个人笔记：检测到人工改动时程序会保留并停止覆盖。日报和事件账本可提交共享；原始日志留在 .runtime。

[事件与日报](../../documentation/activities-and-daily-report.md) · [调度与暂停](../../documentation/cron.md)
