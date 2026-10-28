# 在 Obsidian 里读产物

产物根（默认 `outputs/`）里除了机器原稿，还有一层**给人读的生成物**。用 Obsidian 把产物根
当 vault 打开，从 `HOME.md` 出发就能点到当前文献卡、来源、图、相关主题与定向精读。

```bash
uv run hydrolitagent cards index          # 生成/更新阅读层
uv run hydrolitagent cards index --json   # 机器可读报告（含断链自检）
```

## 打开步骤（照做即可）

1. 先在仓库根跑一次 `uv run hydrolitagent cards index`。
2. 打开 Obsidian → **Open folder as vault**（打开文件夹作为仓库）。
3. 选择**产物根**本身 —— 默认是仓库下的 `outputs/`，**不是**仓库根，也不要点进 `outputs/zotero/`。
4. 在文件列表最外层打开 `HOME.md`；需要的话在设置里把它设为起始页。
5. 点任一张卡片，底部有「来源 / 相关主题 / 定向精读 / 图」。

## 生成物长什么样

```text
<产物根>/
  HOME.md                              阅读入口：怎么读、卡片列表、主题列表
  cards/INDEX.md                       所有卡片一行一条（只列当前选中的草稿）
  cards/<条目Key>/card.md              阅读版卡片（YAML 头 + 状态 + 正文 + 来源/主题/精读/图）
  cards/<条目Key>/figures/*.png        从转换缓存复制的论文插图
  reading/themes/<主题编号>.md          当前主题版本的阅读页（来源链接已按新布局重算）
  zotero/ themes/ evidence-packs/      机器原稿：**不改**
```

`cards index` **只写**上面标为阅读层的路径。`zotero/`、`themes/`、`evidence-packs/` 和
`themes/_registry.json` 属于哈希链，生成器只读不写；主题页里历史版本的「粗卡」链接保持原样。

## 阅读层是生成物

- 可以随时删掉 `HOME.md`、`cards/`、`reading/` 重新生成；不要手工编辑，下一次生成会覆盖。
- 生成是**幂等**的：内容没变就不重写，报告里的 `unchanged` 会列出来。
- 生成器写完会**自检所有相对链接**；有断链时退出码为 `3` 并在报告里列出文件与目标。
- 链接是**标准 Markdown 相对链接**，不是 `[[双向链接]]`。Obsidian 能跟随，其他 Markdown
  阅读器也能跟随。

## 卡片状态怎么读

卡片顶部状态行与 YAML 头都取自该草稿**最新一份** `validation.json`：

| 显示 | 含义 |
|---|---|
| `PASS` | 确定性规则通过；**不证明**科学内容正确 |
| `FAIL` | 最近一次校验未通过；错误在机器原稿的 `validation.json` 里 |
| `未校验` | 还没有校验记录 |

`production_eligible` 与 `scientific_correctness_verified` 原样保留，不要把它们读成「已发表」。
同一论文存在多份草稿时，阅读层优先选**最新一份 `PASS` 且 `reading_verified=true`** 的草稿；
没有这样的草稿才退回最新创建的一份。`cards/INDEX.md` 的「选择依据」列写明用了哪条规则。

## 外部产物根

产物根由 `configs/paths.toml` 的 `[literature] root` 决定，可用环境变量
`HYDROLITAGENT_LITERATURE_ROOT` 覆盖。指向仓库之外时配置里要显式写 `external = true`。
阅读层跟着产物根走：

```bash
uv run hydrolitagent cards index --root /path/to/outputs
```

插图来自转换缓存（默认仓库根 `.runtime/papers/`）。缓存放在别处时用 `--runtime-dir` 指过去；
缓存缺失不会中断生成，卡片页会写明 `FIGURE_CACHE_MISSING:<条目Key>`。

## 不要编辑正在写入的文件

- 不要在生成器运行期间编辑 `cards/`、`reading/` 或 `HOME.md`：下一次生成会按磁盘状态重写。
- 产物根在同步盘（OneDrive / Google Drive / 坚果云）上时，等同步完成再打开 Obsidian；
  同步冲突副本（`{文件名}-{主机名}.md`）会被当成普通文件读进来。
- 机器原稿不要手改。手改会被主题池判为冲突并**保留现场、不覆盖**；要改就重跑对应命令。

## 边界

- 旧目录 `survey-ai-scientist/`、`_archive/` 与其他 vault 杂项**不在**阅读层里。
- 历史 `reading.md` 若在修复前写成，可能仍含字面转义换行；写入路径已修，但那些文件属于
  哈希链，**不就地改写**（改写会让主题池一致性检查失败）。
- 阅读层不做检索、不做科学判断；它只是把已有产物组织成可点的路径。

## 相关

[文献卡与主题卡](index.md) · [统一主题池](unified-theme-pool.md) · [运行维护](runtime-maintenance.md)
