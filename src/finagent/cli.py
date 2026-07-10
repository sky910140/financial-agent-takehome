from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from finagent.agent import FinancialAgent, render_markdown
from finagent.ingest import build_filing_index
from finagent.market import download_index_history, download_major_indices, market_snapshot
from finagent.sec import download_sec_10k


def _configure_console_encoding(*streams: object) -> None:
    """Avoid Windows legacy-console failures when filings contain typographic symbols."""
    for stream in streams:
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finagent", description="Evidence-first personal financial research agent")
    subcommands = parser.add_subparsers(dest="command", required=True)

    download_sec = subcommands.add_parser("download-sec", help="Download 10 companies' SEC 10-K documents")
    download_sec.add_argument("--output-dir", type=Path, default=Path("sample_docs/sec_10k"))
    download_sec.add_argument("--years", type=int, default=1)
    download_sec.add_argument("--user-agent", help="SEC-compliant app name and contact email; defaults to SEC_USER_AGENT")

    download_market = subcommands.add_parser("download-market", help="Download CSI 300 daily close and volume")
    download_market.add_argument("--output", type=Path, default=Path("data/market/csi300.csv"))
    download_market.add_argument("--symbol", default="sh000300")
    download_market.add_argument("--start-year", type=int, default=2005)
    download_market.add_argument("--end-year", type=int)

    download_markets = subcommands.add_parser("download-markets", help="Download CSI 300, Shanghai Composite, and Shenzhen Component history")
    download_markets.add_argument("--output-dir", type=Path, default=Path("data/market"))
    download_markets.add_argument("--start-year", type=int, default=2005)
    download_markets.add_argument("--end-year", type=int)

    index = subcommands.add_parser("index", help="Build local filing chunks from the SEC manifest")
    index.add_argument("--docs-dir", type=Path, default=Path("sample_docs/sec_10k"))
    index.add_argument("--output", type=Path, default=Path("data/index/filing_chunks.json"))
    index.add_argument("--chunk-size", type=int, default=1_400)

    market = subcommands.add_parser("market", help="Calculate an auditable market-period snapshot")
    market.add_argument("--file", type=Path, default=Path("data/market/csi300.csv"))
    market.add_argument("--start")
    market.add_argument("--end")

    ask = subcommands.add_parser("ask", help="Ask a cited filing or market-data question")
    ask.add_argument("question")
    ask.add_argument("--user", default="default")
    ask.add_argument("--company", help="Filter filing retrieval by ticker or company name")
    ask.add_argument("--index", type=Path, default=Path("data/index/filing_chunks.json"))
    ask.add_argument("--memory", type=Path, default=Path("data/memory/preferences.json"))
    ask.add_argument("--market-file", type=Path, default=Path("data/market/csi300.csv"))
    ask.add_argument("--web", action="store_true", help="Add explicitly-labelled public-web search snippets")
    ask.add_argument("--json", action="store_true", help="Write machine-readable response JSON")
    ask.add_argument("--trace", action="store_true", help="Include non-secret agent execution trace")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        _configure_console_encoding(sys.stdout, sys.stderr)
        _load_dotenv()
        args = build_parser().parse_args(argv)
        if args.command == "download-sec":
            records = download_sec_10k(args.output_dir, years=args.years, user_agent=args.user_agent)
            print(f"Downloaded {len(records)} SEC 10-K documents to {args.output_dir}. Manifest: {args.output_dir / 'manifest.jsonl'}")
            return 0
        if args.command == "download-market":
            rows = download_index_history(args.output, symbol=args.symbol, start_year=args.start_year, end_year=args.end_year)
            print(f"Downloaded {rows} daily {args.symbol} rows to {args.output}. Source metadata: {args.output}.meta.json")
            return 0
        if args.command == "download-markets":
            counts = download_major_indices(args.output_dir, start_year=args.start_year, end_year=args.end_year)
            print("Downloaded major A-share indices: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
            return 0
        if args.command == "index":
            documents, chunks = build_filing_index(args.docs_dir, args.output, chunk_size=args.chunk_size)
            print(f"Indexed {documents} SEC filings into {chunks} chunks at {args.output}")
            return 0
        if args.command == "market":
            snapshot = market_snapshot(args.file, start=args.start, end=args.end)
            print("| Symbol | Start | End | Start close | End close | Change | Avg volume |")
            print("| --- | --- | --- | ---: | ---: | ---: | ---: |")
            print(f"| {snapshot.symbol} | {snapshot.start_date} | {snapshot.end_date} | {snapshot.start_close:.2f} | {snapshot.end_close:.2f} | {snapshot.change_percent:.2f}% | {snapshot.average_volume:.0f} |")
            print(f"Source: {snapshot.source_url}")
            return 0

        agent = FinancialAgent(index_path=args.index, memory_path=args.memory, market_path=args.market_file)
        response = agent.ask(args.question, user_id=args.user, company=args.company, include_web=args.web)
        if args.json:
            print(json.dumps(response.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(render_markdown(response, include_trace=args.trace))
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
