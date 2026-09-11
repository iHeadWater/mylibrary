# 换机恢复

完整恢复需要三类输入：Git 中的可复现资产、Zotero 共享库及本地同步 PDF，以及 Git 之外的持久化科研产物备份。只克隆 GitHub 不能恢复证据卡、主题、事件账本和日报，因为这些运行产物被 `.gitignore` 明确排除。

## 恢复输入

| 来源 | 需要取回的内容 | 不应取回的内容 |
| --- | --- | --- |
| GitHub `iHeadWater/mylibrary` | 代码、依赖锁、模板、Schema、测试、文档和非敏感团队配置 | 旧机器的 `.venv`、`.tools`或 `.runtime` |
| Zotero | 目标群组条目、附件身份和同步完成的 PDF | 不经校验的本地数据库拷贝 |
| Git 外备份 | `paths.evidence_packs_dir`、`themes_dir`、`activity_dir`、`reports_dir`、`members_dir` 下的持久化成果 | 密钥、未脱敏原始日志和无法解释来源的零散文件 |
| 本机凭据存储 | Zotero、Codex 和可选服务所需的账号或环境变量 | 写进仓库配置的 Token 或密码 |

合并后新增的 `artifact_root/证据卡/主题/运行记录/文献链接` 契约目前还没有与 `hydro-platform` 自动化发布链接通。如果这些目录中已有人工或 Skill 产物，它们也必须作为 Git 外资产单独备份，不能假定 `recover` 会自动重建。

## 恢复步骤

1. 在新 Windows 机器上克隆仓库，切换到需要的分支，运行 `uv sync --all-packages`。
2. 安装并登录 Zotero，确认目标群组和 PDF 已同步；登录 Codex CLI，从本机凭据存储恢复所需环境变量。
3. 恢复 Git 外科研产物到配置指定的原路径，不要先创建空主题池或重编号。
4. 检查 `hydro-platform/config/config.json`；个人覆盖应使用被 Git 忽略的完整配置文件并通过 `--config` 显式选择。
5. 运行 `uv run hydro-platform setup --json`预览，确认后运行 `uv run hydro-platform setup --apply --json`。
6. 运行 `uv run hydro-platform doctor --json`，核对 Python、模板、Zotero、Codex、PDF 工具和路径。
7. 运行 `uv run hydro-platform recover --dry-run --json`预览全量对账，再运行 `uv run hydro-platform recover --json`重建快照和任务。
8. 受控运行一次 `uv run hydro-platform run-once --json`，确认已完成卡被复用、待处理条目没有丢失。
9. 需要定时运行时，重建计划任务并用 `schedule-status --json` 读回验证。

## 恢复边界

`recover` 可以根据 Zotero 与完整证据包重建 `.runtime` 中的派生状态，但它不会：

- 从 Git 恢复被忽略且从未备份的证据卡、主题、账本或日报；
- 找回旧机器上未发布的 Codex 会话或未备份草稿；
- 为来源冲突的证据包自动选择“正确版本”；
- 自动把候选主题转为正式主题；
- 证明模型科学理解、真实关机/登录恢复或干净异机全链路已验收。

## 验收标准

- 已完成的证据包和主题没有因换机被重制或重编号。
- 补齐 PDF 的旧条目和新条目都能重新进入正确任务状态。
- 重复执行恢复不产生重复证据包、重复事件或不必要模型调用。
- 认证失败、PDF 不完整、产物缺失和人工修改冲突都以可操作阻塞呈现，不被写成成功。
- 计划任务在目标机器上真实存在，且最近状态可通过命令读取。

恢复实现已有自动测试和同机隔离验证，但这不证明当前机器拥有正确的计划任务，也不证明干净异机和真实关机/重新登录已经通过。当前覆盖与缺口见[验证地图](tests.md)。
