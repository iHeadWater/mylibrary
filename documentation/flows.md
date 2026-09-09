# 跨边界的实际操作流

仅记录读取外部数据、调用模型、写入知识或安装依赖的流程。静态权限基线见 [permissions.md](permissions.md)，当前没有前端服务器/数据库授权层。

主题行现行替代路径：同一主题锁 → 校验统一注册表/旧成果迁移 → 全部粗卡+已有修订主题+适用历史精读送入规划 → 检查候选修改权限与来源ID → 复用或原始PDF定向精读 → 各主题回填另存 → 不可变变更记录 → 原子更新注册表与统一入口。全部替代结果保存前不退休父主题；正式主题不作为修改对象；旧正文、PDF、粗卡不覆盖。实现是theme_pool.py / theme_pool_runner.py，边界见[统一主题池](unified-theme-pool.md)。下表旧BATCH路径为历史实现，不再由日常入口选择。

| 执行者与前提 | 顺序及边界检查 | 成功副作用 | 拒绝 / 失败处理 |
|---|---|---|---|
| setup，安装操作者，基础软件/账号已备 | 默认只读计划；apply→独立锁→配置指纹/路径→程序登录/就绪→项目依赖→doctor→recover→启用时计划注册→完整doctor | 项目依赖、派生状态、安装报告、配置中启用的任务；无直接模型调用 | 中途配置变化/失败即停、已完成步骤保留；不修改总配置，不生成知识；计划到期仍可能调用模型 |
| run-once在整轮锁内，启动等待已开启 | 本机进程/指定群组只读探测→仅明确缺失时启动配置的zotero.exe一次→有限轮询→原PDF门禁 | 可启动GUI应用；应用自身沿用原同步设置。只写本地运行摘要 | 无权限/错路径停止；不重启、不加账号/配置档参数、不写库；PENDING由调度有限补查 |
| `run-once`，指定制卡机，Zotero 可用 | 整轮锁 → 只读指定群组 → PDF/任务对账 → 事件基线/新增 → 跳过旧卡 → 需要时调用模型 → 已开启时进入主题 | 任务、新证据包、日志、事件/日报及候选 | 持锁不启动；来源变化不覆盖；服务故障有限重试/冷却，保留结果 |
| PDF→卡，Python 调度 Agent | 群组/父条目/附件/哈希复核 → 临时目录交付原 PDF 路径 → CLI 用已登录账号请求外部模型 → shell/页面图像读取 → 完成且非空返回 → 来源复核与发布 | 模型额度、临时草稿、card/manifest/审计 | 无 PDF、未完成/空输出不发布；标题/标签不拦截，草稿先保全 |
| 粗卡→主题，Python 编排 | 输入指纹 → 文本会话生成候选计划 → 每个主题关联 PDF 分别定向精读 → 根据精读回填修订 | `themes/candidates/BATCH-*`、包内 `readings/TH-*` | 来源不符/人工改动保留；完成步骤可复用；不转正式，不生成 idea |
| 事件/日报，Python，无模型 | API 明确身份或系统标识 → 首次基线 → 稳定事件 ID 去重 → 任务与最近运行合成摘要 | `activity/ledger.json`、`reports/daily` | 不从论文作者猜操作者；无身份记未知；文件冲突保留 |
| `recover`，新机/制卡机，源库与成果已取回 | 统一/主题互斥 → 原始 PDF 对账 → 持久化证据包核对 → 重建任务/快照 | 仅派生状态，无模型 | 来源冲突不覆盖共享文件；dry-run 不写；未备份结果不能凭空恢复 |
| `bootstrap`，操作者，基础 Python 已有 | 默认只读计划 → --install 才加锁 → 自有 venv → 锁定 HTTPS wheel 校验 → 离线哈希安装 → 隔离/版本检查 | 项目环境、缓存、安装记录/锁 | 未知目录/漂移/哈希不符停止；同版本中断可续装，不切生产配置 |
| `bootstrap-native`，操作者，Windows x86_64 | 默认只读 → --install加锁 → 固定HTTPS发布包及重定向白名单 → 大小/SHA256 → 全归档路径/大小检查 → 自有目录不覆盖发布 → 全文件/版本检查 | `.tools/poppler`、缓存、安装清单/锁 | 未知目录、越界ZIP、哈希不符、文件漂移停止；不改系统PATH/ACL/账号，不切生产配置 |

## 代码和日志

- 入口 `cli.py`；写入在 `pipeline.py`、`publication.py`、`themes.py`、`activity.py`、`daily_report.py`。
- 模型命令与工具限制在 `card_generators/codex_local_pdf.py`、`codex_text.py`，固定沙箱预检在 `pdf_sandbox.py`。单 Agent 详细粗卡不是逐卡人工审批流程。
- 运行摘要在 `.runtime/logs/pipeline-runs/`、`theme-runs/`；脱敏错误在 `.runtime/logs/`。已发布主题步骤在共享知识目录，不依赖临时日志续跑。
- 安装在 `deployment.py` 与 `automation/setup/dependencies.lock.json`，见 [部署说明](deployment.md)。无模型的独立部署兼容性验证不加入日常制卡链路。
- 原生工具安装在 `native_deployment.py`，锁在 `automation/setup/native-tools.lock.json`；[验证和限制](native-deployment.md)。调用这些下载文件是供应链执行边界，不把哈希等同于独立安全审计。
- Windows每日计划已部署：当前用户交互令牌→固定pythonw仓库入口→日任务状态/锁/冷却→原run_once。管理入口核对项目归属，未知同名任务不修改；不保存密码。详见 [实际计划与未验证场景](cron.md)。Git 推送不是任何自动入口的附带动作。
