# Google Floodhub Paper

Here we simply show you the basins used in the floodhub paper.

## 依赖

复现脚本依赖 `pandas`、`hydrodataset`、`hydrodatasource`（不在主包默认依赖中）：

```bash
uv pip install pandas hydrodataset hydrodatasource
```

数据默认从 `<repo>/datasets` 读取，结果写到 `<repo>/results`；可用
`HYDRO_DATASET_DIR` / `HYDRO_RESULT_DIR` 覆盖。
