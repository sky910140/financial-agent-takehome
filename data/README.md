# 数据快照、来源与口径

本目录的受检入口是 `DATA_SNAPSHOT.json`。快照日期为 2026-07-12，内容由已提交文件实际计算，不是手工估算：10 份最新 10-K、3,978 个检索片段，以及 3 组 A 股主要指数日频 CSV。

## SEC 10-K

来源为 SEC EDGAR Archives。每份记录保留 ticker、公司名、CIK、form、报告期、提交日、accession、document ID、原始 SEC URL 和 chunk 数。`filing_chunks.json` 的整体 SHA-256 也在快照中。索引正文是原始 10-K HTML 去除 script/style 和高密度 inline-XBRL 噪声后的展平、重叠 chunk；它适合可追溯词法检索，但不是表格或 XBRL fact 数据库。

## 市场数据

来源为腾讯财经 K-line 公开端点，请求参数按自然年使用 `day` 和 `qfq`。CSV 只保存来源返回的交易日期、收盘价和成交量，未填补非交易日，成交量保持来源原始单位、不做跨指数归一化。各 `.meta.json` 保留全部年度请求 URL、UTC 下载时间、覆盖日期、行数、字段定义和 LF 规范化文本的 CSV SHA-256，因此 Windows CRLF 与 Linux LF checkout 使用同一口径。

口径边界：CSV 的 `close` 和 `volume` 是来源披露值；Python 从实际落入请求区间的首末交易日计算区间涨跌幅，并对区间内 volume 做算术平均。模型不参与计算。交易日期按指数所属中国市场日历理解；下载时间是 UTC 时间戳。当前数据截至 2026-07-10，不是实时行情，也不用于投资建议。

## 完整性检查

```powershell
python -m finagent data-integrity
```

检查会验证 SEC 元数据完整性、唯一 chunk ID、SEC HTTPS URL、日期格式、索引 hash，以及市场 CSV 列、有限数值（拒绝 NaN/Inf）、严格递增日期、行数、覆盖范围和 checksum。任何一项与 `DATA_SNAPSHOT.json` 不一致都会返回退出码 2。
