# Recorded Demo Outputs

These outputs were generated locally on 2026-07-10 after downloading one latest 10-K for each of the ten configured companies, filtering and indexing 3,978 chunks, and downloading CSI 300 and Shanghai Composite data through 2026-07-10. Model keys were intentionally absent, so the application disclosed its offline extractive mode.

## Twenty-year CSI 300 snapshot

Command:

```powershell
python -m finagent market --file data/market/csi300.csv --start 2006-07-10 --end 2026-07-10
```

Output:

```text
| Symbol | Start | End | Start close | End close | Change | Avg volume |
| sh000300 | 2006-07-10 | 2026-07-10 | 1412.12 | 4780.79 | 238.55% | 117740769 |
Source: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
```

The source sidecar reported 5,164 rows covering 2005-04-08 through 2026-07-10.

## Apple liquidity and debt risk

Command:

```powershell
python -m finagent ask "Summarize liquidity and debt-related risks." --company Apple --user demo-reviewer --trace
```

Selected output:

```text
Offline extractive mode is active because one or both required model credentials are unavailable.

- The value and liquidity of the Company's cash, cash equivalents and marketable securities may fluctuate substantially. [S1]
- Adverse economic conditions can lead to limitations on the Company's ability to issue new debt and reduced liquidity. [S2]
- Apple stated that cash, cash equivalents and marketable securities totaled $132.4 billion as of September 27, 2025, and described ongoing operating cash generation and access to debt markets as sufficient for its stated cash requirements. [S3]
```

`[S1]` to `[S3]` each pointed to the same original filing with distinct retrieved chunk IDs: Apple Inc. Form 10-K, filed 2025-10-31, accession `0000320193-25-000079`, [SEC archive](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm).

The trace reported DeepSeek V4 as planner/verifier and `doubao-seed-evolving` as analyst, all `remote=False` because no credentials were supplied. With both configured, the same evidence is sent to the two-model loop and remote output is accepted only when it retains valid `[S#]` labels.

## Twenty-year Shanghai Composite snapshot

Command:

```powershell
python -m finagent market --file data/market/sse_composite.csv --start 2006-07-10 --end 2026-07-10
```

Output:

```text
| Symbol | Start | End | Start close | End close | Change | Avg volume |
| sh000001 | 2006-07-10 | 2026-07-10 | 1734.33 | 3996.16 | 130.42% | 229070678 |
Source: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
```

The sidecar reported 5,225 rows covering 2005-01-04 through 2026-07-10. `download-markets` also supports Shenzhen Component; the public endpoint was slow during this recorded run, so the README documents its independent retry command instead of claiming a file exists.

## Public web search

Command:

```powershell
python -m finagent ask "Apple 10-K SEC filing" --company no-such-company --web --trace
```

Selected output:

```text
- FAQ Contact SEC Filings Details Form 10-K Oct 31, 2025 Annual Report HTML Format Download. [S1]

- [S1] SEC Filings - SEC Filings Details - Apple - investor.apple.com
  https://investor.apple.com/sec-filings/sec-filings-details/default.aspx?FilingId=18880179
  source_type=web_search; locator=search result snippet; chunk=web:1
- [S3] aapl-20250927
  https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm
  source_type=web_search; locator=search result snippet; chunk=web:3
```

This demonstrates the intentional boundary: search snippets are cited as `web_search`, not upgraded to SEC filing evidence merely because the result links to SEC.

## Preference memory, JSON, and trace

Commands:

```powershell
python -m finagent ask "I'm interested in cash flow and debt maturity." --company JPM --user demo-memory --json
python -m finagent ask "What should I focus on?" --company JPM --user demo-memory --json --trace
```

Selected second-response fields:

```json
{
  "preferences": ["cash flow", "debt maturity"],
  "evidence_count": 7,
  "warnings": [],
  "model_trace": [
    {"stage": "planning", "provider": "offline", "model": "deepseek-v4"},
    {"stage": "analysis", "provider": "offline", "model": "doubao-seed-evolving"},
    {"stage": "verification", "provider": "offline", "model": "deepseek-v4"}
  ]
}
```

The first command writes only the explicit preferences to `data/memory/preferences.json`; the second reuses them in retrieval. The selected evidence included JPMorgan disclosures on long-term debt, cash-flow hedges, and maturity-related cash-flow conditions, each with SEC URL, accession, and chunk locator.

## Cross-company filing retrieval

Command:

```powershell
python -m finagent ask "How did revenue or profitability change compared with the prior year?" --company Microsoft --trace
```

The offline retriever returned Microsoft fiscal-2025 versus fiscal-2024 operating-results chunks, including sales-and-marketing expense increasing $1.2 billion (5%) and R&D increasing $3.0 billion (10%), with the 2025-07-30 Microsoft 10-K archive URL and chunk locators. This is evidence retrieval, not a claim that the extractive fallback has produced a complete profitability analysis; enabling both required models invokes the constrained draft-and-verify path.

## Plan, draft, and verifier guard

The deterministic integration test `test_planning_terms_change_retrieval_and_verifier_rewrites_draft` exercises the collaboration contract without pretending a cloud model was called:

```text
Question: "What should I focus on?"
DeepSeek plan terms: "liquidity debt maturity"
Retrieved evidence: "Liquidity risk is driven by debt maturities in 2027." [S1]
Doubao draft: "Unsupported growth claim without a citation."
DeepSeek verifier: "Verifier kept only cited evidence. [S1]"
Final answer: verifier output, not the unsupported draft.
```

The test proves the plan is actually used for retrieval and the verifier can replace a draft. It does not make an unsupported quantitative claim about relative model quality.

## Known BM25 failure, shown deliberately

Command:

```powershell
python -m finagent ask "top-line pressure" --company Microsoft --trace
```

Observed output: `No local evidence matched this question.` The Microsoft filing may discuss revenue, sales, or declines without containing either lexical term `top-line` or `pressure`. The agent refuses to infer an answer. This is the intended transparent failure mode of a small lexical BM25 index and motivates a future evaluated hybrid retriever rather than an undocumented semantic fallback.
