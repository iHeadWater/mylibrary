# ADR-0003：精读产物根可配置（文件给默认值 + 环境变量覆盖）

## Status

Accepted

## Date

2026-09-12

## Context

精读/综述产物（分析卡、文章、播客、PDF、B站上传件）此前落在 `hydrolitagent/literature/_paths.py`
的一个模块常量上：

```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_ROOT  = PROJECT_ROOT / "outputs"
```

**没有任何出口** —— 没有环境变量、没有参数、没有配置文件。三个消费者
（`bilibili_upload.py`、`download_pdf.py`、`zotero_notebooklm.py`）全部被钉死。想做两件事都做不到：

1. 把产物同步到云盘（OneDrive / Google Drive / 坚果云），让协作者或学生直接打开；
2. 换一台机器、换一个用户，用自己的目录布局。

同时仓库里的「路径类配置」是散的：`HYDROLITAGENT_OUTPUT`（graph 专用，`cli.py:88`）与
`MYLIBRARY_PDF_ROOT`（只覆盖 PDF 目录，`download_pdf.py:205`）各管一段，`cli.py` 里还另有一份
手写的 dotenv 解析。

### 一个决定了设计的既存 bug

`literature/` 下**没有**模块调用 `load_dotenv`（只有 `wechat/*` 和 `zotero_sync.py` 调）。
因此 `MYLIBRARY_PDF_ROOT` 写在 `.env` 里是**静默失效**的，只有 export 到 shell 才生效。

**这条直接决定了新配置必须以仓库内的文件为主载体，环境变量只是覆盖层** —— 否则新变量会重蹈覆辙。

## Decision

### 1. 配置面：`configs/paths.toml` 给默认值，`HYDROLITAGENT_LITERATURE_ROOT` 覆盖

```toml
[literature]
root = "outputs"     # 相对路径从仓库根解析
external = false     # root 指向仓库外时必须显式设为 true
```

优先级：显式参数 → 环境变量 → `configs/paths.toml` → 内置默认 `<仓库根>/outputs`。

**只放两个键**。子目录名（`weekly-review` / `papers` / `bilibili-upload` / `zotero`）**刻意不做成配置项** ——
它们是与 skill 和文档的契约，配错了只会得到「配了个没人认识的名字」这种故障，用户零收益。
它们改为 `_paths.py` 里的代码常量。

### 2. 外部路径必须显式 opt-in，但**不在 import 期报错**

`hydrolitagent/cards/` 的 `paths.artifact_root_external` 是同一约定，但它在 `load_config()` 里直接抛
`ConfigError`。**不照抄这一点**：`literature/_paths.py` 是被库模块 import 的副作用，
import 就抛会连 `import bilibili_upload` 都炸，而用户只是打错一个路径。

规则相应分开：

| 来源 | 规则 |
|---|---|
| 配置文件 | 声明仓库外 root 而无 `external = true` → `PathConfigError`。提交的文件是全用户共享的默认值，指向外部是缺陷不是偏好。由**仓库测试**守卫 |
| 环境变量 | **指向外部路径本身就是显式 opt-in**，不要求第二个开关 —— 那个开关不可能提交进仓库，再要一个自相矛盾 |
| 路径长度 | 外部根超过 180 字符告警（Windows MAX_PATH 是 260，留 80 给产物子树）。是告警不是报错 |

### 3. 复活 `hydrolitagent/_config.py`，不新建模块

它已有可用的 `load_toml`，但**零 importer**，是死代码。`CLAUDE.md` 早就称它「Shared TOML loader」。
在它旁边再建一个 `paths_config.py`，只会让「配置」这个概念的散落更严重。同时：

- `PROJECT_ROOT` 的层级算术收进 `_config.py`（此前 `_paths.py` 自己算过一次，同一事实两处维护）；
- `cli.py` 的手写 dotenv 解析删除，改用 `_config.read_dotenv_values`（顺带修掉它不剥离行内注释的问题）。

### 4. `OUTPUT_ROOT` **必须保持模块级 `Path` 常量**

这是一条硬约束，不是风格偏好：`tests/test_literature_zotero_notebooklm.py` 的三个测试靠
`monkeypatch.setattr(zn, "OUTPUT_ROOT", tmp_path)` 改落点，这依赖消费者用
`from ... import OUTPUT_ROOT` 绑定模块全局、并在**调用期**读取。改成函数会让那条路子作废。

因此 `zotero_notebooklm.py:449` **刻意**写成 `OUTPUT_ROOT / "zotero" / dirname` 而不是
import `_paths.ZOTERO_DIR` —— 后者在 import 期就绑死了。

### 5. skill 层：把 22 处单数 `output/` 归一为 `outputs/`，并加一条可查的解析约定

代价：`output/` 是错的（没有代码创建它、`OUTPUT_ROOT` 是 `outputs/`、多数文档已写 `outputs/`），
但 22 处里 20 处在 skills 里 —— 也就是**在 prompt 文本里**。

**诚实记录这个局限**：prompt 无法强制。补一条 Phase 0 约定 + 一个真实命令
（`uv run hydrolitagent paths --json`），要求 agent 解析出根、不等于默认时替换字面量、
并把解析结果**回显**到 transcript。跳过这一步的 agent 会静默写到 `outputs/`，
而运行看起来是成功的 —— 回显是让它可见的唯一手段。

可强制的那一半是：根一条命令可查，且**所有代码路径**解析正确。

## Alternatives Considered

### 只做 NTFS junction，不改代码

解决了这台机器，但下一个人还要重做一遍，且是机器级设置（换机器丢失）、无法评审、无法测试。
**junction 仍作为迁移手段保留**（见下），但它不是可复用的机制。

### 复用 `hydro-platform` 的 `artifact_root`

它是同类问题最完整的实现，但当时属于独立 workspace 成员（该成员已并入 `hydrolitagent`）：自己的 JSON schema、自己的
`ConfigError` 语义、自己的测试套件。合并会让两个成员互相耦合，并破坏那些测试。
**本次不碰它。**

### 只用环境变量，不要配置文件

最小改动，但新人 clone 下来看不到默认约定，且**在 `.env` 生效路径打通之前**又会踩同一个静默失效的坑。

### 把子目录名也做成配置项

见 Decision §1。契约性的名字不该可配置。

### 让 `OUTPUT_ROOT` 惰性求值

能解决「死共享/不可达路径在 import 期挂住」的问题，但会破坏上面 §4 的三个测试。
**选择接受该风险并记录**：不要把产物根指向离线的网络共享。

## Consequences

- 产物根一条命令可查：`uv run hydrolitagent paths [--json]`。注意本包**没有** `__main__.py`，
  `python -m hydrolitagent` 不可用。
- `outputs/graph` **不在**产物根内：`HYDROLITAGENT_OUTPUT` 继续独立管理 graph 产物。
  这不只是范围问题 —— 实测 `graph/` 在云盘根下最长路径会到 **291 字符**，超过 MAX_PATH。
- `MYLIBRARY_PDF_ROOT` 保留为**旧名**，对 `papers/` 的优先级仍高于产物根。它是过渡期的
  第二个答案，待 `skills/download-pdf/SKILL.md` 与对应测试更新后移除。
- **`.env` 静默失效只修了产物根**：`MYLIBRARY_PDF_ROOT` 与 `NOTEBOOKLM_HOME` 的同款问题
  仍在，各需两行改动，本次刻意留给后续以保持改动可评审。
- `_paths.NOTEBOOKLM_HOME`（Python 常量）**已删除** —— 实测零 importer，是死代码。
  同名的**环境变量**是活的（`zotero_notebooklm.py` 多处读写），保留且文档不变。
  记录于此,以免日后 grep 以为它丢了。
- `configs/graph_prompts.toml` 仍是死配置（是 `--prompt` 的默认值，但 `build_graph` 从不打开它）。
  它属 graph 范畴，本次不动。
- `scripts/filter_hydrology.py:6-8` 的绝对路径（含过期的旧仓库名 `D:/code/hydrolitagent/papers`）
  未纳入统一。它是一次性脚本，应单独决定废弃或移入 `scripts/legacy/`。
- 云盘同步的真实风险不在本 ADR 的代码范围内：OneDrive 按需下载会让读取拿到占位文件；
  同步客户端与写入方没有互斥，可能产生冲突副本（`{slug}-{HOSTNAME}.md`），而 skill 的 glob
  可能把它当成真卡片。运行期间不要用 Obsidian 打开正在同步的产物根。
