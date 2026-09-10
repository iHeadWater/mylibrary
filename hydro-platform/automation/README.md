# 自动化程序

当前完整流程：指定 Zotero 共享库 → PDF 就绪 → 单 Agent 详细粗卡 → 统一主题池规划 → 必要精读/适用精读复用 → 回填候选 → 关键事件与日报。

日常不需要逐条运行 US-01～US-07；这些编号是历史实施拆分，不是使用步骤。

## 常用入口

以下在项目根目录运行，统一前缀为 python automation/run.py：

| 子命令 | 用途 / 副作用 |
|---|---|
| run-once --json | 一键处理本轮全部可制卡论文、衔接主题、记录贡献并刷新日报；可能调用模型 |
| run-once --dry-run --json | 只预览已有本机任务，不扫描、不调用模型 |
| themes-run --json | 单独推进统一主题池；输入变化时可能调用模型 |
| themes-run --dry-run --json | 只读主题预览，不写入、不调用模型 |
| themes-run --migrate-only --json | 接入已有完成主题并保存注册表，不调用模型 |
| doctor --json | 只读环境、登录、共享库及计划检查，不调用模型或启动应用 |
| recover --json | 全量对账 Zotero 与本地共享成果，重建派生任务/快照，不重做科研结果 |
| setup --json / setup --apply --json | 安装恢复的预览 / 执行；执行可能下载依赖、启动 Zotero、按配置恢复计划 |
| schedule-status --json | 查看真正的 Windows 计划定义与最近状态 |
| activity-sync --json / daily-report --json | 单独维护关键事件 / 日报，不调用模型 |

模型结果完成后直接正式保存，不要求逐篇手动搬文件。已有粗卡不覆盖；主题无变化不调用模型。实时进度写 stderr，最终 JSON 写 stdout，--no-progress 关闭本次进度。[完整操作手册](../documentation/operator-manual.md)。

## 代码地图

核心代码位于 src/hydro_platform/：

| 模块 | 职责 |
|---|---|
| cli.py、pipeline.py | 命令解析、完整流水线、整轮锁与数量/时间/重试限制 |
| zotero.py、zotero_readiness.py、snapshot.py | 只读群组访问、单次启动/有限等待、条目与附件变化检测 |
| pdf_gate.py、pdf_delivery.py | PDF 就绪、身份/指纹检查及原始路径交付 |
| tasks.py、evidence_packages.py | 派生任务状态、证据包骨架、重复与已完成保护 |
| card_generation.py、card_generators/single_agent.py | 详细粗卡编排、来源和非空输出检查 |
| card_generators/codex_local_pdf.py、codex_text.py | 当前 Codex CLI 的 PDF 路径读取和纯文本步骤适配 |
| themes.py、theme_pool_runner.py、theme_pool.py | 主题入口、全池规划、精读/回填、稳定编号、版本/演变及原子发布 |
| publication.py、draft_recovery.py、runtime_recovery.py 等 | 安全保存、草稿和本地状态恢复；冲突不覆盖 |
| activity.py、daily_report.py | 关键贡献账本和面向老师的摘要 |
| scheduled.py、windows_schedule.py | 到期检查、有限补查、Windows 计划安装/查询/移除 |
| deployment.py、native_deployment.py、workstation_setup.py | 锁定 Python/PDF 依赖安装和统一恢复 |
| doctor.py、progress.py、failure_records.py | 环境检查、实时进度及脱敏失败记录 |

run.py 是用户命令入口，scheduled_run.py 是 Windows 的固定后台入口。它们进入同一套流水线，不另建知识池。

## 提示词、模板与机器协议

- [prompts/](prompts/README.md)：当前 v8 制卡指引和共用 PDF 路径阅读指引。
- [schemas/](schemas/README.md)：模型传输结构及证据包清单格式。
- [../templates/evidence-cards/](../templates/evidence-cards/README.md)：八类详细粗卡模板及来源版本。
- [../templates/themes/](../templates/themes/README.md)：统一主题规划、定向精读及回填模板。
- [setup/](setup/README.md)：依赖下载来源、版本和 SHA-256 锁。
- tests/：自动化回归；verify_*.py：显式运行的环境/恢复演练，可能创建隔离目录或下载依赖，不是每日工作步骤。

当前协议 rough-card-single-agent-v2 / unified-theme-pool-v1。原多 Agent、MCP 和按批次生成的旧路径保留历史兼容/迁移测试用途，不由当前正常配置自动选择或失败回退。

## 维护与边界

模型、思考强度、超时和路径来自 [总配置](../config/README.md)。当前适配器仅 codex_cli；填写另一个 API 名称不会自动得到新适配器。

日常命令不改 Zotero 文献/偏好，不自动转正式主题、不生成 idea、不执行 Git 提交或推送。制卡可按配置启动本机 Zotero，并调用登录的 Codex 账号处理 PDF；不是完全离线运行。Windows 计划的启用不依赖 Codex 对话窗口，但依赖已登录的 Windows 用户与有效账号。

程序只校验来源、非空输出、路由和写入流程，不以正文排版/归因标签作为保存门槛。保存通过不代表机器已独立验证论文理解。

[统一主题池](../documentation/unified-theme-pool.md) · [每日调度](../documentation/cron.md) · [安装恢复](../documentation/workstation-setup.md) · [验证与缺口](../documentation/tests.md)
