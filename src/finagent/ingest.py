from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from finagent.retrieval import chunk_document, write_chunks
from finagent.sources import EvidenceChunk

XBRL_NOISE_MARKERS = ("http://fasb.org", "xbrli:", "us-gaap:", "xmlns", "dei:", "linkbase")
IGNORED_HTML_TAGS = {"script", "style", "noscript", "ix:header", "ix:hidden", "ix:references", "ix:resources", "xbrli:context", "xbrli:unit"}


class _FilingHTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in IGNORED_HTML_TAGS:
            self._ignored_depth += 1
        elif tag in {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in IGNORED_HTML_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag in {"p", "div", "tr", "li"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    parser = _FilingHTMLTextParser()
    parser.feed(raw)
    text = html.unescape(" ".join(parser.parts)).translate(str.maketrans({
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
    }))
    return re.sub(r"\s+", " ", text).strip()


def is_xbrl_noise(text: str) -> bool:
    """Reject schema/context boilerplate while retaining normal filing prose about XBRL."""
    lowered = text.lower()
    return sum(marker in lowered for marker in XBRL_NOISE_MARKERS) >= 2


def build_filing_index(documents_dir: Path, output_path: Path, *, chunk_size: int = 1_400) -> tuple[int, int]:
    manifest_path = documents_dir / "manifest.jsonl"
    if not manifest_path.exists():
        raise FileNotFoundError(f"SEC manifest not found: {manifest_path}. Run download-sec first.")
    chunks: list[EvidenceChunk] = []
    if chunk_size < 80:
        raise ValueError("chunk_size must be at least 80 characters")
    overlap = min(180, max(20, chunk_size // 5))
    documents = 0
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        raw_path = documents_dir / record["local_path"]
        if not raw_path.exists():
            continue
        raw_bytes = raw_path.read_bytes()
        try:
            raw = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            # Some historical EDGAR documents contain Windows-1252 punctuation.
            raw = raw_bytes.decode("cp1252", errors="replace")
        text = html_to_text(raw)
        if len(text) < 400:
            continue
        documents += 1
        document_chunks = chunk_document(
            document_id=record["document_id"],
            title=f"{record['company']} {record['form']} ({record['report_date'] or record['filing_date']})",
            text=text,
            source_url=record["source_url"],
            published_at=record["filing_date"],
            source_type="sec_10k",
            locator=f"accession {record['accession_number']}",
            chunk_size=chunk_size,
            overlap=overlap,
        )
        chunks.extend(chunk for chunk in document_chunks if not is_xbrl_noise(chunk.text))
    if not chunks:
        raise RuntimeError("No usable filing text was indexed. Inspect download_report.json for failed downloads.")
    write_chunks(chunks, output_path)
    return documents, len(chunks)
