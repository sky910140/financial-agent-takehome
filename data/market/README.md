# 已提交的 A 股指数数据

中文 | [English](README_EN.md)

本目录保存离线演示使用的可复现市场数据。三组 CSV 和配套元数据会提交到 Git，使评审者无需先访问公网，就能运行市场计算和 Agent 演示。

## 数据集

| 文件 | 代码 | 指数 | 覆盖范围 | 行数 | 字段 |
| --- | --- | --- | --- | ---: | --- |
| `csi300.csv` 和 `.meta.json` | `sh000300` | 沪深 300 | 2005-04-08 至 2026-07-10 | 5,164 | 每日 `date`、`close`、`volume` |
| `sse_composite.csv` 和 `.meta.json` | `sh000001` | 上证综指 | 2005-01-04 至 2026-07-10 | 5,225 | 每日 `date`、`close`、`volume` |
| `szse_component.csv` 和 `.meta.json` | `sz399001` | 深证成指 | 2005-01-04 至 2026-07-10 | 5,225 | 每日 `date`、`close`、`volume` |

## 来源与校验

每个 `.meta.json` 配套文件都会保存：

- 腾讯财经 K 线来源和数据端点；
- 每一个自然年度的请求 URL；
- UTC 下载时间；
- 数据行数和覆盖日期；
- 字段含义；
- 日频、不填补非交易日、`qfq` 请求参数、交易日期时区和 source-native 成交量口径；
- 披露值、确定性计算值和模型解释的边界；
- CSV 文件的 SHA-256 校验值。

程序运行时会拒绝缺失字段、非法数字、重复或乱序日期、非正收盘价、负成交量以及校验值不一致的数据。CSV 中的收盘价和成交量是来源披露值；区间涨跌幅和平均成交量由 Python 程序确定性计算；模型只能解释这些值，不参与算术。

运行一个可审计的区间快照：

```powershell
python -m finagent market `
  --file data/market/csi300.csv `
  --start 2006-07-10 `
  --end 2026-07-10
```

## 重新构建

更新单个指数：

```powershell
python -m finagent download-market `
  --output data/market/<dataset>.csv `
  --symbol <symbol> `
  --start-year 2005
```

更新全部三个指数：

```powershell
python -m finagent download-markets --output-dir data/market --start-year 2005
```

下载器按自然年拆分请求，避免公开端点的单次响应行数限制。只有全部年份收集并校验成功后，才写入最终 CSV 和元数据；不应提交不完整的临时结果。
