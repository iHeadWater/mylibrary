# 水利科研知识平台：约 20 分钟技术实现黑板讲稿

**题目：从一条 run-once 命令，看文献知识平台如何自动运行。**

本稿重点是实际实现：怎样读取 Zotero、建立任务、防止重复、调用 Codex、保存和恢复，以及怎样把主题、定时器和配置接起来。不以产品价值或“为什么设计研究流程”为主线。

正文按第一人称撰写，适合直接练习。时长包含板书与停顿，不含后面的技术答疑；正式汇报前按自己的语速练一遍。备查表不需要全部念。

如果接口、哈希、任务状态、适配器和保存恢复等概念还不熟悉，先读[技术流程逐步解释版](technical-walkthrough-explained.md)。它用一篇论文的多次运行解释每一步，读懂后再用本稿练习 20 分钟汇报。

## 一、黑板布局

先写入口，再沿一篇论文的实际执行顺序展开。分三块区域，不一次写满。

```text
上方：uv run hydro-platform run-once --json   （在仓库根目录运行）
                  ↓
         CLI 解析参数 + config.json → pipeline.run_once()

左：接入与任务                 中：模型执行与保存             右：主题与运行管理

Zotero 本地 API                PDF 路径 + 模板 + 任务          全部有效粗卡
      ↓                             ↓                           ↓
父条目 → PDF → tasks.json      Codex CLI 独立会话              主题计划
      ↓                             ↓                           ↓
等待 / 就绪 / 处理中 / 完成      JSON 中的 Markdown             定向精读或复用
                                    ↓                           ↓
库ID + 父Key                  Python 检查、保存                回填修订
附件Key + PDF哈希                    ↓                           ↓
                              card + manifest + audit         注册表 + 索引

下方贯穿：本地锁｜输入指纹｜步骤记录｜失败恢复｜日志｜配置｜定时器
```

核心句：**AI 完成阅读和分析，Python 管理执行顺序与文件状态。**

左侧讲防重时补“完成 ≠ 有文件夹”；中间讲保存时补“临时文件 → 原子替换”；右侧最后补“每日检查 → 到期才调用同一个 run-once”。长哈希和完整文件路径不写黑板。

## 二、时间安排

| 时间 | 技术内容 | 板书重点 |
|---|---|---|
| 0:00–1:00 | 技术组成与命令入口 | Python 编排，不是人工串命令 |
| 1:00–4:00 | Zotero、PDF 检查和任务状态 | 本地 API → tasks.json |
| 4:00–7:00 | 防重复与完成判定 | 身份、指纹、成果核对、本地锁 |
| 7:00–10:00 | Codex 读取 PDF 并返回卡片 | 路径 + 工具 + 模板 → JSON |
| 10:00–12:30 | 保存、超时与失败恢复 | 待发布记录、原子替换、有限重试 |
| 12:30–16:00 | 统一主题池的执行过程 | 计划 → 精读/复用 → 修订 → 提交 |
| 16:00–18:00 | 多篇一键运行与每日调度 | 固定队列串行、调度复用入口 |
| 18:00–20:00 | 配置、换机部署和测试 | 总配置 + 依赖锁 + 状态恢复 |

## 三、逐段讲稿

### 第 1 段｜0:00–1:00：从一条命令进入代码

#### 板书

```text
run.py → cli.py → config.py → pipeline.run_once()
```

#### 讲稿

老师，我今天重点汇报这个平台在技术上是怎么实现的。我就从日常使用的一条命令讲起：运行 run-once，程序怎样把 Zotero 里的论文处理成证据卡，再接着生成和修订主题。

当前主体是 Python 命令行程序，存储使用 JSON 和 Markdown，文献通过 Zotero 本地接口读取，模型通过 Codex 命令行调用。现在没有另外建设数据库或网页服务。

这条命令首先进入 run.py，再由命令行模块解析参数、读取配置，最后交给流水线函数执行。后面的扫描、制卡、保存、主题和报告，不是我再手动逐个启动，而是由这个函数按条件安排。

我下面沿着一篇新论文走一遍，重点解释程序怎样知道该处理谁、怎样避免重复，以及出错以后怎样继续。

### 第 2 段｜1:00–4:00：怎样找到论文并建立任务

#### 板书

```text
本地 API → 父条目 + PDF 附件 → 文件检查 → tasks.json

等待PDF / 等待同步或索引
          ↓ 满足条件
READY → PROCESSING → COMPLETED
              └→ RETRY_PENDING / 阻塞
```

READY 是板书缩写，代码里叫 READY_FOR_EXTRACTION；不是所有失败都能自动重试。

#### 讲稿

首先，Python 检查本机 Zotero 是否启动、本地接口是否可访问、配置里的共享库是否能读。如果程序没有启动，当前实现可以尝试启动一次，再在有限时间内等待；不会一直重复启动软件。

连接的是本机二三一一九端口，不是直接查询 Zotero 的数据库。程序通过群组编号定位共享库，再分页读取条目。论文的父条目和 PDF 附件是两种记录，附件里有父条目的 Key，所以程序可以把它们对应起来。

这里有一个实现细节：当前一键运行会重新读取可见条目清单，再和本地任务记录对账，不是只听一次“新增事件”，也不是每次都让模型重新读全部论文。这样，今天先入库、明天才补上 PDF 的旧条目，也不会遗漏。

拿到附件记录以后，还要检查本机是否真有这个 PDF，文件是否可读、基本格式是否正常，并计算内容哈希。当前还检查 Zotero 的全文索引是否达到最低长度。这个检查只是判断处理条件，不代替 AI 读全文；扫描版没有可用文本时，目前不会自动 OCR。

没有 PDF 就等 PDF；有附件记录但本地文件没同步，就等同步；若有多个 PDF 不能确定主文件，就先阻塞，不随便选一个。

这些结果写进本机的 tasks.json。它相当于一张持续保存的任务表，里面有论文身份、输入文件、当前状态、尝试次数、最近原因和状态历史。程序不是靠上一次聊天记住进度，而是每次读取这张表。

符合条件的任务进入就绪状态，真正开始制卡时变成处理中，成功保存后才标记完成。后续补文件、重新执行或进程中断，都围绕这套状态处理。

### 第 3 段｜4:00–7:00：防重复不是只判断文件夹存在

#### 板书

```text
论文身份 = 群组ID + 父条目Key
任务身份 = SHA256(群组ID、父Key、附件Key、PDF哈希)

完成 ≠ 有目录
完成成果 = 非占位正文 + 有效manifest + 匹配的内容指纹

整轮锁 + 状态写入锁 + 单篇租约
```

#### 讲稿

防重复在代码里不是一个判断，而是分成几层。

第一层是论文身份。我们不用标题作为唯一标识，因为标题可以修改，也可能相似。当前使用群组编号和父条目 Key 定位论文。证据包文件夹名字里的论文标题只是帮助人识别，真正对应来源的是 Key 和清单记录。

第二层是输入身份。程序把群组、父条目、附件 Key 和 PDF 内容哈希组合起来，再生成任务编号。只要这些输入没变，就对应同一个处理输入。如果文件内容变了，程序能够发现，但不会因此获得覆盖旧卡的权限；发现旧包和新输入不一致时，先保留旧成果并报冲突。

第三层是实际成果核对。这一层解决了之前“有文件夹就以为做完”的问题。程序现在会读取 manifest 和 card，确认不是空白占位、有生成记录，而且实际正文的哈希和清单一致；如果记录了审计文件，也要核对它的指纹。目录存在本身不算完成。

如果成果完整，就跳过模型。如果卡已经保存，但任务表还没来得及写完成，就根据有效成果补齐任务状态。如果记录写着完成、实际文件却缺失或被改动，就报告不一致，不悄悄覆盖。

第四层是防止两个进程抢着处理。同一个本地工作区有整轮运行锁，状态写入时有短锁，每篇任务还有带有效期和令牌的租约。它们分别保护整轮执行、任务表更新和单篇领取。

这些机制保证的是同一条目不会因为重复运行而重复制卡，不是论文语义查重。同一篇论文如果在 Zotero 被建成两个不同父条目，当前程序不会自动证明它们相同。另外这些锁是本地的，还不是多台电脑共同抢任务的分布式系统。

### 第 4 段｜7:00–10:00：Python 怎样让 Codex 读 PDF

#### 板书

```text
PDF 原路径 + 本地读取工具 + 制卡提示词 + 模板包
                         ↓
Python → Codex CLI 独立会话 → 文字提取、页面渲染与看图
                         ↓
JSON {模板信息, 阅读报告, card_body_markdown}
                         ↓
Python 接收；不是 AI 直接写正式目录
```

#### 讲稿

任务就绪后，Python 先通过 Zotero 找到这一次的原始 PDF 路径，并核对它和任务、证据包记录的是同一个输入。PDF 仍然保存在 Zotero 的存储目录，不需要把整份原文件再放到 Git 仓库。

随后程序读取制卡提示词、模板清单和已启用的模板正文，把论文身份、PDF 路径和任务要求一起交给适配器。当前不是先用一次模型做分类，再用另一次制卡；而是在同一个制卡会话里，让 Codex 判断类型并按相应模板完成详细粗卡。

适配器实际启动一个 Codex 命令行子进程，使用这台电脑已经登录的订阅账号。模型名字、思考强度、超时和子进程代理来自配置，不是写在每个业务函数里。

这里的“交给 PDF 路径”也不是远端模型看到路径就自动拥有文件。Codex 需要调用本机工具读取：当前有 Python 的 pypdf 提取文字，有 Poppler 查看 PDF 信息、把页面渲染成图片，再通过看图工具处理图表。路径和这些工具的信息由程序一起提供。默认链路已经不再启动之前的 PDF MCP。

为了让正式成果不被模型随意改写，模型在一个单独的临时工作区运行，临时文字和页面图像可以放在那里，原 PDF 不在这个可写工作区里。会话是独立的，也禁用了额外插件、联网搜索和子 Agent。这里限制的是工具活动，不表示模型调用不需要外网。

模型最终返回一个 JSON 对象，里面包含模板信息、阅读报告，以及一段 Markdown 正文。程序读取执行事件和最终结果，检查来源、正常结束和非空输出，再决定保存。

所以当前边界很明确：正文分析交给 AI，正式文件写入交给 Python。不再因标题顺序或某个固定标签不一致就重做，但输出仍必须能被程序解析，也不能缺少基本来源信息。阅读报告和执行记录是流程依据，不是自动证明模型已经理解正确。

### 第 5 段｜10:00–12:30：可靠保存与失败恢复

#### 板书

```text
模型结果 → 临时文件与校验 → 待发布记录 → 逐文件原子替换
                                      ↓
                               更新任务为完成

card.md        正文
manifest.json  来源、版本、哈希
quality-audit  执行记录，不是科学审稿
```

先确保待发布记录已持久保存，再替换正式文件；上图不是把多个文件当成一个数据库事务。

#### 讲稿

模型返回结果以后，不是打印出来就算完成。Python 会把正文组织成 card.md，把对应的父条目、附件、PDF 哈希、模板版本、模型、提示词版本和正文哈希写进 manifest，同时保存执行审计记录。

保存要处理一个问题：这几个文件不可能天然同时写好。假如卡片写完、清单还没写，电脑就断电了，下一次不能把它当成完整成果，也不应该直接再花一次模型费用。

现在的做法是准备临时文件，检查通过，并在替换正式文件以前保留一份待发布记录，然后逐个用原子替换更新正式文件，最后更新任务状态。原子替换解决单个文件写一半的问题，待发布记录解决多个文件之间的中断恢复问题。它不是数据库事务，但有明确的对账和恢复路径。

下一次运行，若发现待发布记录和现有文件能够匹配，就补齐保存，不重新调用模型；若存在人工修改或者输入冲突，则保留现场并报错。已经做完的其他论文也不会因为这一篇失败而撤销。

对于没有成功拿到完整输出的网络中断或超时，程序只能按允许的错误类型、冷却时间和次数上限重新尝试，不能恢复模型脑中还没输出的内容。当前单次生成时限是二十五分钟，同一输入最多尝试三次，重试冷却一小时，不是在一次运行里无限循环。

终端每分钟输出等待心跳，工具事件和保存结果即时显示，最终生成一份整轮 JSON 报告。因此，一篇保存成功和整轮成功是两个层次，要看最终的完成、跳过、等待和失败计数。

### 第 6 段｜12:30–16:00：证据卡怎样接到统一主题池

#### 板书

```text
全部有效 card + 已有主题 + 可复用精读 + 可选研究目标
                              ↓
                        主题计划 JSON
                              ↓
               按 evidence_id 找原PDF，精读或复用
                              ↓
                       initial → revised
                              ↓
                   CHANGE记录 → 注册表 → index.md

证据包/readings/RD-…     主题只引用
```

#### 讲稿

制卡队列处理以后，一键入口会根据结果决定是否接着运行主题模块。如果有失败、阻塞或同步未就绪等情况，会暂缓主题，保留已有主题；不是每次都用一个暂时残缺的集合重新规划。

进入主题模块后，程序会扫描整个证据包目录，选出当前群组里通过完整性检查的粗卡。所以输入是统一文献池，不只包含刚刚这一批生成的卡。

接下来它会把这些来源记录、粗卡内容指纹、研究目标、模型配置以及主题提示词等组合成一个输入指纹。如果和上一次成功处理的输入一致，就直接复用当前主题，不再调用模型。这个机制也意味着，修改主题提示词或模型配置，可能触发新的规划，而不仅是新增论文才触发。

如果需要处理，程序把全部有效粗卡、已有主题及适用精读交给主题规划模型，要求返回结构化计划。计划里包括新增或更新哪些候选、是否合并拆分、关联哪些 evidence ID，以及每篇论文需要关注什么问题。程序会核对这些 ID 是否真的属于当前文献池，不接受模型随意给出的文件路径。

然后 Python 遍历计划里的精读任务。已有精读是否适用，由模型给出选择和理由，程序核对来源和保存记录；需要新精读时，则按 evidence ID 找到证据包，再定位原 PDF，调用前面同一套本地 PDF 读取适配器。

精读结果存回对应论文的 readings 目录，不复制到每个主题下面。结果绑定了论文来源、精读重点、候选上下文、模型和提示词；同一个输入下已经完成的步骤可以复用。只是换了一个运行批次，不会自动要求全部重读。

精读齐备以后，程序再把初版候选和各篇精读送入回填步骤，生成 revised.md。初版、修订版、来源引用和执行结果都保留，因此主题不是只剩一篇最终文字。

普通更新沿用主题编号、产生新版本；合并拆分则新建编号，保留旧主题和前后关系。这次变更需要的结果都完成后，才提交变更记录、更新统一注册表，再生成阅读索引。如果中途失败，已保存步骤留下，下次输入匹配时继续复用，旧的当前主题仍然可读。

这里所谓“提交”是本地主题池状态提交，不是 Git 提交。候选可以自动演化，已确认正式主题不允许被这个流程直接覆盖；正式确认的专用入口目前还没有做。

### 第 7 段｜16:00–18:00：从分步命令到一键与每日运行

#### 板书

```text
run-once：扫描 → 固定队列逐篇处理 → 主题 → 事件/日报 → 总报告

Windows计划 → 检查今日任务时段 → 到期才 run_once()
                  ↑ 已完成就跳过；失败受冷却与次数限制
```

#### 讲稿

之前我们有扫描、同步任务、建证据包、单篇制卡等分步命令。现在的一键入口不是简单把这些命令用字符串串起来，而是直接调用对应的 Python 函数，共用同一份配置，并根据返回状态决定下一步。

一次运行先取得一份任务队列，然后按顺序逐篇处理。每篇生成完成就保存，再处理下一篇。默认没有每轮篇数上限，不需要我每做一批就改配置。当前是串行处理，不是所有论文同时调用模型；运行途中才新加的论文通常留到下一轮扫描。

如果某篇发生局部错误，会保留已有成果并记录原因；如果是账号、额度或者模型服务整体不可用，则会让后面的待生成任务延后，避免每篇都重复撞同一种错误。最后再记录关键贡献事件、生成日报和整轮报告。

每日自动化是在这条入口外面加一层 Windows 计划任务。配置里每天九点是任务时点，每三十分钟可以唤醒一次检查。检查并不等于每次调用 AI，它先读调度状态，今天对应时段已经完成就退出；失败或等待则受冷却和每日尝试上限限制。

所以手动和定时执行的是同一个核心流程，不是维护两套逻辑。要实际安装计划任务，仍然需要运行安装命令并检查 Windows 中的状态；只把配置改成启用还不够。当前依赖指定电脑和已登录用户运行，也不会自动把成果推到 GitHub。

### 第 8 段｜18:00–20:00：配置化、换机恢复和测试

#### 板书

```text
config.json：位置 / 群组 / 模型 / 强度 / 代理 / 时限 / 调度
依赖锁 → setup → 环境检查 → 从共享成果恢复任务

测试：重复运行、占位卡、写入中断、主题更新、调度补跑
```

#### 讲稿

最后讲工程化的另外两部分：配置和验证。

目前可调整的路径、群组、模型、思考强度、代理、超时以及调度参数，都集中从总配置读取。程序先把相对路径解析成实际位置，再传给各模块，不需要每换一台电脑就在多个函数里改盘符。代理也只通过子进程环境传给这次 Codex 调用，不修改桌面客户端的全局配置。

但配置化不等于任何模型工具只改一个名字就能接上。目前实现的是 Codex 适配器；在它支持的模型之间切换可以改配置，要换成另一家服务，还需要实现对应适配器。密码和登录凭据也不存进仓库。

换机时，Git 恢复代码、模板和已经提交的成果，Zotero 负责同步原 PDF；安装脚本按依赖锁建立项目 Python 环境和 PDF 工具，再检查账号、路径、权限，并根据有效证据包恢复任务记录。这样恢复的是相同执行流程，不承诺模型每次写出相同文字。

工程检查也写成测试，比如连续运行不重复生成、占位卡不算完成、保存中断后能补齐、主题输入不变不调用模型，以及合并拆分保留历史。模拟测试和真实模型运行分开验证，不能互相代替。

因此，这套实现的核心不是只有一次模型调用，而是围绕它补齐了输入身份、任务状态、可靠保存、结果复用、配置部署和统一调度。日常才可以收敛到一条命令，而不用人记住每篇跑到哪一步。

## 四、讲防重时可补画：一篇论文的多次运行

老师追问时用，或替换一部分正文，不是额外增加 20 分钟内容。

| 执行时点 | Zotero / 本机条件 | 程序处理 | 是否调用制卡模型 |
|---|---|---|---|
| 第一次 | 新父条目，还没有 PDF | 建等待任务，记 WAITING_FOR_PDF | 否 |
| 第二次 | 同一条目补上 PDF，同步及索引就绪 | 更新任务输入，绑定附件和 PDF 哈希，生成保存 | 是 |
| 第三次 | 来源和完整成果未变 | 核对有效证据包，已有卡跳过 | 否 |
| 保存中断后 | 匹配的待发布记录，正式文件只完成一部分 | 对账补齐文件和任务状态 | 满足恢复条件时否 |
| 输入冲突 | 同一条目换了 PDF，旧卡已存在 | 保留旧卡，报告来源不一致 | 不自动覆盖重制 |

“否”只指粗卡生成；主题输入变化时，规划或精读可能仍调用模型。

关键区分：**Zotero 文献去重、任务输入识别、完整成果核对、运行互斥，是不同的事。**

## 五、存储示意：成果与运行状态怎样分开

```text
hydro-platform/
├─ config/config.json               总配置；不放账号密钥
├─ automation/
│  ├─ run.py                        命令入口
│  ├─ src/hydro_platform/           各处理模块
│  ├─ prompts/                      阅读和制卡指令
│  ├─ schemas/                      模型与程序的数据交换结构
│  ├─ setup/                        依赖与本地工具锁定信息
│  └─ tests/                        自动测试
├─ templates/
│  ├─ evidence-cards/               论文类型模板及清单
│  └─ themes/                       主题规划、精读、回填的提示词和结构
├─ evidence-packs/
│  └─ EV-父Key-标题片段/
│     ├─ card.md                    通用详细粗卡
│     ├─ manifest.json              来源、输入身份、版本、生成记录
│     ├─ quality-audit.json         执行/流程审计，不是科学质量认证
│     └─ readings/RD-…/
│        ├─ reading.md              定向精读
│        └─ result.json             输入绑定、输出、执行信息、哈希
├─ themes/
│  ├─ _registry.json                主题身份、当前版本与演化关系
│  ├─ index.md                      人阅读的主题入口
│  ├─ changes/CHANGE-…/             一次变更的输入、计划和本地提交记录
│  └─ candidates/TH-…/versions/CHANGE-…/
│     ├─ initial.md                 精读前候选
│     ├─ revised.md                 精读回填后候选，附来源链接
│     ├─ plan.json                  变更与精读计划
│     ├─ manifest.json              版本身份及精读引用
│     └─ revision-result.json       回填步骤结果
├─ activity/                       关键贡献事件
├─ reports/                        日报等共享摘要
├─ members/                        成员映射说明与可选配置，不是学生证据卡目录
├─ docs/hydro-platform/            操作与实现文档（实际位于仓库根，与平台目录同级）
├─ ../.venv/                       仓库根共享 Python 环境；由 uv sync --all-packages 管理，在平台目录之外
├─ .tools/                         当前机器的 PDF 工具
└─ .runtime/                       当前机器运行状态，不进 Git
   ├─ tasks.json                   任务状态、尝试和租约
   ├─ zotero-snapshot.json          独立 scan 命令保存的历史快照
   ├─ scheduler-state.json         每日时段和补跑状态
   ├─ pending-publications/        中断恢复所需的待发布记录
   ├─ generation-drafts/           未验收草稿，不是正式卡
   └─ logs/                       运行和脱敏失败记录
```

上图省略历史试验及其他辅助文件。旧 BATCH-*、旧 readings/TH-* 可以保留为历史，不代表当前按批次隔离主题。PDF 原件位于 Zotero 管理的存储位置。

**不要把 .runtime 笼统称为“随便删的缓存”。** 已发布成果可重建一部分派生状态，但未发布草稿和待发布记录还只在本机，删除会损失恢复材料。

## 六、技术答疑与边界

### 1. 新增检测是不是 Zotero 主动通知系统？

不是。当前是运行时主动读取本地 API，定时器触发同一流程。独立 scan 命令可比较快照，输出 ITEM_ADDED、PDF_ADDED 等事件；run-once 则直接调用 sync_tasks 取得清单、检查 PDF 并对账，不依赖先手动执行 scan。

分页读取也检查接口提供的总数和版本是否一致；途中变化则拒绝将不完整结果当作可靠输入。全量读清单不等于全量制卡。

### 2. 为什么同时有 tasks.json 和 manifest.json？

前者回答“这台机器现在处理到哪里”，后者回答“这份成果来自哪里、怎样生成”。前者本机保存，后者随证据包共享。换机和中断后可以用有效成果修复任务状态，不能只相信 COMPLETED 字样。

证据包当前没有独立 _registry.json，通过父 Key 定位并核对包内 manifest；主题层才有统一 _registry.json。

### 3. 哈希能保证什么？

源 PDF 哈希用于识别输入内容，卡片哈希用于检测保存正文是否变化，任务与主题指纹用于输入绑定和复用。它们不能判断科学结论对错，也不做论文语义查重。

同一个 PDF 放进两个不同父条目，当前仍是不同任务。手改正文造成指纹不匹配时会报冲突，不应再手改哈希绕过检查。

### 4. 原子替换是否保证整个证据包绝对不会失败？

不是。os.replace 只解决单个文件替换，多个文件不是一个数据库事务。临时文件、写入前复核和待发布记录共同支持中断恢复；权限、磁盘和外部修改仍可导致失败。

模型未完整返回、来源冲突或恢复条件不满足时，不能承诺不重跑。恢复的是已保存输出，不是未完成的远端推理。

### 5. 单 Agent 是否代表整个平台只调用一次模型？

不是。单篇粗卡在一个会话中分类并制卡，主题规划、必要精读和回填仍是不同步骤。默认粗卡适配链为 SingleAgentCardGeneratorAdapter → CodexLocalPdfAdapter。

当前不使用旧 PDF MCP，不逐页摘录核验全文覆盖；仍检查文件来源、页数、读取命令事件、阅读报告及输入未变。执行事件不独立证明逐页理解或看图正确。

### 6. 主题如何跨批次，又不每次全重读？

规划输入包含全部有效粗卡、已有主题和适用精读。整池输入不变则跳过规划；变化时由模型选择复用或新增精读，程序核对来源和记录。

步骤结果绑定输入并带哈希，匹配才复用；研究重点在语义上是否仍适用，仍包含模型判断。当前没有向量数据库或检索切片层替代全池输入，不能声称小样本已经验证任意规模。

### 7. 半小时唤醒是否每半小时处理新增文献？

不是。半小时是调度检查频率，九点划分每日到期时段。该时段成功后就不再自动处理；当天后来新增的论文可以手动 run-once，否则通常等下一每日时段。当前不是实时监听。

每日补跑次数和单篇尝试次数是两层限制。需要已安装且匹配配置的 Windows 计划，不能只看配置里的 enabled=true。

### 8. 一键运行是否能消除重连？

不能。子进程代理、事件观察、超时和有限重试不能修复不稳定的网络节点。当前不因重连事件次数直接停止，但单次总时限与无进展时限仍在。

心跳说明本地正在等待，不保证远端持续正常。程序不修改系统 VPN 或桌面 Codex 客户端的全局设置。

### 9. 多台电脑是否能同时生产？

目前是指定主机约定和本地锁，没有跨电脑共享的任务锁或权限控制服务。可以独立副本测试，不能把 Git 共享说成分布式任务协调已经完成。

### 10. 怎样确认工程化规则真的存在？

现有测试包含重复同步、空占位、正文被修改、输入改变、各保存阶段中断、主题无变化复用、合并拆分历史和调度补跑等。技术汇报应把现有测试、真实运行和仍未验证的场景分开。

当前只是核对代码并重写讲稿，没有在本次汇报稿工作中重新运行整个测试套件，也没有触发新的模型任务。

## 七、配置与命令备查

### 当前总配置的关键字段

下面是当前配置值，不是每台机器都应原样复制的通用默认值。

| 字段 | 当前值 | 作用 |
|---|---|---|
| paths.project_root | .. | 相对配置文件目录定位根，其他成果路径据此解析 |
| zotero.group_id | 6618088 | 限定共享库来源 |
| card_generator.adapter / workflow_mode | codex_cli / single_agent | 已实现的适配器与粗卡流程 |
| card_generator.pdf_reader.adapter | local_path | 原 PDF 本地路径读取 |
| card_generator.model / reasoning_effort | gpt-5.6-sol / high | 子进程模型与强度 |
| card_generator.proxy.url | http://127.0.0.1:7897 | 当前机器代理端口，换机需核对 |
| card_generator.generation_timeout_seconds | 1500 | 单次生成时限，不是整轮多篇时限 |
| card_generator.progress.heartbeat_interval_seconds | 60 | 周期等待提示；真实事件即时显示 |
| pipeline.max_items_per_run / max_run_seconds | null / null | 默认不按篇数或整轮时间截断 |
| pipeline.max_attempts_per_item | 3 | 同一输入的任务尝试上限 |
| pipeline.retry_cooldown_seconds | 3600 | 可重试任务冷却 |
| tasks.lease_seconds | 1800 | 单篇任务租约期限 |
| theme_pipeline.enabled / research_goal | true / null | 是否接主题及可选目标 |
| theme_pipeline.model / reasoning_effort | null / null | 当前继承制卡模型与强度 |
| scheduler.daily_time / poll_interval_minutes | 09:00 / 30 | 每日时段及轻量检查 |
| scheduler.retry_interval_minutes / max_attempts_per_slot | 60 / 3 | 调度补跑冷却与每时段上限 |

私人配置要复制完整配置并通过 --config hydro-platform/config/config.local.json 显式选择，不是自动合并。更换服务商需要对应适配器；配置一个名字不等于实现了该服务。

### 黑板只展示一条，其他留作备查

在仓库根目录执行：

```powershell
uv run hydro-platform run-once --json
```

| 命令 | 用途与副作用 |
|---|---|
| uv run hydro-platform run-once --dry-run --json | 只预览本地任务，不扫描最新 Zotero、不调用模型 |
| uv run hydro-platform tasks-list --json | 查看现有任务状态 |
| uv run hydro-platform generator-preflight --json | 检查 Codex、登录及读取工具，不制卡 |
| uv run hydro-platform generator-smoke-test --json | 最小真实模型调用，使用额度，不制科研卡 |
| uv run hydro-platform themes-run --json | 单独推进主题，可调用模型并保存 |
| uv run hydro-platform setup --json | 安装/恢复预检，不实际安装 |
| uv run hydro-platform setup --apply --json | 执行安装恢复；启用调度配置时会处理计划 |
| uv run hydro-platform schedule-plan --json | 预览计划，不注册 |
| uv run hydro-platform schedule-install --json | 按配置安装或更新本项目 Windows 计划 |
| uv run hydro-platform schedule-status --json | 检查实际计划与配置是否匹配 |

--json 让最终结果可供程序读取。进度写 stderr，最终 JSON 写 stdout；两者都在终端显示，不表示进度混入最终 JSON 数据。

## 八、代码定位与测试依据

下表用于讲前复习或答疑，不要按文件名逐个念。

| 技术机制 | 代码定位 | 现有测试入口 |
|---|---|---|
| 统一入口与队列 | `hydro-platform/automation/run.py`、`hydro-platform/automation/src/hydro_platform/cli.py`、`hydro-platform/automation/src/hydro_platform/pipeline.py` 的 run_once | `hydro-platform/automation/tests/test_pipeline.py` |
| API 与分页清单 | `hydro-platform/automation/src/hydro_platform/zotero.py`、`hydro-platform/automation/src/hydro_platform/snapshot.py` 的 fetch_snapshot | `hydro-platform/automation/tests/test_snapshot.py` |
| PDF 就绪及交付 | `hydro-platform/automation/src/hydro_platform/pdf_gate.py`、`hydro-platform/automation/src/hydro_platform/pdf_delivery.py` | `hydro-platform/automation/tests/test_pdf_gate.py` |
| 任务身份、锁和租约 | `hydro-platform/automation/src/hydro_platform/tasks.py` 的 build_task_id、sync_tasks、claim_task | `hydro-platform/automation/tests/test_tasks.py` |
| 证据包定位 | `hydro-platform/automation/src/hydro_platform/evidence_packages.py` 的 find_evidence_package | `hydro-platform/automation/tests/test_evidence_packages.py` |
| 提示词与模板组装 | `hydro-platform/automation/src/hydro_platform/card_generation.py` 的 _build_prompt、generate_evidence_card | `hydro-platform/automation/tests/test_card_generator.py` |
| 单 Agent 与本机 PDF | `hydro-platform/automation/src/hydro_platform/card_generators/single_agent.py`、`hydro-platform/automation/src/hydro_platform/card_generators/codex_local_pdf.py` | `hydro-platform/automation/tests/test_single_agent.py` |
| 完成判定与保存恢复 | `hydro-platform/automation/src/hydro_platform/publication.py` 的 validate_saved_package、recover_publication；card_generation.py 的 _write_generated_package | test_pipeline.py 中保存中断、状态对账和人工修改保护用例 |
| 统一池与步骤复用 | `hydro-platform/automation/src/hydro_platform/theme_pool_runner.py`、`hydro-platform/automation/src/hydro_platform/theme_pool.py`、`hydro-platform/automation/src/hydro_platform/themes.py` 的 _result_record | `hydro-platform/automation/tests/test_theme_pool.py` |
| 每日时段与补跑 | `hydro-platform/automation/src/hydro_platform/scheduled.py`、`hydro-platform/automation/src/hydro_platform/windows_schedule.py` | `hydro-platform/automation/tests/test_scheduled.py`、`hydro-platform/automation/tests/test_windows_schedule.py` |
| 配置、安装和恢复 | `hydro-platform/automation/src/hydro_platform/config.py`、`hydro-platform/automation/src/hydro_platform/workstation_setup.py`、`hydro-platform/automation/src/hydro_platform/runtime_recovery.py` | [验证地图](tests.md)中部署与恢复部分 |

可具体举这三条现有测试：

1. test_repeated_sync_is_idempotent：重复同步不重复建包。
2. test_interruption_during_each_package_write_recovers_without_model：分别在保存阶段中断，符合条件时从记录恢复，不再次调用模型。
3. test_failed_split_is_not_visible_until_all_children_are_refined：拆分未全部完成时，不把半成品变成当前主题池。

完整操作和目录说明见[平台操作说明](platform-operations-guide.md)，主题演化见[统一主题池说明](unified-theme-pool.md)。

## 九、只剩一分钟时的技术总结

> 这套系统以 Python 为编排层，通过 Zotero 本地 API 取得文献和 PDF，用任务状态、来源身份和文件哈希决定是否处理；通过独立 Codex 会话完成阅读，把结果交回 Python 安全保存。主题层读取统一文献池，按计划精读、复用和回填，并保留版本关系。最后用同一个 run-once 入口接起手动执行与每日调度，再通过配置和安装脚本支持换机恢复。所以一键运行，是这些可检查、可恢复的步骤被接成了一条执行链，而不只是把一段提示词发给 AI。
