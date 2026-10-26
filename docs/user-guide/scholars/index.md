# 学者论文统计

**按人查文献，生成学院学术论文自查表所需的结构化数据。**

不要把它理解成「解析学院下发的表格」：这个工具从**一个人**出发，去 OpenAlex 查这个人的论文，
统计 2021 年以来的论文总数，以及本人作为**第一作者或通讯作者**的论文数，最后输出 CSV/JSON/Markdown。

## 快速开始

```bash
# 1) 先确认这个人是谁；同名时只列候选，不自动选
uv run hydrolitagent scholars resolve --name "张三" --name-en "Zhang San" --json

# 2) 单人统计
uv run hydrolitagent scholars stats --name "张三" --name-en "Zhang San" \
  --institute "水利水电工程研究所" --output-dir outputs/scholars/2026-10-26 --json

# 3) 批量名单
uv run hydrolitagent scholars batch --roster configs/scholars_roster.example.csv \
  --output-dir outputs/scholars/2026-10-26 --json
```

产物在 `--output-dir` 下：

- `form_summary.csv`：表头与学院表逐字一致，可直接打开/粘贴
- `summary_audit.csv`：带作者 ID、匹配状态、撤稿数、复核标记
- `works.csv`：每篇论文一行，含完整作者列表、本人署名、作者序号、计数原因
- `works_by_person.md`：**按人分组的可读明细**，列出全部检索结果（含未计入），并做「清单篇数/计入篇数 vs 汇总数字」对账
- `summary.json`：机器可读
- `review.md`：同名候选、通讯信息缺失、撤稿、查询失败等复核清单

详见[名单格式](roster.md)与[输出与填表](outputs.md)。

## 统计口径

- 时间：`publication_date >= 2021-01-01`；只有年份时按该年 1 月 1 日处理并标记。
- 类型：默认 `article`、`review`、`conference-paper`；预印本、数据集、软件默认不计。
- 「第一通讯作者」：**第一作者或通讯作者任一即计入**，每篇最多计一次。
- 共同一作：OpenAlex 无法识别，这是已知局限。
- 共同通讯：可识别，本人是其中之一即计入。
- 无通讯标记：第一作者仍计入；非第一作者不计入，并进复核清单（不按末位猜）。
- 去重：DOI 优先；预印本与正式版合并，保留正式版。
- 撤稿：仍计入总数，同时单独给出「不含撤稿」数并进复核。

## 同名与中文名

- OpenAlex 里同名作者很多。工具先用配置的单位（默认大连理工大学 `I27357992`）过滤；
  **只有唯一候选才自动采用**，多个候选一律列出来等人选。
- 中文姓名在 OpenAlex 搜不到。名单必须提供**英文名/别名**，或 ORCID / OpenAlex ID。
  只有一个中文名时，工具会直接报错并提示补什么。
- 同一个人可能有多个 OpenAlex profile：名单的 `OpenAlexID` 列可以写多个（`|` 分隔），合并统计。
- 最稳的做法：先跑 `resolve`，确认作者 ID 后写进名单。

## OpenAlex API key

OpenAlex 现在对无 key 请求有每日预算限制，且 **cursor 翻页第一页之后必须带 key**。
建议在 `.env` 里设置：

```bash
OPENALEX_API_KEY=your-key
```

没有 key 也能跑，但会退回 page 翻页（最多 10,000 条），且额度可能很快用完；
额度耗尽时该人员标记为失败，批量继续。

## 中文文献

OpenAlex 对中文期刊覆盖有限。**知网/万方没有稳定的公开 API**，直接爬会遇到登录和验证码，
不适合作为工具的主路径。中文补充有两条路：

1. `--web-search <provider>`：网页检索，结果只进 `web_candidates.csv`，**不自动计入**。
2. `--supplement confirmed.csv`：人工确认后的论文清单，以 `source=manual` 合入统计。

### `--web-search` 有哪些 provider

| provider | 需要什么 | 说明 |
|---|---|---|
| `none`（默认） | 无 | 不做网页检索；核心流程不需要它 |
| `deepseek`（推荐国内用户） | `DEEPSEEK_API_KEY` | 用 DeepSeek 自研搜索（`/v1/tools/search`），以「姓名+单位」查询，再按学术站点白名单过滤；结构化结果，按成功请求计费 |
| `firecrawl` | `FIRECRAWL_API_KEY` | 第三方搜索+抓取服务；**不是核心依赖**，需要单独申请，适合已有 key 的用户 |
| `manual` | 无 | 只读 `--supplement`，不做网页检索 |

DeepSeek 的搜索 API 和主 API 共用 Bearer key，5 QPS；如果只是偶尔补几篇中文论文，
成本很低。它返回标题/URL/摘要，**作者位次和是否通讯仍需人工核对**。
`configs/scholars.toml` 的 `web_search.domains` 是**学术站点白名单**（默认
CNKI、万方、维普、NAPSTIC、工程科学与技术、SciEngine），不是搜索目标；DeepSeek
先用“姓名+单位”查，再只保留这些域名下的结果。

其他可扩展、但当前未内置的国内方案：

- **博查 Bocha**：中文搜索 API，新用户约 1000 次免费试用，之后约 0.036 元/次；
- **智谱 Web Search**：结构化搜索，仓库已有 `ZHIPUAI_API_KEY`，适合后续接入；
- **SearXNG**：自建、免费、无需 key，但需要自己部署；
- **Qwen `enable_search`**：是“搜索增强生成”，返回模型回答而不是原始结果列表，
  适合问答，不适合逐篇核对。

### 推荐流程

1. 先跑 `--web-search deepseek`（或 `firecrawl`），看 `web_candidates.csv`；
2. 在知网/万方/维普/百度学术的公开检索页核对题名、年份、期刊、DOI、**作者位次**和**是否通讯**；
3. 写进 `confirmed.csv`，重跑时加 `--supplement confirmed.csv`。

注意：OpenAlex 有时会把中文论文的英文题名单独收录（例如《基于深度学习的水面漂浮物
智能检测方法》对应英文记录 *Intelligent Detection of Floating Objects...*）。
补充时用 DOI 或作者列表核对，避免同一篇论文算两次。

## 相关

- [名单格式](roster.md)
- [输出与填表](outputs.md)
- [模块架构](../../development/architecture.md)
