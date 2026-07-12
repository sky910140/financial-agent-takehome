# Evidence-First Financial Agent

[![CI](https://github.com/sky910140/financial-agent-takehome/actions/workflows/ci.yml/badge.svg)](https://github.com/sky910140/financial-agent-takehome/actions/workflows/ci.yml)

[中文](README.md) | English

A locally runnable, traceable, and verifiable personal financial research agent. It retrieves sourced evidence from SEC 10-K filings, major A-share indices, and optional public Web results before `doubao-seed-evolving` drafts an answer and DeepSeek V4 plans and verifies it. If remote stages, citations, or numeric checks fail, the system explicitly falls back to an offline extractive answer.

This project does not provide investment advice, execute trades, or treat model training knowledge as a current data source.

## Verifiable Snapshot

| Area | Current result |
| --- | --- |
| SEC corpus | Latest 10-K for 10 companies, 3,978 searchable chunks |
| China market data | CSI 300, Shanghai Composite, Shenzhen Component, 20+ years of daily close and volume |
| Retrieval evaluation | 5 golden questions, Hit@5 = 5/5 |
| Golden answer audit | 3 Q&A cases, 6/6 sentences verified against cited evidence phrases |
| Automated tests | 60/60 passing, 88% total coverage |
| Python compatibility | 3.11, 3.13, and 3.14 verified locally |
| Multi-model path | DeepSeek planning → Doubao drafting → DeepSeek verification |
| Strict remote path | Doubao + DeepSeek three-stage smoke reached `remote_verified` |
| Output formats | Markdown, JSON, self-contained safe HTML |
| Failure behavior | Explicit fallback for model, network, citation, or numeric-guard failures |

## Architecture

```mermaid
flowchart TB
    U["Question + company + user ID"] --> M["Explicit preference memory"]
    M --> P["DeepSeek V4<br/>bounded retrieval planning"]

    subgraph DATA["Sourced data and evidence"]
        S["Local SEC 10-K index"]
        K["A-share index CSV + SHA-256"]
        W["Optional Web Search snippets"]
    end

    P --> R["BM25 retrieval / deterministic market calculation"]
    S --> R
    K --> R
    W --> R
    R --> E["Numbered evidence [S1]...[S#]<br/>URL + date + accession + chunk ID"]
    E --> A["Doubao<br/>evidence-only draft"]
    A --> V["DeepSeek V4<br/>verification against the same evidence"]
    V --> G{"Program guards<br/>remote stages + citations + numbers"}
    G -->|"pass"| O["Markdown / JSON / HTML<br/>answer + used sources + trace"]
    G -->|"fail"| F["Offline extractive fallback<br/>with an explicit reason"]
```

The key design choice is not simply calling two models. It is separating responsibilities and keeping the final trust decision in deterministic code. See [DESIGN.md](DESIGN.md) for the full tradeoff discussion.

## Five-Minute Reviewer Path

Python 3.11+ is required. The runtime has no mandatory third-party dependency. The checked-in market files and SEC retrieval index make the core demo runnable without downloading external data.

Windows PowerShell:

```powershell
git clone https://github.com/sky910140/financial-agent-takehome.git
cd financial-agent-takehome
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

macOS / Linux:

```bash
git clone https://github.com/sky910140/financial-agent-takehome.git
cd financial-agent-takehome
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Run the complete onsite path with one command. It explicitly disables remote model credentials, makes no network request, and uses temporary memory outside the repository:

```powershell
python -m finagent offline-demo
```

Expected output:

```text
Data integrity: PASS (10 filings, 3978 chunks, 3 market datasets)
Market deterministic calculation: 1412.12 -> 4780.79 = 238.55%
Retrieval Hit@5: 5/5
Golden sentence citations: 6/6
Offline cited Q&A: PASS (4 cited chunks)
Memory lifecycle: PASS (write/read/influence/modify/clear)
OFFLINE DEMO: PASS
```

Use the remaining minutes for targeted inspection:

```powershell
python -m finagent eval-golden
python -m finagent data-integrity
python -m finagent ask "Summarize liquidity and debt-related risks." --company Apple --trace
python -m finagent ask "I care about cash flow and debt maturity." --company JPM --user onsite
python -m finagent memory show --user onsite
python -m finagent memory set --user onsite --preferences "liquidity risk"
python -m finagent ask "What should I focus on?" --company JPM --user onsite --json
python -m finagent memory clear --user onsite
```

Without credentials, output explicitly reports `execution_mode=offline_extractive` and the fallback reason while preserving SEC URL, filing date, document ID, accession, chunk ID, evidence SHA-256, and retrieval score.

Onsite checklist: confirm Python 3.11+; run `offline-demo` before relying on network access; require exit code 0 and the final `PASS`; open one `[S#]` SEC URL and inspect accession/chunk/hash; verify numeric output labels disclosed versus deterministically calculated values; clear the demo memory; configure `.env` and run `smoke-demo` only when the remote path is explicitly requested. See the [failure matrix](docs/FAILURE_MATRIX.md) for exact degradation and exit behavior.

## Configure the Two Required Models

```powershell
Copy-Item .env.example .env
```

Fill in the following variables. `.env` is Git-ignored and must never be committed.

```dotenv
DOUBAO_API_KEY=your_Ark_API_key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3/chat/completions
DOUBAO_MODEL=doubao-seed-evolving

DEEPSEEK_API_KEY=your_DeepSeek_API_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/chat/completions
DEEPSEEK_MODEL=deepseek-v4-pro
```

Verify connectivity first, then require the complete remote path:

```powershell
python -m finagent verify-models
python -m finagent smoke-demo
```

`verify-models` sends only a fixed `READY` request and no financial documents. `smoke-demo` exits successfully only when planning, drafting, and verification all use the remote models and the final citation and numeric guards pass.

Expected trace:

```text
planning: deepseek / deepseek-v4-pro / remote=True / ok
analysis: doubao / doubao-seed-evolving / remote=True / ok
verification: deepseek / deepseek-v4-pro / remote=True / ok
```

## Representative Demos

```powershell
# Main risk factors
python -m finagent ask "What are this company's main risk factors?" --company Tesla --trace

# Prior-year revenue and profitability change
python -m finagent ask "How did revenue or profitability change compared with the prior year?" --company Microsoft --trace

# Competition disclosures
python -m finagent ask "What does the company say about competition?" --company Amazon --trace

# Long-term preference memory
python -m finagent ask "I care most about liquidity risk and debt maturity." --company JPM --user alice
python -m finagent ask "What should I focus on?" --company JPM --user alice --json --trace

# Optional public Web discovery; snippets remain labelled web_search
python -m finagent ask "Apple 10-K SEC filing" --company Apple --web --trace
```

Recorded commands and outputs are available in [DEMO_OUTPUTS.md](DEMO_OUTPUTS.md).

## Output Formats

Markdown is the default. Use `--json` for integrations, `--html` for a self-contained browser report, and `--trace` for non-sensitive execution status.

```powershell
python -m finagent ask `
  "Summarize liquidity and debt-related risks." `
  --company Apple `
  --html `
  --trace |
  Set-Content -Encoding utf8 apple-liquidity-report.html

Start-Process .\apple-liquidity-report.html
```

The HTML renderer escapes dynamic text, links only absolute HTTP(S) sources, and includes a restrictive Content Security Policy. `--json` and `--html` are mutually exclusive.

## Data and Provenance

| Dataset | Checked-in artifact | Preserved provenance |
| --- | --- | --- |
| SEC 10-K | `data/index/filing_chunks.json` | company, CIK, filing/report date, accession, SEC URL, document/chunk ID |
| CSI 300, Shanghai Composite, Shenzhen Component | `data/market/*.csv` and `.meta.json` | endpoint, every yearly request URL, download time, coverage, SHA-256 |
| Public Web | request-local `web_search` evidence | title, result URL, snippet; never silently promoted to parsed SEC evidence |
| User preferences | local `data/memory/preferences.json` | explicit allow-listed preferences only; never committed |

`data/DATA_SNAPSHOT.json` is the checked 2026-07-12 snapshot. It lists ticker, issuer, CIK, report date, filing date, accession, SEC URL, and chunk count for every 10-K, plus source, download time, coverage dates, row count, and SHA-256 for all three market datasets. CSV close and volume are source-disclosed observations; period return and average volume are deterministic Python calculations; model prose is interpretation only. `python -m finagent data-integrity` recomputes and checks the snapshot.

Raw SEC HTML is excluded to keep the repository small. The download and rebuild path remains reproducible:

```powershell
$env:SEC_USER_AGENT = "FinancialAgent your-email@example.com"
python scripts/download_sec_10k.py --years 1 --output-dir sample_docs/sec_10k
python -m finagent index --docs-dir sample_docs/sec_10k --output data/index/filing_chunks.json
python -m finagent download-markets --output-dir data/market --start-year 2005
```

## Tests and Evaluation

```powershell
python -m pip install -r requirements-dev.txt
$env:PYTHONPATH = "src"
python -m coverage run -m unittest discover -s tests
python -m coverage report --fail-under=80
python -m compileall -q src scripts tests
python -m finagent eval-retrieval
python -m finagent eval-golden
python -m finagent data-integrity
python -m finagent offline-demo
```

Coverage includes SEC recent/history downloads, incomplete-download exit behavior, XBRL noise filtering, BM25 and financial phrase handling, market dates, checksums, NaN/Inf rejection, preference memory, per-stage model budgets, empty model responses, mandatory verification, numeric drift, adjacent sentence-citation binding, full golden-answer coverage, Web evidence classification, CLI errors, and safe HTML rendering.

GitHub Actions runs compilation, coverage, retrieval evaluation, golden-answer verification, data integrity, and the offline demo on Python 3.11 and 3.13 without model credentials or external network access.

## Repository Layout

```text
src/finagent/                 Agent, retrieval, models, data, memory, and output
src/finagent/integrity.py     SEC/market snapshot and integrity gates
scripts/                      SEC and market download entry points
tests/                        60 unit, integration, and review-readiness tests
evals/                        Retrieval and golden-answer evaluation sets
data/index/                   Checked-in SEC retrieval index
data/market/                  Three index CSV files and provenance metadata
data/DATA_SNAPSHOT.json       Audited records, methodology, and SHA-256 values
docs/                         Golden audit, failure matrix, and implementation map
DESIGN.md                     1-2 page architecture and tradeoff document
DEMO_OUTPUTS.md               Reproducible commands and recorded outputs
```

## Known Boundaries

- BM25 is interpretable lexical retrieval, not open-domain semantic search. The current 5/5 result applies only to five golden questions.
- Flattened HTML cannot preserve every complex financial-table relationship. Numeric claims should be checked against the original filing; an XBRL fact layer is the next priority.
- Public Web results are variable and snippets are not first-party financial evidence.
- The numeric guard rejects values absent from the supplied evidence but does not prove semantic entailment for every non-numeric claim.
- Local preference memory supports user-scoped read, allow-listed modification, and clear operations with atomic file replacement. It still lacks authentication, encryption, cross-process locking, and retention policy, so it is not production storage.
- The current interface is CLI plus static HTML rather than a multi-turn chat UI, prioritizing reproducibility, citations, and explicit failure behavior.

Further reading:

- [System design](DESIGN.md)
- [Reproducible demo outputs](DEMO_OUTPUTS.md)
- [Project structure and implementation map](docs/PROJECT_STRUCTURE_CN.md)
- [Market data notes](data/market/README_EN.md)
- [Golden Q&A and sentence citation audit](docs/GOLDEN_QA.md)
- [Failure matrix and fallback behavior](docs/FAILURE_MATRIX.md)
- [Data snapshot](data/DATA_SNAPSHOT.json)
