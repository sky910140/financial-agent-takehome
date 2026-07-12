from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen


SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"

COMPANIES: tuple[tuple[str, str, int], ...] = (
    ("AAPL", "Apple Inc.", 320193),
    ("MSFT", "Microsoft Corporation", 789019),
    ("NVDA", "NVIDIA Corporation", 1045810),
    ("AMZN", "Amazon.com, Inc.", 1018724),
    ("GOOGL", "Alphabet Inc.", 1652044),
    ("TSLA", "Tesla, Inc.", 1318605),
    ("JPM", "JPMorgan Chase & Co.", 19617),
    ("BRK-B", "Berkshire Hathaway Inc.", 1067983),
    ("WMT", "Walmart Inc.", 104169),
    ("XOM", "Exxon Mobil Corporation", 34088),
)


@dataclass(frozen=True)
class FilingRecord:
    document_id: str
    ticker: str
    company: str
    cik: int
    form: str
    report_date: str
    filing_date: str
    accession_number: str
    primary_document: str
    source_url: str
    local_path: str
    downloaded_at: str
    source_type: str = "sec_10k"


def validate_sec_user_agent(value: str | None) -> str:
    candidate = (value or os.getenv("SEC_USER_AGENT", "")).strip()
    if not candidate or "@" not in candidate or "\n" in candidate or "\r" in candidate:
        raise ValueError("SEC_USER_AGENT must identify the app and include a contact email, for example: FinancialAgent name@example.com")
    return candidate


def download_sec_10k(
    output_dir: Path,
    *,
    years: int = 1,
    user_agent: str | None = None,
    companies: tuple[tuple[str, str, int], ...] = COMPANIES,
) -> list[FilingRecord]:
    """Download the most recent 10-K documents and an append-only source manifest."""
    if years < 1:
        raise ValueError("years must be at least 1")
    contact = validate_sec_user_agent(user_agent)
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[FilingRecord] = []
    errors: list[str] = []
    for ticker, company, cik in companies:
        try:
            submissions = _get_json(SEC_SUBMISSIONS_URL.format(cik=cik), contact)
            filings = submissions.get("filings", {})
            filings = filings if isinstance(filings, dict) else {}
            recent = filings.get("recent", {})
            selected = _select_10k_rows(recent if isinstance(recent, dict) else {}, limit=years)
            if len(selected) < years:
                history_files = filings.get("files", [])
                if isinstance(history_files, list):
                    for history_file in history_files:
                        if len(selected) >= years or not isinstance(history_file, dict):
                            break
                        name = history_file.get("name")
                        if not isinstance(name, str) or not name:
                            continue
                        historical = _get_json(SEC_SUBMISSIONS_FILE_URL.format(name=name), contact)
                        selected.extend(_select_10k_rows(
                            historical,
                            limit=years - len(selected),
                            excluded_accessions={row["accession_number"] for row in selected},
                        ))
            if not selected:
                errors.append(f"{ticker}: no 10-K in SEC recent submissions")
                continue
            if len(selected) < years:
                errors.append(f"{ticker}: requested {years} 10-K filings but SEC submissions exposed {len(selected)}")
            for filing in selected:
                accession = filing["accession_number"]
                primary_document = filing["primary_document"]
                filing_date = filing["filing_date"]
                report_date = filing["report_date"]
                source_url = SEC_ARCHIVE_URL.format(cik=cik, accession=accession.replace("-", ""), document=primary_document)
                payload = _get_bytes(source_url, contact)
                document_id = f"{ticker.lower()}-{report_date or filing_date}-10k-{accession.replace('-', '')}"
                filename = f"{document_id}.html"
                target = output_dir / filename
                target.write_bytes(payload)
                records.append(FilingRecord(
                    document_id=document_id,
                    ticker=ticker,
                    company=company,
                    cik=cik,
                    form="10-K",
                    report_date=report_date,
                    filing_date=filing_date,
                    accession_number=accession,
                    primary_document=primary_document,
                    source_url=source_url,
                    local_path=filename,
                    downloaded_at=datetime.now(UTC).isoformat(),
                ))
        except Exception as exc:  # Keep other public-company downloads progressing.
            errors.append(f"{ticker}: {type(exc).__name__}: {exc}")

    manifest = output_dir / "manifest.jsonl"
    existing_records = _read_manifest(manifest)
    combined_records = {record["document_id"]: record for record in existing_records}
    for record in records:
        combined_records.setdefault(record.document_id, asdict(record))
    manifest.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in combined_records.values()),
        encoding="utf-8",
    )
    (output_dir / "download_report.json").write_text(json.dumps({
        "downloaded_at": datetime.now(UTC).isoformat(),
        "requested_companies": len(companies),
        "years_per_company": years,
        "downloaded_documents": len(records),
        "errors": errors,
        "sec_user_agent_configured": True,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


def _select_10k_rows(
    table: dict[str, object],
    *,
    limit: int,
    excluded_accessions: set[str] | None = None,
) -> list[dict[str, str]]:
    """Normalize SEC parallel-array submission tables into auditable filing rows."""
    excluded_accessions = excluded_accessions or set()
    forms = table.get("form", [])
    accessions = table.get("accessionNumber", [])
    primary_documents = table.get("primaryDocument", [])
    filing_dates = table.get("filingDate", [])
    report_dates = table.get("reportDate", [])
    if not all(isinstance(values, list) for values in (forms, accessions, primary_documents, filing_dates, report_dates)):
        return []
    rows: list[dict[str, str]] = []
    for index, form in enumerate(forms):
        if form != "10-K" or len(rows) >= limit:
            continue
        try:
            accession = str(accessions[index])
            if accession in excluded_accessions:
                continue
            rows.append({
                "accession_number": accession,
                "primary_document": str(primary_documents[index]),
                "filing_date": str(filing_dates[index]),
                "report_date": str(report_dates[index]) if index < len(report_dates) else "",
            })
        except IndexError:
            continue
    return rows


def _get_json(url: str, user_agent: str) -> dict[str, object]:
    return json.loads(_get_bytes(url, user_agent).decode("utf-8"))


def _get_bytes(url: str, user_agent: str) -> bytes:
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=60) as response:
        return response.read()


def _read_manifest(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid manifest JSON at line {line_number}: {path}") from exc
        if not isinstance(record, dict) or not isinstance(record.get("document_id"), str):
            raise ValueError(f"Manifest record at line {line_number} has no document_id: {path}")
        records.append(record)
    return records
