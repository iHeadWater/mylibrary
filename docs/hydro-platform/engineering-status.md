# 工程化状态与缺口（2026-09-09）

依据：用户最新确认的流程、[PRD](PRD-zotero-to-evidence-pack.md)、[架构](architecture.md)、[恢复要求](recovery.md)，以及实际执行路径与验收记录。使用 intended-vs-implemented 方法核对；文档中的目标不作为已经实现的证据。以下是运行、成本和数据保护边界的核对，不是安全扫描认证。

## 当前结论

本版交付文档已统一更新根目录及17份README，明确单Agent v8、统一主题池、精读/版本存储和本机运行区边界；同时修正架构中残留的独立batch规则。发布前全量540项测试通过（63.961秒），README内部链接检查通过。（其后平台自身的 README 已全部并入 `docs/hydro-platform/`，平台不再保留任何 README 文件；内容未丢弃，见[文档入口](index.md)。）当前版本包含此前未发布的自动化、安装恢复、主题及共享成果；GitHub备份以实际推送后的提交为准，不等于干净新机验收。

统一主题池改造：已取消按BATCH独立生长的主流程，新增长期主题身份、版本链、自动合并/拆分与精读复用。真实2个旧主题接入，35个旧文件未变，模型0；再次运行复用3精读/6步骤。全量540项通过。合并/拆分的过程保护已通过受控测试，真实模型的关联质量尚未验收。[现行规则与证据](unified-theme-pool.md)。此前将主要剩余工作归为换机验收不够全面，不能用工程恢复测试替代这个产品逻辑。

统一池完整入口实测：Zotero原先未运行，既有配置自动启动一次，6.73秒后本地API/共享库可读；跳过3卡、复用6主题步骤、模型0，整轮7.0秒COMPLETED。随后doctor12项通过。未人为关闭应用制造条件；现在已有“未运行→自动启动→流水线继续”的本机证据，仍不证明云端同步、重登录或异机恢复。记录：.runtime/logs/pipeline-runs/20260909T053608-bc83b9d7808b40f3b36496ac1b2c596d.json。

每日到期实测：2026-09-09 09:00由Windows自动进入原流水线，1.48秒完成，3张旧卡跳过、6个主题步骤复用、日报同步更新、模型0。随后回读10:30检查成功且日任务次数仍为1。不是新增论文制卡、关机/登录或异机验收。[完整证据](cron.md#已有证据与未证明范围)。本轮没有更改处理代码或配置，全量523项再验通过（33.241秒）。

统一恢复增量：setup默认只读，--apply将安装、就绪、环境检查、状态恢复与配置中启用的每日计划串接，失败保留已完成步骤。真实同机新路径从源码/共享知识重建依赖和3篇状态，二次安装复用、3卡跳过/6主题步骤复用、无模型，三篇PDF沙箱渲染通过；原45文件不变。523项测试通过。不能把新路径当作干净异机；[证据与边界](workstation-setup.md)。

原生工具增量：bootstrap-native已安装项目内Poppler 26.07.0，锁定下载来源/SHA256，552文件完整性验证和二次复用通过。正式配置已从旧Codex/MiKTeX绝对路径切到项目相对路径。3篇真实PDF全页提取、沙箱首图渲染及PNG查看通过，45原文件/3PDF/旧工具未变，模型0。全新下载与沙箱兼容来自分开运行，早期权限失败及后续下载失败报告均保留；不冒充同一次fresh全链路或干净新机。[记录](native-deployment.md)。

就绪补查增量：run-once现按配置执行Zotero单次启动、有限API/群组等待；待PDF和延后项返回COMPLETED_WITH_PENDING，由调度PENDING有限补查，避免误标全部完成。早期实际已运行库+隔离副本实测3卡跳过、6主题步骤复用、二次调度跳过，45原文件和Zotero进程不变、模型0；当时未覆盖启动分支，现由上方完整入口实测补充。云端同步延迟仍未演练。[证据与边界](zotero-readiness.md)。

调度增量：Windows任务HydroPlatform-qinjiajun已启用，日常09:00、30分钟轻量检查、登录后补最近到期一轮。固定pythonw入口已由Windows按需启动真实流水线，三卡跳过/六主题步骤复用/模型0；二次tick跳过，二次install不改任务。04:00系统自行触发的轻量检查也已观察成功。真实关机/重新登录恢复、干净新机仍有缺口。[调度证据](cron.md)。

部署增量：已实现只读安装计划、项目自有 venv、SHA256 锁定 wheel 安装、二次复用，以及独立真实 PDF 验证。新环境 Python 3.14.6 / pypdf 6.18.0；三篇 16/17/43 页的提取和沙箱渲染通过，45 个原运行/知识文件及三份 PDF 未变；配置已切换项目解释器。仍不是干净新电脑完整部署。[记录与外部前提](deployment.md)。

真实样本已经跑通：3 张粗卡 → 2 个候选主题 → 3 份原始 PDF 定向精读 → 2 个回填修订候选。原卡不覆盖、不自动晋级正式主题。统一入口再次执行，3 张卡跳过，6 个主题步骤复用、模型调用 0。新运行区的全量恢复也已通过。

平台仍未整体交付：计划注册、按需启动、09:00到期运行、随后轻量检查及Zotero未运行时自动启动已有本机证据；定时上下文中新增论文的实际模型处理、关机/登录、云端同步及干净异机完整部署尚未全部验证。关键贡献和老师摘要已接入，真实多人身份受本地API缺字段限制。没有把一个命令通过当作工程化全部完成。

## 需求—实现—验收

| 已确认要求 | 当前实现及证据 | 状态与下一步 |
|---|---|---|
| PDF 到位才制卡；后补 PDF 可继续 | `pdf_gate.evaluate_pdf_gate`、`tasks.sync_tasks`；`hydro-platform/automation/src/hydro_platform/tasks.py` | 3 篇正向真实样本；缺失/未同步/未索引的负面场景由测试覆盖，尚非全套真实故障演练 |
| 只校验流程，不因正文格式重跑 | `hydro-platform/automation/src/hydro_platform/card_generators/single_agent.py`、`hydro-platform/automation/src/hydro_platform/card_generation.py`；当前 v2 / PROCESS_VALIDATED | 已实现；提示词要求区分原文与推理，但不声称机器认证科学正确性。旧六 Agent/严格格式要求已失效 |
| 一篇一个包、旧卡不覆盖、失败可恢复 | `hydro-platform/automation/src/hydro_platform/pipeline.py` 的 `_package_status/run_once`、`hydro-platform/automation/src/hydro_platform/publication.py` | 已实现和回归；真实重复运行无模型调用；无法解释的文件修改保留并报冲突 |
| 候选→每篇定向精读→回填候选 | `hydro-platform/automation/src/hydro_platform/themes.py` 的 `_run/run_themes`；[真实记录](themes-workflow.md#已完成的真实联调) | 已真实跑通；人确认后才能转正式，未开发自动转正，未生成 idea |
| 换机不要为了恢复状态重花模型额度 | `hydro-platform/automation/src/hydro_platform/runtime_recovery.py` 的 `recover_runtime`，只对账本地状态，无模型调用路径 | 本轮补齐；新目录实测恢复3篇，第二轮任务零变化，38个原文件未变；不等同于异机安装验收 |
| 可检查缺哪个依赖 | `hydro-platform/automation/src/hydro_platform/doctor.py` 的 `doctor/_python_probe`，CLI `doctor` | 已有8类基础检查，按配置另查账本/成员映射、Windows计划、Zotero启动路径和项目原生工具，当前12项通过。不启动应用，不是模型/沙箱/科学质量验收 |
| Zotero未运行或PDF未同步时能继续 | `hydro-platform/automation/src/hydro_platform/zotero_readiness.py`单次启动/有限探测，pipeline与scheduled区分待处理并补查 | 已有受控测试、实际就绪库隔离验证，以及本机未运行时自动启动后继续的完整入口实测；不改偏好/账号、不声明云端同步完成。真实下载延迟仍待验证 |
| 每日无人值守、错过计划补跑 | `hydro-platform/automation/src/hydro_platform/windows_schedule.py`注册/核对自有任务，`hydro-platform/automation/src/hydro_platform/scheduled.py`控制每日/补跑，固定pythonw入口调用原run_once | 本机按需及09:00到期原流水线成功，随后轻量检查未重跑；三卡跳过/六步复用/模型0。日界线/有限重试/重复另有测试；真实关机、登录、同步等待及定时新增制卡仍待验证 |
| 砸电脑后只靠仓库、Zotero与重新登录恢复 | `hydro-platform/automation/src/hydro_platform/deployment.py` 与 `hydro-platform/automation/src/hydro_platform/native_deployment.py` 创建项目环境/工具、哈希锁定且不覆盖未知目录；[Python验证](deployment.md)、[PDF工具验证](native-deployment.md) | 部分完成：Python/原生依赖及状态恢复有证据；基础软件准备、异机调度恢复、干净机器完整测试仍缺 |
| 老师看到谁新增、谁补PDF、系统完成什么及每日进度 | `hydro-platform/automation/src/hydro_platform/activity.py`、`hydro-platform/automation/src/hydro_platform/daily_report.py`、[验收](activities-and-daily-report.md)；run-once前后使用同一快照记录并生成摘要 | 已实现基线、去重、未知身份、系统完成/阻塞、跨日未解决事项与最近运行。真实初始3篇/0新事件，日报自动落盘；实际API没有贡献者字段，因此真实多人身份覆盖尚未证明。每日计划已启用，真实调度验收边界见上行 |
| 只有明确要求才推 GitHub | 当前运行/主题/恢复路径均不执行 Git 写入；工作区改动尚未提交/推送 | 边界保留。换机能取回成果以实际备份/推送为前提，不能把本地保存冒充远端备份 |

## 本轮修复的文档偏差

- PRD 和用户故事开头仍残留“六角色”“正文格式必须通过”“只做到证据包”等旧方案，会引导后续 AI 重新引入昂贵且已取消的门禁。更新现行规则并保留历史章节，不再混用。
- 本机配置文件原称“覆盖配置”，但加载器不自动合并。明确使用 `--config` 选择完整文件，避免用户修改后误以为已经生效。
- 原恢复文档写的是目标步骤，现在分别链接已实现的 doctor/recover 和尚未交付的安装/调度，避免高估换机能力。

## 尚未验证的产品假设与边界

- 换机验收需要包含当前源码与共享成果的真实备份，以及可用的干净Windows验收环境。早前HEAD为6ae9e79时，主题/统一流水线/调度/setup模块与依赖锁尚未跟踪，那是发布前的历史状态；用户现已明确授权本版提交/推送。恢复时以实际远端提交核对，不复制私人登录文件代替本人登录。已有同机新路径恢复仍不能代替干净异机验收。
- 关机/注销、关闭正在使用的Zotero不作为自动验收动作；要在用户可配合的窗口验证。程序测试覆盖故障分支，但不把它们说成实际桌面故障恢复已通过。无需为了制造新进展再次运行同样的下载或重读三篇论文。
- 更详细的粗卡是否提升主题的科学价值、怎样的主题由导师判断达标，尚未完成产品效果验收；不能承诺子刊成果。
- 当前通过统一主题池进行增量更新、合并/拆分和有依据的精读复用。输入变化产生新的CHANGE处理记录，不另起独立主题库；无变化不调用模型。仍为小样本全量规划上下文，尚未实现大规模检索/压缩；科学关联与复用适用性由模型判断，不是程序认证。
- 人工确认正式主题仍是权限边界；当前没有专用确认命令，不能由生成 Agent 绕过。idea、OCR、论文/基金全文和实验执行不在当前范围。
- 当前是同一指定制卡机的互斥与写入保护，不是跨多台电脑的分布式写入授权系统。

## 验证记录

统一恢复轮：523项通过（41.038秒）。新项目路径relocated-903ecba2b46e40d8ac3e0e8b34d55ce0首次Python/Poppler均INSTALLED，恢复3篇COMPLETED，后续REUSED；验证器UTF-8及隔离模块导入问题已修复，旧失败记录保留，原目录续跑最终成功。双次完整入口不重做科研结果，三篇PDF首图已查看；未注册第二个自动任务。[完整记录](workstation-setup.md)。

正式项目setup --apply实测READY_SCHEDULED，报告ba6d20791c6947899d347d0584af1af3：安装REUSED、3篇COMPLETED、现有计划ENABLED、最终doctor12项通过；共享知识哈希不变，派生快照按对账更新，无模型调用，未推Git。

原生工具轮：503项全量测试通过（28.358秒），含23项原生安装及2项doctor只读路由新增测试；切换配置后doctor12项通过。实际三篇PDF沙箱读取/渲染通过，原文件保留、模型0，不改系统PATH/ACL、Zotero或调度定义，不推Git。源码核对及交付文档依据intended-vs-implemented与shipping-artifacts方法维护；证据强弱分开，见native-deployment.md。

切换后的隔离全链路复验：readiness-check-cp1tpshc，3卡跳过、6主题步骤复用，二次ALREADY_COMPLETED；模型0、启动0，原45文件和Zotero进程集合不变。不是重新生成科研内容或干净新机验收。

就绪补查轮：478项通过（26.126秒），doctor11项通过；真实隔离副本流水线1.21秒，45个原运行/知识文件及Zotero进程集合未变、无模型和启动调用，报告readiness-check-kvf8_q5b。HTTPError响应现已关闭，本次测试未出现此前对应ResourceWarning。未注册新系统任务、未改Zotero数据/设置、未推Git。[记录](zotero-readiness.md)。
调度轮：449项全量测试通过（25.161秒），doctor含真实计划检查共10项通过。Windows探针启动/回执/移除成功；正式计划已启用并按需执行真实流水线，三卡跳过/六主题步骤复用/模型0。再次tick和install幂等。未重启/注销用户桌面、未改Zotero或推Git。实时注册/状态及未证明范围见 [cron.md](cron.md)。

部署轮：416项全量测试分别在原环境、新项目环境通过；新环境下 doctor 9项通过，三篇真实 PDF 读取/沙箱渲染通过，独立新运行区恢复三篇并二次幂等通过，45个原文件未变，模型调用0。`bootstrap --install` 二次 REUSED，不重装。安装过程未改变旧 Python 或共享知识，验证后仅将总配置读取器指向项目环境。见 [部署验收](deployment.md)。未注册调度、未提交/推送 Git。

本轮最新：400项全量测试通过（23.329秒），doctor当前9项通过。真实统一运行 c4c06b1ad6344e7e86761cf147923faa 跳过3张旧卡、复用6主题步骤、自动维护账本并生成日报，模型调用0。新运行区恢复验收扩展到45个原文件（含账本/日报），全部哈希未变，第二次任务零变化。未增加真实模型调用、未写Zotero、未安装调度或推Git；[操作记录](activities-and-daily-report.md)。

前轮历史：368项通过（21.856秒），含14项恢复和7项检查测试。既有HTTPError 403清理ResourceWarning仍存在，不影响断言通过，但不宣称零警告。真实无模型恢复报告见 [运行维护](runtime-maintenance.md)。
