# 环境检查与本地状态恢复

所有路径、共享库和运行参数读取同一个 `hydro-platform/config/config.json`。本页两个命令不调用模型、不修改 Zotero、不写共享卡片或主题、不提交/推送 Git，也不安装定时任务。

## 日常检查

在仓库根目录运行：

```powershell
uv run hydro-platform doctor --json
```

检查主程序 Python、当前单 Agent/本地 PDF 工作流、九类模板来源清单、提示词与输出结构文件、本地任务/快照、Zotero 群组、Codex CLI 登录及 PDF 工具路径、实际读取 PDF 的 Python/pypdf。

开启 activity_reporting 后另查贡献账本和可选成员映射；当前总计12项。缺少贡献者元数据时不会为了“检查通过”猜测人名。[事件与日报](activities-and-daily-report.md)。

`ok=true` 表示这些运行前置检查通过。它不消耗模型额度，也不证明模型服务当时连通、Windows 沙箱可以读取某篇 PDF、AI 读懂了论文、定时任务已部署或换机安装已成功。缺失的 `.runtime` 是允许的；损坏或属于其他群组的状态文件会报告失败，命令不会修复它们。依赖版本偏离时只提示，不自动安装。

## 运行状态丢失后恢复

先确保仓库成果已从备份取回、Zotero 登录正确账号、共享库和 PDF 已同步。不要为测试删除正在使用的 `.runtime`。

```powershell
uv run hydro-platform recover --dry-run --json
uv run hydro-platform recover --json
```

注意：`recover --dry-run` 会只读访问 Zotero，预览全量对账，但不写文件、不占用运行锁；因此只是瞬时预览。`run-once --dry-run` 则只看本地任务，这两者不同。

正式恢复命令会：

1. 拒绝抢占统一运行实例、主题运行实例或有效单篇租约；
2. 读取全部当前父条目，检查 PDF 是否到位及其真实哈希；
3. 用群组、父/附件 Key、PDF 哈希和任务标识核对共享证据包；
4. 完整且未改动的粗卡恢复为 `COMPLETED`；未制卡的可读 PDF 留在 `READY_FOR_EXTRACTION`；缺 PDF、未同步和未索引分别等待；
5. 建立扫描基线，不把历史文献输出成当日新贡献；
6. 只保存本地任务、快照和恢复报告。不会创建占位包、重制卡、自动恢复写到一半的共享文件或运行主题。

遇到来源不一致、重复证据包、已有卡被修改、损坏状态记录等冲突，保留现场，不覆盖本轮任务和快照。文件系统错误可能发生在两个原子状态文件写入之间；`state_files_written` 明确列出已经落盘的文件，修复本机问题后重复 `recover` 即可对账，不需要清空目录。报告路径在 `report_path` 中。

`ok=true` 是“恢复操作成功”，不表示所有论文都可以制卡；请看 `counts` 中的等待和阻塞状态。恢复后，正常推进仍使用：

```powershell
uv run hydro-platform run-once --json
```

已保存的主题步骤由主题目录及各论文 `readings/` 中的结果记录复用，不依赖恢复日志；`recover` 本身不验证或改写主题。未备份的本地草稿/未完成会话不能靠恢复命令找回。

## 不破坏当前状态的恢复验证

```powershell
uv run python hydro-platform/automation/verify_runtime_recovery.py
```

脚本在配置运行区下创建新的 `recovery-trials/recovery-check-*` 目录，连续恢复两次，比较任务是否幂等，以及原任务、快照、证据包和主题文件的哈希是否未变。验收目录和 `verification.json` 保留；不清理原运行区，不调用模型。自动规则可另用 `uv run pytest hydro-platform/automation/tests/test_runtime_recovery.py -q` 验证。

这是同机新运行目录验收，不能替代另一台电脑的依赖安装、账号登录、成果备份和自动调度恢复。事件账本也必须实际备份，才能在换机后保留去重历史。

## 其他配置文件

所有命令都可显式指定完整配置，例如 `uv run hydro-platform doctor --config hydro-platform/config/config.local.json --json`。`config.local.json` 不会自动加载，也不会与 `config.json` 合并。它是另一份完整总配置，不是只填几个覆盖字段的补丁文件。
