# 权限与数据归属

当前是单台 Windows 制卡机上的 CLI 工程，不是多用户 Web 服务。没有平台 JWT、角色数据库或行级安全（RLS）。成员的 Zotero 权限来自私人账号与群组资格；本地文件权限来自 Windows 账号/ACL；GitHub 权限由远端账号管理。`SYS-CARD-01` 是审计标识，不是认证凭据。

| 资源 / 操作 | 团队成员 | 指定制卡机 Python | 生成 Agent | 检查 / 拒绝情形 |
|---|---|---|---|---|
| 统一安装与恢复 | 明确运行setup --apply；本人登录基础软件 | 按现有安装/恢复/调度权限顺序执行；仅本项目 | 不参与安装/恢复 | workstation_setup.py；配置指纹变化、路径未对齐、前置步骤失败即停，未知任务仍拒绝 |
| Zotero应用启动 | Windows账号权限内手动启动/配置 | run-once持锁、启用时仅缺失启动一次，固定exe无shell参数；不代登录或修改同步偏好 | 无启动权限 | zotero_readiness.py；doctor/preflight/dry-run不启动，路径无效拒绝，不结束已有进程 |
| Zotero 入库、补 PDF | 受各自群组权限限制 | 只读，无写入入口 | 不直接操作 Zotero | `zotero.py` 使用配置群组，API 拒绝不可见/无权限资源 |
| 原始 PDF | 受 Zotero 和本机权限限制 | 读取、核对身份与哈希 | 沙箱工具读取指定源 | `pdf_gate.py`、`pdf_delivery.py`；缺失、未同步、身份不符停止 |
| 粗卡 | 可查阅；拥有 OS/Git 权限者仍可手改 | 首次发布/已知中断恢复，不覆盖旧卡 | 返回正文，不直接发布 | `publication.py`、`pipeline.py`；未知改动/重复包报冲突 |
| 精读与候选主题 | 查阅共享结果 | 不改原卡，按输入版本另存 | 分析并返回结果 | `themes.py`；来源错误、越界、人工改动停止 |
| 统一主题池合并/拆分 | 用户已允许候选自动演化，无逐次审批 | 全部替代结果保存后提交注册表；历史不删除 | 仅提出CREATE/UPDATE/MERGE/SPLIT及来源/复用选择，不直接写池 | `theme_pool.plan_actions/commit`；正式或历史父主题、重复操作、无效来源/复用拒绝，保留原文件 |
| 正式主题 | 必须由人确认；专用命令尚未开发 | 无自动转正入口 | 不能自行晋级 | `themes.py` 只发布 candidates |
| 贡献事件/日报 | 查阅，不作绩效排名 | 建基线、去重、生成摘要 | 不参与 | `activity.py`、`daily_report.py`；无来源身份记 UNKNOWN，损坏/改动冲突保留 |
| 成员身份映射 | 录入已核实的 Zotero 用户ID；不存密码 | 只读映射，用于事件归属 | 不参与 | `config.py`、`activity.py`；重复ID或成员编号报错，无来源身份不猜 |
| 依赖环境 | 明确运行 `bootstrap --install` | 仅自有项目环境内安装 | 不参与安装 | `config.py`、`deployment.py`；越界/未知目录/哈希不符拒绝 |
| PDF原生工具 | 明确运行 `bootstrap-native --install` | 固定HTTPS发布包/哈希→项目工具目录；无全局PATH/权限修改 | 不参与安装 | `native_deployment.py`；越界ZIP/未知目录/文件漂移拒绝执行，doctor只验证 |
| Windows每日计划 | 操作者可按总配置安装、检查、停用 | 固定入口、当前用户交互令牌，无管理员提升/密码保存 | 不管理计划，只由原流水线按需调用 | `windows_schedule.py` 核对归属与真实定义，`scheduled.py` 日任务/冷却/锁；不修改其他任务 |
| Git 提交/推送 | 须用户明确授权 | 日常入口不写 Git | 无发布权限 | 无自动提交/推送路径；仓库 ACL 不由平台管理 |

## 成员身份映射

`hydro-platform/members/` 维护稳定的平台成员编号，例如 `STU-001`、`TCH-001` 和 `SYS-CARD-01`。

成员编号用于把 Zotero 私人账号、GitHub 账号和关键贡献事件关联起来。这里只保存必要的身份映射，不保存密码、API Key、邮箱凭据或其他秘密。

当前已确认：每位老师和学生都使用自己的 Zotero 账号；具体成员清单和文件格式待录入真实成员时确定。

现已支持可选的 `members.json`。只填写已核实的实际用户ID，不从用户名或论文作者猜ID。示例格式（不要把示例数据当真实成员）：

```json
{
  "schema_version": 1,
  "members": [
    {"member_id": "STU-001", "display_name": "实际姓名", "zotero_user_id": 123456}
  ]
}
```

可留空数组或不创建文件。重复ID或成员编号会报错；映射仅用于明确返回的 Zotero 用户ID，不能补造接口没有提供的贡献者。系统身份来自 config 中的 `activity_reporting.system_actor_id`。[操作说明](activities-and-daily-report.md)。

本目录不是学生工作区：不存论文、证据卡或主题，也不构成写入权限控制。当前尚未创建真实 `members.json`；缺失时允许继续运行，不能据此推断已完成多人贡献归属验收。[文档入口](index.md)。

## 实际保护与限制

- 来源身份、路径范围、锁、幂等和可恢复写入由 Python 执行；正文格式/标签和科学正确性不是硬门槛。
- PDF Agent 的 shell/看图运行在临时工作区沙箱，文本主题步骤使用只读模式；额外插件、多 Agent 和搜索在命令中关闭。见 `card_generators/codex_local_pdf.py`、`codex_text.py`。
- 论文内容进入已配置模型提供者，这是外部数据边界。本机沙箱禁网不等于模型请求不会出机；密钥和无关私人文件不得放入提示词。
- 单机锁不等于跨机授权。“指定制卡机”目前是部署约定；相同 Windows 用户权限的程序仍可改源码/配置。哈希检查不是抗同账号攻击的数字签名，也不是完整安全审计。

相关：[操作流](flows.md)、[配置与密钥](variables.md)、[验证地图](tests.md)。
