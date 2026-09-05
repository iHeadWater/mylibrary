# 总配置

`config.json` 是自动化唯一的团队级总配置入口。需要迁移目录、更换 Zotero 本地接口、调整扫描参数时，只修改这个文件，不修改程序源码。所有路径字段必须显式填写；缺失时程序直接报配置错误，不使用源码中的隐含目录默认值。

以后实现 Codex 制卡、其他模型适配器、Git 同步、定时调度和报告时，凡是团队可能主动调整的非敏感参数，也必须加入这个总配置并由代码读取，不能写死在源码或命令中。新增配置项必须和对应的解析校验、功能实现、测试及本说明同时交付；禁止先放入程序并不读取的“假配置”。

配置只能在程序已经实现的能力之间切换。例如将制卡后端从 `codex_cli` 改为另一种适配器，前提是仓库中已经存在并测试过该适配器；任意填写一个 API 名称不能凭空获得相应能力，程序必须对不支持的值立即报错。

其中 `paths.project_root` 相对于 `config.json` 所在目录解析；其余路径相对于 `project_root` 解析。因此，从仓库外部工作目录调用程序时，产物仍会写入正确项目。为避免误写，所有项目路径必须位于 `project_root` 内，运行快照、任务、锁和原始日志还必须位于 `runtime_dir` 内。

当前可配置项：

- `paths`：项目根目录、运行区、快照、任务、锁、日志，以及证据包、模板、主题、成员、事件、报告、提示词和数据结构目录；
- `zotero`：本地 API 地址、目标共享群组 ID、HTTP 超时和进程检查超时；
- `scan.page_size`：每页读取条目数；
- `pdf_gate`：最小 PDF 体积、最小可提取文字数和计算哈希时的分块大小；
- `tasks`：处理租约时长、死锁恢复时间和每篇论文保留的最大状态历史条数。
- `card_generator`：当前已注册的制卡适配器、Codex CLI 可执行程序、认证方式和预检超时。

后续功能实现时计划补充但当前尚未生效的配置类别：

- `card_generator` 的制卡字段：模型、推理强度、真实调用超时、重试策略、提示词和输出结构路径；这些字段要等 US-07B 有实际消费代码时再增加；
- `git`：远端、分支和自动同步策略；
- `scheduler`：每日运行时间、错过后的补跑规则和并发限制；
- `reports`：摘要生成范围和保留规则。

Codex 登录凭据、Zotero API Key、GitHub Token 等秘密只能存放在制卡机本地凭据存储或环境变量中，不得提交到仓库。`config.json` 最多记录所使用的凭据类型或环境变量名称，不能记录秘密本身。

当前 `card_generator` 字段说明：

| 字段 | 当前含义 | 允许值或规则 |
|---|---|---|
| `adapter` | Python 调用哪一种制卡运行时适配器 | 当前只能是 `codex_cli` |
| `executable` | 要查找和运行的 Codex CLI 命令名或路径 | 默认为 `codex`；非空字符串 |
| `auth_mode` | 本阶段能够确认的认证方式 | 当前只能是 `chatgpt_account` |
| `preflight_timeout_seconds` | 版本和登录状态两项检查各自的最长等待秒数 | 大于 0 |

修改后可运行 `python automation/run.py generator-preflight --json` 验证。填写未实现的适配器或认证方式会返回配置错误，不会静默回退。

注意：`chatgpt_account` 只表示 CLI 明确报告为 ChatGPT 登录。它不证明订阅档位、剩余额度或某次模型调用必然成功；这些只能在 US-07B 的受控真实调用中验证。

父条目 Key、附件 Key、PDF 哈希、任务状态和运行时间不是配置，它们由系统运行时写入 `.runtime/` 或证据包 `manifest.json`。API 路由、事件类型和数据结构版本属于程序协议，也不是用户路径配置。详细边界见 [variables.md](../documentation/variables.md)。

## US-01 本地配置

团队目标库已经确定为 qinjiajun，群组 ID 为 6618088，保存在可复现的 `config.json` 中。群组 ID 不是密钥，可以进入 Git。

`config.example.json` 用于解释配置结构。只有本机需要覆盖团队配置时，才复制为被 Git 忽略的 `config.local.json`。

如果还不知道群组 ID，可以先运行发现命令：

    python automation/run.py discover-groups --json

然后执行目标群组预检：

    python automation/run.py preflight --json

程序默认定位同一项目中的 `config/config.json`。如果以安装包方式运行或临时使用另一份总配置，可设置 `HYDRO_PLATFORM_CONFIG`，也可显式传入 `--config`；这些只是总配置入口，不保存第二套业务参数。
