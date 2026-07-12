# Checked-In Market Data

This directory contains the reproducible market-data artefacts used by the offline demo. These files are intentionally versioned so a reviewer can run the market and agent demos without first depending on public-network availability.

| File pair | Symbol | Dataset | Fields |
| --- | --- | --- | --- |
| `csi300.csv` and `.meta.json` | `sh000300` | CSI 300 | daily `date`, `close`, `volume` |
| `sse_composite.csv` and `.meta.json` | `sh000001` | Shanghai Composite | daily `date`, `close`, `volume` |
| `szse_component.csv` and `.meta.json` | `sz399001` | Shenzhen Component | daily `date`, `close`, `volume` |

Each `.meta.json` records the Tencent Finance K-line endpoint, every annual request URL, download timestamp, row count, coverage dates, field semantics, and the CSV SHA-256 checksum. Runtime validation also rejects malformed numbers, duplicate or unsorted dates, non-positive closes, negative volume, and checksum mismatches. Regenerate an individual file with:

```powershell
python -m finagent download-market --output data/market/<dataset>.csv --symbol <symbol> --start-year 2005
```

Run `python -m finagent download-markets --output-dir data/market --start-year 2005` to refresh all three. The downloader writes a completed CSV only after its annual windows have been collected; do not commit partial output.
