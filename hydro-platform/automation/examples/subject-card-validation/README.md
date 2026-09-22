# 离线校验合成示例

这两份 JSON 是用于验证 #31 程序规则的合成数据，不来自真实论文，也不是科研证据。/example/papers/demo.pdf 无需存在；此阶段不打开 PDF。

在包含 #44 的仓库根目录运行：

~~~powershell
uv sync --all-packages --locked
.\.venv\Scripts\python.exe -m hydro_platform evidence-validate --draft hydro-platform/automation/examples/subject-card-validation/draft.json --paper-input hydro-platform/automation/examples/subject-card-validation/paper-input.json --report-dir outputs/validation-demo --json
~~~

预期退出码 0、status=PASS，可能含短正文提示。每次报告在 outputs/validation-demo/<validation_id>/validation.json，输入不会被修改。不需要 config.json、Zotero、Codex、Poppler 或模型登录。

模板和提示词指纹绑定当前资产版本；以后资产变化时需要同步更新示例，不能只改版本标签绕过校验。这些 JSON 不能送到 #30 冒充真实 READY PDF。
