from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from math import isfinite
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from finagent.checksums import normalized_text_sha256


TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
MAJOR_A_SHARE_INDEXES: dict[str, str] = {
    "csi300": "sh000300",
    "sse_composite": "sh000001",
    "szse_component": "sz399001",
}
REQUIRED_MARKET_COLUMNS = {"date", "close", "volume"}


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    start_date: str
    end_date: str
    start_close: float
    end_close: float
    change_percent: float
    average_volume: float
    source_url: str


def download_index_history(
    output_path: Path,
    *,
    symbol: str = "sh000300",
    start_year: int = 2005,
    end_year: int | None = None,
) -> int:
    """Download annual windows because the Tencent endpoint caps each response at 640 rows."""
    end_year = end_year or date.today().year
    if start_year > end_year:
        raise ValueError("start_year cannot be after end_year")
    rows: dict[str, dict[str, str]] = {}
    requests_made: list[str] = []
    for year in range(start_year, end_year + 1):
        params = {"param": f"{symbol},day,{year}-01-01,{year}-12-31,640,qfq"}
        url = f"{TENCENT_KLINE_URL}?{urlencode(params)}"
        requests_made.append(url)
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 FinancialAgent/0.1", "Referer": "https://gu.qq.com/"})
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
        values = payload.get("data", {}).get(symbol, {}).get("day", [])
        for value in values:
            if len(value) < 6:
                continue
            rows[value[0]] = {"date": value[0], "close": value[2], "volume": value[5]}

    if not rows:
        raise RuntimeError("Market download returned no rows. Check network access and symbol.")
    ordered_rows = [rows[key] for key in sorted(rows)]
    _validate_market_rows(ordered_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "close", "volume"])
        writer.writeheader()
        writer.writerows(ordered_rows)
    metadata = {
        "symbol": symbol,
        "source_name": "Tencent Finance K-line API",
        "source_url": TENCENT_KLINE_URL,
        "request_urls": requests_made,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "row_count": len(rows),
        "coverage_start": min(rows),
        "coverage_end": max(rows),
        "fields": {"close": "daily close", "volume": "daily volume as returned by source"},
        "methodology": {
            "frequency": "daily trading observations returned by source; non-trading days are not filled",
            "request_adjustment": "qfq",
            "trading_date_timezone": "Asia/Shanghai",
            "volume_basis": "source-native units; not normalized across indices",
            "calculation_policy": "source rows are disclosed values; returns and averages are deterministic Python calculations",
        },
        "sha256": normalized_text_sha256(output_path),
    }
    Path(f"{output_path}.meta.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(rows)


def download_major_indices(output_dir: Path, *, start_year: int = 2005, end_year: int | None = None) -> dict[str, int]:
    """Download the core mainland China index set using one auditable file per index."""
    return {
        dataset: download_index_history(
            output_dir / f"{dataset}.csv",
            symbol=symbol,
            start_year=start_year,
            end_year=end_year,
        )
        for dataset, symbol in MAJOR_A_SHARE_INDEXES.items()
    }


def market_snapshot(path: Path, *, start: str | None = None, end: str | None = None) -> MarketSnapshot:
    meta_path = Path(f"{path}.meta.json")
    metadata = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    expected_checksum = metadata.get("sha256")
    if expected_checksum and normalized_text_sha256(path) != expected_checksum:
        raise ValueError(f"Market CSV checksum does not match metadata: {path}")
    with path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing_columns = REQUIRED_MARKET_COLUMNS - fieldnames
        if missing_columns:
            raise ValueError(f"Market CSV missing required columns: {', '.join(sorted(missing_columns))}")
        rows = list(reader)
    _validate_market_rows(rows)
    selected = [row for row in rows if (start is None or row["date"] >= start) and (end is None or row["date"] <= end)]
    if len(selected) < 2:
        raise ValueError("At least two market observations are required for the requested period")
    first, last = selected[0], selected[-1]
    start_close = float(first["close"])
    end_close = float(last["close"])
    return MarketSnapshot(
        symbol=str(metadata.get("symbol", path.stem)),
        start_date=first["date"],
        end_date=last["date"],
        start_close=start_close,
        end_close=end_close,
        change_percent=(end_close / start_close - 1) * 100,
        average_volume=sum(float(row["volume"]) for row in selected) / len(selected),
        source_url=str(metadata.get("source_url", "local CSV; metadata unavailable")),
    )


def _validate_market_rows(rows: list[dict[str, str]]) -> None:
    previous_date: date | None = None
    for line_number, row in enumerate(rows, start=2):
        try:
            current_date = date.fromisoformat(row["date"])
            close = float(row["close"])
            volume = float(row["volume"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid market row at CSV line {line_number}") from exc
        if previous_date is not None and current_date <= previous_date:
            raise ValueError("Market dates must be strictly increasing with no duplicates")
        if not isfinite(close):
            raise ValueError(f"Market close must be finite at CSV line {line_number}")
        if not isfinite(volume):
            raise ValueError(f"Market volume must be finite at CSV line {line_number}")
        if close <= 0:
            raise ValueError(f"Market close must be positive at CSV line {line_number}")
        if volume < 0:
            raise ValueError(f"Market volume cannot be negative at CSV line {line_number}")
        previous_date = current_date
