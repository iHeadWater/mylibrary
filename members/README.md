# 成员身份映射

本目录维护稳定的平台成员编号，例如 `STU-001`、`TCH-001` 和 `SYS-CARD-01`。

成员编号用于把 Zotero 私人账号、GitHub 账号和关键贡献事件关联起来。这里只保存必要的身份映射，不保存密码、API Key、邮箱凭据或其他秘密。

当前已确认：每位老师和学生都使用自己的 Zotero 账号；具体成员清单和文件格式待录入真实成员时确定。

现已支持可选的 members.json。只填写已核实的实际用户ID，不从用户名或论文作者猜ID。示例格式（不要把示例数据当真实成员）：

```json
{
  "schema_version": 1,
  "members": [
    {"member_id": "STU-001", "display_name": "实际姓名", "zotero_user_id": 123456}
  ]
}
```

可留空数组或不创建文件。重复ID或成员编号会报错；映射仅用于明确返回的 Zotero 用户ID，不能补造接口没有提供的贡献者。系统身份来自 config 中的 activity_reporting.system_actor_id。[操作说明](../documentation/activities-and-daily-report.md)。

本目录不是学生工作区：不存论文、证据卡或主题，也不构成写入权限控制。当前尚未创建真实 members.json；缺失时允许继续运行，不能据此推断已完成多人贡献归属验收。[统一知识目录](../README.md)。
