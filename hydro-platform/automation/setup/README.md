# 安装与恢复

在项目根目录先预览，再明确执行：

~~~powershell
python automation/run.py setup --json
python automation/run.py setup --apply --json
~~~

setup 编排项目依赖安装、就绪检查、本地任务恢复及按配置恢复 Windows 计划；不代登录、不改总配置、不生成科研内容、不推 Git。基础 Python、Zotero、Codex 以及私人账号需先准备。

## 本目录的文件

- dependencies.lock.json：Python 依赖的版本、来源和 SHA-256。
- native-tools.lock.json：Windows Poppler 工具的来源、版本及 SHA-256。

安装代码在 src/hydro_platform/deployment.py、native_deployment.py、workstation_setup.py。完整安装复用已有受管环境，不接管未知目录或修改系统 PATH。

## 分步入口

统一前缀 python automation/run.py：

| 子命令 | 功能 |
|---|---|
| bootstrap --json / bootstrap --install --json | Python 项目环境预览 / 安装 |
| bootstrap-native --json / bootstrap-native --install --json | PDF 工具预览 / 安装 |
| doctor --json | 只读环境检查 |
| recover --json | 根据本地 Zotero 与已取回的共享成果重建派生状态 |
| schedule-plan/status/install/remove/tick | 计划预览、查询、管理及到期检查；每个是独立子命令 |

recover 不自动从 GitHub 下载或推送。换机先取回已备份的源码和共享成果，再本人登录并同步 Zotero；不能从未上传的旧电脑找回文件。

指定制卡机才启用 scheduler。只查看资料的机器使用关闭调度的配置，避免重复制卡。setup 本身无模型调用，但注册的计划日后到期可能调用模型。

已有同机新目录恢复、依赖安装和本机调度实测；干净新机、关机/重新登录、云端同步延迟未全面验收。

[完整安装恢复](../../documentation/workstation-setup.md) · [调度](../../documentation/cron.md) · [运行维护](../../documentation/runtime-maintenance.md)
