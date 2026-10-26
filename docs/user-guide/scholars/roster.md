# 名单格式

## CSV（推荐）

UTF-8-sig 或 GB18030 均可；Excel 直接编辑保存即可。

```csv
姓名,所属研究所,英文名/别名,ORCID,OpenAlexID,自查结论,补充说明
张三,水利水电工程研究所,Zhang San|San Zhang,,,,
李四,岩土工程研究所,Li Si,0000-0002-1825-0097,,,
```

| 列 | 必需 | 说明 |
|---|---|---|
| `姓名` | 是 | 写入汇总表的姓名 |
| `所属研究所` / `研究所` | 否 | 写入汇总表；缺失则留空 |
| `英文名/别名` / `别名` / `aliases` | 否 | OpenAlex 检索用；多个用 `|`、`;`、`；`、`、` 分隔 |
| `ORCID` | 否 | 有 ORCID 时优先用 ORCID 定位，最稳 |
| `OpenAlexID` / `openalex_id` | 否 | 可写多个（`A111|A222`），合并统计 |
| `自查结论` | 否 | 原样写入「自查是否存在问题」；不填则写「待本人确认」 |
| `补充说明` | 否 | 原样写入最后一列 |

表头也接受英文：`name`、`institute`、`aliases`、`orcid`、`openalex_id`。

> 真实名单建议放 `outputs/` 或仓库外；仓库里只保留匿名示例。

## TOML

```toml
[[people]]
name = "张三"
institute = "水利水电工程研究所"
aliases = ["Zhang San", "San Zhang"]
orcid = ""
openalex_ids = ["A1234567890"]
self_check = ""
self_check_note = ""
```

## 为什么必须给英文名或 ORCID

OpenAlex 的作者检索基于拉丁字母姓名。实测中文姓名直接搜通常返回 0，
拉丁字母别名才能定位到作者。中文名单独出现时工具会报错，不会瞎猜。

## 同名怎么办

1. 先跑：

   ```bash
   uv run hydrolitagent scholars resolve --name "张三" --name-en "Zhang San" --json
   ```

2. 看候选的 OpenAlex ID、单位、论文数、ORCID。
3. 把确认的 ID 写进名单的 `OpenAlexID` 列，或补上 `ORCID`。

工具不会在多个候选里自动挑一个；未确认的人汇总数字留空，并在 `review.md` 里列出候选。
