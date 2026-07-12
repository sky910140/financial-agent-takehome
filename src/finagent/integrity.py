from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from finagent.market import REQUIRED_MARKET_COLUMNS, _validate_market_rows
from finagent.checksums import normalized_text_sha256
from finagent.retrieval import read_chunks


DOCUMENT_ID_RE = re.compile(r"^(?P<ticker>.+)-(?P<report_date>\d{4}-\d{2}-\d{2})-10k-(?P<accession>\d+)$")
CIK_RE = re.compile(r"/Archives/edgar/data/(?P<cik>\d+)/")
ACCESSION_RE = re.compile(r"accession (?P<accession>\d{10}-\d{2}-\d{6})")


def validate_repository_data(index_path: Path, market_dir: Path, snapshot_path: Path) -> dict[str, object]:
    """Validate checked-in datasets and require them to match the reviewer-visible snapshot."""
    issues: list[str] = []
    chunks = read_chunks(index_path)
    if not chunks:
        issues.append("SEC index is empty")
    by_document: dict[str, list[object]] = defaultdict(list)
    chunk_ids: set[str] = set()
    for chunk in chunks:
        if chunk.chunk_id in chunk_ids:
            issues.append(f"Duplicate SEC chunk ID: {chunk.chunk_id}")
        chunk_ids.add(chunk.chunk_id)
        by_document[chunk.document_id].append(chunk)
        if chunk.source_type != "sec_10k":
            issues.append(f"Unexpected SEC index source type: {chunk.source_type}")
        if not chunk.text.strip() or not chunk.source_url or not chunk.published_at or not chunk.locator:
            issues.append(f"Incomplete SEC metadata: {chunk.chunk_id}")
        if not _valid_date(chunk.published_at):
            issues.append(f"Invalid filing date: {chunk.chunk_id}")
        parsed_url = urlparse(chunk.source_url)
        if parsed_url.scheme != "https" or parsed_url.netloc.lower() != "www.sec.gov":
            issues.append(f"Unexpected SEC source URL: {chunk.chunk_id}")

    filing_records: list[dict[str, object]] = []
    for document_id, document_chunks in sorted(by_document.items()):
        first = document_chunks[0]
        identifier = DOCUMENT_ID_RE.fullmatch(document_id)
        cik = CIK_RE.search(first.source_url)
        accession = ACCESSION_RE.search(first.locator or "")
        if not identifier or not cik or not accession:
            issues.append(f"Unparseable 10-K metadata: {document_id}")
            continue
        filing_records.append({
            "ticker": identifier.group("ticker").upper(),
            "company": first.title.rsplit(" 10-K", 1)[0],
            "cik": cik.group("cik"),
            "form": "10-K",
            "report_date": identifier.group("report_date"),
            "filing_date": first.published_at,
            "accession": accession.group("accession"),
            "document_id": document_id,
            "source_url": first.source_url,
            "chunk_count": len(document_chunks),
        })
    filings = {
        "index_file": index_path.name,
        "index_sha256": _sha256(index_path),
        "document_count": len(by_document),
        "chunk_count": len(chunks),
        "records": filing_records,
    }

    market_records: list[dict[str, object]] = []
    for csv_path in sorted(market_dir.glob("*.csv")):
        meta_path = Path(f"{csv_path}.meta.json")
        if not meta_path.exists():
            issues.append(f"Missing market metadata: {meta_path.name}")
            continue
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        with csv_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_MARKET_COLUMNS - set(reader.fieldnames or [])
            rows = list(reader)
        if missing:
            issues.append(f"Market CSV missing columns ({csv_path.name}): {', '.join(sorted(missing))}")
            continue
        try:
            _validate_market_rows(rows)
        except ValueError as exc:
            issues.append(f"Invalid market CSV ({csv_path.name}): {exc}")
            continue
        checksum = _sha256(csv_path)
        if metadata.get("sha256") != checksum:
            issues.append(f"Market checksum mismatch: {csv_path.name}")
        if metadata.get("row_count") != len(rows):
            issues.append(f"Market row count mismatch: {csv_path.name}")
        if rows and (metadata.get("coverage_start") != rows[0]["date"] or metadata.get("coverage_end") != rows[-1]["date"]):
            issues.append(f"Market coverage mismatch: {csv_path.name}")
        methodology = metadata.get("methodology")
        required_methodology = {
            "frequency", "request_adjustment", "trading_date_timezone", "volume_basis", "calculation_policy",
        }
        if not isinstance(methodology, dict) or not required_methodology.issubset(methodology):
            issues.append(f"Incomplete market methodology: {csv_path.name}")
        market_records.append({
            "dataset": csv_path.stem,
            "symbol": metadata.get("symbol"),
            "source_name": metadata.get("source_name"),
            "source_url": metadata.get("source_url"),
            "downloaded_at": metadata.get("downloaded_at"),
            "coverage_start": rows[0]["date"] if rows else None,
            "coverage_end": rows[-1]["date"] if rows else None,
            "row_count": len(rows),
            "fields": metadata.get("fields"),
            "methodology": methodology,
            "csv_sha256": checksum,
        })
    markets = {"dataset_count": len(market_records), "records": market_records}

    if not snapshot_path.exists():
        issues.append(f"Missing data snapshot: {snapshot_path}")
    else:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if snapshot.get("filings") != filings:
            issues.append("SEC data does not match data/DATA_SNAPSHOT.json")
        if snapshot.get("markets") != markets:
            issues.append("Market data does not match data/DATA_SNAPSHOT.json")
    return {"valid": not issues, "issues": issues, "filings": filings, "markets": markets}


def _sha256(path: Path) -> str:
    return normalized_text_sha256(path)


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True
