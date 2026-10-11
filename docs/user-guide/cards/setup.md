# 一次性配置

**配一次就够。** 之后直接跟 agent 说人话 ——「把《某某》这篇做成卡」—— 不必再回来看这页。

## 装什么

装上 **Git**、**Python 3.12–3.14** 和 [uv](https://docs.astral.sh/uv/)，然后在仓库根装依赖：

```bash
git clone --branch literature-platform https://github.com/iHeadWater/mylibrary.git mylibrary
cd mylibrary
uv sync --all-packages --locked
```

仓库里**不含**别人的论文、Zotero 库、账号或 `.venv` —— 那些都是你自己的。

## 开什么

| 你要做的事 | 先得有什么 |
|---|---|
| 读你自己的 Zotero 论文 | **Zotero Desktop 正在运行**，并在「设置 → 高级」勾选「允许此计算机上的其他应用程序与 Zotero 通信」 |
| 生成主体卡草稿 | 装好并**登录**一种 CLI：**Codex** 或 **Claude Code**（二选一即可） |
| 同上（读 PDF 页面） | **Poppler** 的 `pdftoppm` / `pdfinfo` / `pdftotext` 在 PATH 里 |
| 只做离线校验 | 以上**都不需要** |

- 要处理的论文必须**已经附好可读的 PDF** —— 本平台**不下载** PDF。
  缺 PDF 先走入库那条线：[论文入库流水线](../paper-pipeline.md)。
- 用群组库的话：确认自己已加入该群组，且群组条目与 PDF 在本机 Zotero 可用。

## 自查（不调用模型）

仓库带一份合成示例，装完就能验证入口通了：

```bash
uv run python scripts/paper_validate.py \
  --draft hydrolitagent/cards/assets/examples/subject-card-validation/draft.json \
  --paper-input hydrolitagent/cards/assets/examples/subject-card-validation/paper-input.json \
  --report-dir outputs/validation-demo
```

返回 `status: PASS` 即入口可用。它只验证**代码入口**，不代表真实论文能生成 ——
那要等你的 Zotero 和模型 CLI 就绪。

## 下一步

配完就能开工了。这条线能做什么、怎么跟 agent 说，见[文献卡与主题卡](index.md)。
