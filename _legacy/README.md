# _legacy

归档的**专利/项目** Excel 统计代码。论文统计已迁到 `hydrolitagent/scholars/`。

## 使用

```bash
cp configs/platform.toml.example configs/platform.toml
cp configs/manual_records.toml.example configs/manual_records.toml
# 编辑这两个文件，填入自己的 Excel 路径、人名和人工确认记录
PYTHONPATH=. python platform_mine.py --config configs/platform.toml
```

真实的 `platform.toml` / `manual_records.toml` 含本机路径和人名，已加入 `.gitignore`；
仓库只提交脱敏的 `.example`，不要提交真实配置。

## 测试

```bash
PYTHONPATH=_legacy uv run pytest _legacy/tests -q
```
