# Financial Agent Take-Home

An evidence-first personal financial research agent for public financial documents and China index history. It answers from local SEC 10-K chunks and optional public-web snippets, then renders every source with a URL and locator. It is intentionally small enough to inspect and run live.

## What it demonstrates

- Public web search capability via DuckDuckGo HTML results, explicitly labelled `web_search` in citations.
- 20+ years of CSI 300 (`sh000300`) daily close and volume, fetched from Tencent Finance in annual windows with a reproducible metadata manifest.
- A SEC-compliant downloader for the most recent 10-K filings of Apple, Microsoft, NVIDIA, Amazon, Alphabet, Tesla, JPMorgan, Berkshire Hathaway, Walmart, and Exxon Mobil. `--years 5` gets five filings per company when present in the SEC recent-submission feed.
- Local BM25 retrieval over filing chunks. Every chunk retains source URL, filing date, document ID, accession locator, and chunk ID.
- Long-term, user-scoped preference memory for explicit statements such as “I care about liquidity risk and debt maturity.”
- A two-model agent loop: DeepSeek V4 plans and verifies citations; `doubao-seed-evolving` drafts from retrieved evidence. No third primary model is used. When either key is absent, the app returns an explicit offline extractive answer instead of pretending an LLM ran.
- Markdown output, source list, JSON mode, and a non-secret execution trace for demos.

This is a research assistant, not investment advice.

## Quick start

Prerequisite: Python 3.11+ (tested with Python 3.14). The runtime itself has no third-party dependency.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e . --no-build-isolation
Copy-Item .env.example .env
```

Set a real SEC-compliant identity before downloading filings. The value must include an application name and contact email.

```powershell
$env:SEC_USER_AGENT = "FinancialAgent your-email@example.com"
python -m finagent download-markets --output-dir data/market --start-year 2005
python scripts/download_sec_10k.py --years 1 --output-dir sample_docs/sec_10k
python -m finagent index --docs-dir sample_docs/sec_10k --output data/index/filing_chunks.json
```

`download-markets` requests CSI 300, Shanghai Composite, and Shenzhen Component as separate auditable files. Each request can also be retried independently with `download-market --symbol sh000001` or `--symbol sz399001`. The first SEC download collects ten companies' latest 10-Ks. To collect five annual filings per company, use `--years 5`; allow more time and ensure the identity is your own. Raw downloaded documents and generated data are deliberately ignored by Git, but the commands reproduce them without hidden steps.

Run an offline, fully cited demo without any model key:

```powershell
python -m finagent ask "Summarize liquidity and debt-related risks." --company Apple --user demo-reviewer --trace
python -m finagent market --file data/market/csi300.csv --start 2006-07-10 --end 2026-07-10
python -m finagent market --file data/market/sse_composite.csv --start 2006-07-10 --end 2026-07-10
```

To also search public web results, make that choice visible in the answer:

```powershell
python -m finagent ask "What did Apple disclose about competition?" --company Apple --web
```

## Model configuration

Copy `.env.example` to `.env`, then supply only the two permitted primary model credentials:

```text
DOUBAO_API_KEY=...
DOUBAO_MODEL=doubao-seed-evolving
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-v4
```

The default endpoints are Ark's OpenAI-compatible chat endpoint and DeepSeek's chat endpoint; override `DOUBAO_BASE_URL` or `DEEPSEEK_BASE_URL` only if the provider's deployment endpoint differs. Keys are read from environment or `.env`, never logged, and `.env` is ignored by Git.

With both keys configured, the execution trace should show:

```text
planning: deepseek / deepseek-v4 / remote=True
analysis: doubao / doubao-seed-evolving / remote=True
verification: deepseek / deepseek-v4 / remote=True
```

If a remote call fails or its answer has no valid evidence label, the agent falls back to the local extractive response. This is intentional: availability must not become unsupported financial prose.

## Data and provenance

| Dataset | Loader | Local artefacts | Evidence fields |
| --- | --- | --- | --- |
| CSI 300, Shanghai Composite, Shenzhen Component daily close and volume | Tencent Finance K-line endpoint, annual windows | `data/market/csi300.csv`, `sse_composite.csv`, `szse_component.csv`, each with `.meta.json` | source endpoint, every request URL, download timestamp, coverage, row count |
| SEC 10-K filings | `data.sec.gov` submissions plus SEC Archives | `sample_docs/sec_10k/*.html`, `manifest.jsonl`, `download_report.json` | ticker, CIK, form, filing/report date, accession, primary document, archive URL, fetch time |
| Filing chunks | local HTML-to-text + deterministic chunker | `data/index/filing_chunks.json` | chunk/document ID, text, source URL, date, source type, accession locator |
| Public web | DuckDuckGo HTML query, only with `--web` | in-memory for this request | result URL, title, result snippet, `web_search` source type |

The agent uses a transparent BM25-style lexical retriever instead of an embedding service so a reviewer can rerun the path offline and inspect ranking input. It scopes filings with `--company` before retrieval; the company name or ticker is matched against manifest-derived title and ID.

## Reproducible questions

After the three setup commands above:

```powershell
python -m finagent ask "What are this company's main risk factors?" --company Tesla
python -m finagent ask "How did revenue or profitability change compared with the prior year?" --company Microsoft
python -m finagent ask "What does the company say about competition?" --company Amazon
python -m finagent ask "Summarize liquidity or debt-related risks." --company Apple
python -m finagent ask "What evidence supports this answer?" --company Walmart
python -m finagent ask "I care most about liquidity risk and debt maturity." --company JPM --user alice
python -m finagent ask "What should I focus on?" --company JPM --user alice
```

The first `alice` request persists only explicit preferences in `data/memory/preferences.json`; the second reapplies them to its retrieval query. `DEMO_OUTPUTS.md` contains a recorded output from the first market and Apple-risk commands using the 2026-07-10 data snapshot.

For machine integration, append `--json`; for the reviewer-facing explanation of model execution append `--trace`.

## Tests

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall -q src scripts tests
```

The test suite covers source-preserving chunks, relevant retrieval and citations, market calculations and provenance, memory persistence, offline model state, SEC manifest creation, index-to-agent integration, web evidence labelling, and SEC identity validation. `requirements-dev.txt` includes optional `pytest` and `coverage` for environments that use them.

## Design and limits

Read [DESIGN.md](DESIGN.md) for architecture, tradeoffs, failure modes, and prioritized next work. [PROJECT_FILES_CN.md](PROJECT_FILES_CN.md) is the complete Chinese file-and-operation reference; [REMEDIATION_CN.md](REMEDIATION_CN.md) maps the external review to implementation decisions. The key limitations are lexical rather than semantic retrieval, flattening of complex SEC tables, non-authoritative search snippets, a local single-process memory store, and no claim that offline extraction is a model-generated analysis.
