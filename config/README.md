# 总配置

`config.json` 是自动化唯一的团队级总配置入口。需要迁移目录、更换 Zotero 本地接口、调整扫描参数时，只修改这个文件，不修改程序源码。所有路径字段必须显式填写；缺失时程序直接报配置错误，不使用源码中的隐含目录默认值。

其中 `paths.project_root` 相对于 `config.json` 所在目录解析；其余路径相对于 `project_root` 解析。因此，从仓库外部工作目录调用程序时，产物仍会写入正确项目。为避免误写，所有项目路径必须位于 `project_root` 内，运行快照、任务、锁和原始日志还必须位于 `runtime_dir` 内。

当前可配置项：

- `paths`：项目根目录、运行区、快照、任务、锁、日志、PDF 临时区，以及证据包、模板、主题、成员、事件、报告、提示词和数据结构目录；
- `zotero`：本地 API 地址、目标共享群组 ID、HTTP 超时和进程检查超时；
- `scan.page_size`：每页读取条目数；
- `pdf_gate`：最小 PDF 体积、最小可提取文字数和计算哈希时的分块大小。

Zotero API Key、GitHub Token 等秘密只能存放在制卡机本地环境变量或密钥存储中，不得提交到仓库。

父条目 Key、附件 Key、PDF 哈希、任务状态和运行时间不是配置，它们由系统运行时写入 `.runtime/` 或证据包 `manifest.json`。API 路由、事件类型和数据结构版本属于程序协议，也不是用户路径配置。详细边界见 [variables.md](../documentation/variables.md)。

## US-01 本地配置

团队目标库已经确定为 qinjiajun，群组 ID 为 6618088，保存在可复现的 `config.json` 中。群组 ID 不是密钥，可以进入 Git。

`config.example.json` 用于解释配置结构。只有本机需要覆盖团队配置时，才复制为被 Git 忽略的 `config.local.json`。

如果还不知道群组 ID，可以先运行发现命令：

    python automation/run.py discover-groups --json

然后执行目标群组预检：

    python automation/run.py preflight --json

程序默认定位同一项目中的 `config/config.json`。如果以安装包方式运行或临时使用另一份总配置，可设置 `HYDRO_PLATFORM_CONFIG`，也可显式传入 `--config`；这些只是总配置入口，不保存第二套业务参数。
