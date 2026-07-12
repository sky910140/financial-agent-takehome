from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from finagent.agent import FinancialAgent, render_html, render_markdown
from finagent.evaluation import evaluate_retrieval
from finagent.ingest import build_filing_index
from finagent.market import download_index_history, download_major_indices, market_snapshot
from finagent.models import ModelGateway
from finagent.sec import COMPANIES, download_sec_10k


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

    subcommands.add_parser("verify-models", help="Verify live connectivity to the two required primary models without sending financial documents")

    smoke = subcommands.add_parser("smoke-demo", help="Run one fixed filing question and require all remote model stages")
    smoke.add_argument("--index", type=Path, default=Path("data/index/filing_chunks.json"))
    smoke.add_argument("--memory", type=Path, default=Path("data/memory/preferences.json"))
    smoke.add_argument("--market-file", type=Path, default=Path("data/market/csi300.csv"))
    smoke.add_argument("--company", default="Apple")
    smoke.add_argument("--question", default="Summarize liquidity and debt-related risks.")
    smoke.add_argument("--limit", type=int, default=4)

    retrieval_eval = subcommands.add_parser("eval-retrieval", help="Run the checked-in golden-query retrieval evaluation")
    retrieval_eval.add_argument("--index", type=Path, default=Path("data/index/filing_chunks.json"))
    retrieval_eval.add_argument("--cases", type=Path, default=Path("evals/retrieval_cases.json"))
    retrieval_eval.add_argument("--limit", type=int, default=5)

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
    ask.add_argument("--limit", type=int, default=5, help="Maximum local evidence chunks before Web or market evidence")
    output_format = ask.add_mutually_exclusive_group()
    output_format.add_argument("--json", action="store_true", help="Write machine-readable response JSON")
    output_format.add_argument("--html", action="store_true", help="Write a self-contained, safe HTML research report")
    ask.add_argument("--trace", action="store_true", help="Include non-secret agent execution trace")
    return parser


def _verify_models(gateway: ModelGateway) -> int:
    for provider in ("doubao", "deepseek"):
        max_tokens = 16 if provider == "doubao" else 600
        response = gateway.complete(
            provider,
            "You are a connectivity check. Reply with exactly READY.",
            "Return READY.",
            max_tokens=max_tokens,
            timeout=25,
        )
        ready = response.text.strip().rstrip(".!").upper() == "READY"
        if not response.used_remote_model or not ready:
            print(f"Model verification failed for {provider}: {response.error or 'unexpected connectivity response'}", file=sys.stderr)
            return 2
        print(f"Verified {provider} / {response.model}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        _configure_console_encoding(sys.stdout, sys.stderr)
        _load_dotenv()
        args = build_parser().parse_args(argv)
        if args.command == "download-sec":
            records = download_sec_10k(args.output_dir, years=args.years, user_agent=args.user_agent)
            expected = len(COMPANIES) * args.years
            if len(records) < expected:
                raise RuntimeError(
                    f"SEC download incomplete: received {len(records)} of {expected} requested documents. "
                    f"Inspect {args.output_dir / 'download_report.json'}."
                )
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
        if args.command == "verify-models":
            return _verify_models(ModelGateway())
        if args.command == "smoke-demo":
            agent = FinancialAgent(index_path=args.index, memory_path=args.memory, market_path=args.market_file)
            response = agent.ask(args.question, company=args.company, limit=args.limit)
            completed = all(bool(item["used_remote_model"]) for item in response.model_trace)
            used_remote_answer = completed and "Offline extractive mode is active" not in response.answer
            if not used_remote_answer:
                print("Smoke demo did not complete all required remote stages with an accepted cited answer.", file=sys.stderr)
                print(render_markdown(response, include_trace=True), file=sys.stderr)
                return 2
            print(render_markdown(response, include_trace=True))
            return 0
        if args.command == "eval-retrieval":
            report = evaluate_retrieval(args.index, args.cases, limit=args.limit)
            print(f"Retrieval Hit@{report['limit']}: {report['passed']}/{report['total']} ({report['hit_at_k']:.0%})")
            for item in report["details"]:
                status = "PASS" if item["hit"] else "FAIL"
                print(f"- {status} {item['company']}: {item['question']}")
            return 0 if report["passed"] == report["total"] else 2
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
        response = agent.ask(
            args.question,
            user_id=args.user,
            company=args.company,
            include_web=args.web,
            limit=args.limit,
        )
        if args.json:
            print(json.dumps(response.to_dict(), ensure_ascii=False, indent=2))
        elif args.html:
            print(render_html(response, include_trace=args.trace))
        else:
            print(render_markdown(response, include_trace=args.trace))
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
