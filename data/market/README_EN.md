# Checked-In A-Share Index Data

[中文](README.md) | English

This directory contains the reproducible market-data artifacts used by the offline demo. They are intentionally checked into Git so reviewers can run market calculations and Agent demos without first depending on public-network availability.

## Datasets

| Files | Symbol | Dataset | Coverage | Rows | Fields |
| --- | --- | --- | --- | ---: | --- |
| `csi300.csv` and `.meta.json` | `sh000300` | CSI 300 | 2005-04-08 to 2026-07-10 | 5,164 | daily `date`, `close`, `volume` |
| `sse_composite.csv` and `.meta.json` | `sh000001` | Shanghai Composite | 2005-01-04 to 2026-07-10 | 5,225 | daily `date`, `close`, `volume` |
| `szse_component.csv` and `.meta.json` | `sz399001` | Shenzhen Component | 2005-01-04 to 2026-07-10 | 5,225 | daily `date`, `close`, `volume` |

## Provenance and Validation

Each `.meta.json` sidecar records:

- the Tencent Finance K-line source and endpoint;
- every annual request URL;
- UTC download time;
- row count and coverage dates;
- field definitions;
- daily frequency, no non-trading-day filling, `qfq` request parameter, trading-date timezone, and source-native volume basis;
- the boundary between disclosed values, deterministic calculations, and model interpretation;
- the LF-normalized text SHA-256 checksum; Windows CRLF and Linux LF checkouts use the same checksum.

Runtime validation rejects missing columns, malformed numbers, NaN/Inf, duplicate or unsorted dates, non-positive close prices, negative volume, and checksum mismatches. CSV close and volume are source-disclosed observations. Market-period returns and average volume are deterministic Python calculations; an LLM may only interpret those values.

Run an auditable period snapshot with:

```powershell
python -m finagent market `
  --file data/market/csi300.csv `
  --start 2006-07-10 `
  --end 2026-07-10
```

## Rebuild

Refresh an individual index:

```powershell
python -m finagent download-market `
  --output data/market/<dataset>.csv `
  --symbol <symbol> `
  --start-year 2005
```

Refresh all three indices:

```powershell
python -m finagent download-markets --output-dir data/market --start-year 2005
```

The downloader requests one natural year at a time to avoid the endpoint's per-response row limit. It writes the final CSV and metadata only after all requested windows have been collected and validated; partial output should not be committed.
