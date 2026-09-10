# 证据包：统一文献证据池

团队只维护这一份证据包集合，不按学生或主题复制论文档案。主题只引用证据包及精读结果。

## 编号与来源

一篇论文一个 EV-父条目Key-简短标题/ 目录。稳定身份由指定共享库 ID + Zotero 父条目 Key 确定，EV 编号使用父条目 Key；标题便于识别，不用于判重。附件 Key 和 PDF SHA-256 用于核对输入版本。

这防止同一条目反复制卡，不替代 Zotero 对重复入库论文的查重。原始 PDF 由 Zotero 管理，不复制到证据包或提交 Git。

## 文件结构

~~~text
EV-父条目Key-简短标题/
├─ card.md
├─ manifest.json
├─ quality-audit.json             部分包有此生成/恢复记录
└─ readings/
   └─ RD-精读编号/
      ├─ reading.md
      └─ result.json
~~~

- **card.md**：通用详细粗卡，基于完整原始 PDF，供主题规划使用。“粗”相对于定向精读，不等于摘要卡。
- **manifest.json**：身份、来源、输入指纹、占位/粗卡状态，以及实际留存的模型/模板/生成记录。它不承载科研正文。
- **quality-audit.json**：当前或历史生成/恢复回执。旧包可能没有，字段随协议不同；不能因文件名称认定已经独立核验科学质量。
- **reading.md**：同一论文面向一个研究问题/分析重点的精读正文。
- **result.json**：精读绑定的论文来源、重点和上下文、模型输出及执行记录，供追溯和中断复用。

旧精读仍在 readings/TH-主题编号/ 下，并有历史 manifest.json；统一池接入后不搬动或改写。新的精读使用 RD-编号，不以运行 batch 或主题目录决定唯一归属。

## 自动保存与复用

1. 取得合格 PDF 后创建 manifest.json 和 PLACEHOLDER 占位 card.md。
2. 当前单 Agent 自动选八类模板之一，生成详细粗卡；Python 检查来源、非空输出、模板路由及安全写入，不检查正文标题、归因措辞或固定数量。
3. 首次保存为 ROUGH 后，日常扫描、补跑和恢复均跳过已有卡，不因模型/模板更新自动重制。
4. 候选主题需要更深入证据时，优先判断历史精读是否仍适用；不足才从原始 PDF 再读。
5. 新精读独立保存，不修改原 card.md。多个主题可引用同一份适用精读；不同问题也可有不同精读。
6. 来源不符、重复包或人工修改冲突停止并保留文件，不静默覆盖。

系统扫描各包的 manifest.json 找到文献，不另外维护一份人工文献总表。本机 tasks.json 是派生任务队列；themes/_registry.json 是主题登记表，不是证据包清单。

共享保存的 JSON 可能含 Markdown 快照，用于恢复已完成结果，不是另一套需要人工维护的卡片。不要直接修改机器清单或移动被主题引用的文件夹。

## 运行与查看

日常在项目根目录：

~~~powershell
python automation/run.py run-once --json
~~~

细分命令 packages-sync、evidence-generate 和 evidence-generate-trial 供维护/受控试运行使用。已有卡试运行只写本机运行区，不替换原卡。

[操作手册](../documentation/operator-manual.md) · [单 Agent 制卡](../documentation/single-agent-rough-card.md) · [统一主题池](../themes/index.md)
