# System Design

## Goal and boundary

The system is a personal financial research agent, not an autonomous trading or recommendation system. Its core promise is narrower: for a question about a supported filing or market dataset, it returns evidence that a reviewer can navigate back to. This prioritizes traceability over a broad but unverifiable tool catalogue.

The supported corpus is ten named public companies' SEC 10-Ks plus CSI 300, Shanghai Composite, and Shenzhen Component daily close and volume from 2005 onward. An opt-in web-search tool gives the agent a way to discover public information, but its result snippet is never silently mixed with primary filings. Every source says whether it is `sec_10k`, `market_data`, or `web_search`.

```mermaid
flowchart LR
  Q["Question + user ID"] --> M["Preference store"]
  M --> P["DeepSeek V4: research plan"]
  P --> R["Local BM25 retrieval"]
  D["SEC 10-K chunks / CSI 300 CSV / optional web"] --> R
  R --> A["doubao-seed-evolving: evidence-bound draft"]
  A --> V["DeepSeek V4: citation verification"]
  V --> O["Markdown / JSON answer + source list + trace"]
```

## Data ingestion and provenance

The SEC downloader first queries each company's `data.sec.gov/submissions` feed, selects `10-K` rows, then downloads the primary document from SEC Archives. It enforces a SEC-style User-Agent containing a contact email. The append-only `manifest.jsonl` records CIK, ticker, form, filing/report dates, accession number, archive URL, local path, and fetch time. The corresponding raw HTML is retained locally. If a company fails, `download_report.json` exposes it instead of presenting an incomplete corpus as complete.

CSI 300 data comes from Tencent Finance's public K-line endpoint. The endpoint caps a response, so the loader requests one calendar year at a time. It writes normalized `date,close,volume` CSV plus a metadata sidecar with source endpoint, all request URLs, download time, row count, and coverage. Calculated period changes always cite that data file and source endpoint, rather than relying on a model calculation.

The indexer strips script/style content, hidden inline-XBRL header/resources, and high-density schema/context boilerplate before it splits text into overlapping chunks. Each chunk carries document and chunk IDs, title, source URL, filing date, source type, and accession locator. Those fields survive retrieval; the final source list renders both accession and chunk ID. This supports three debugging questions: “which document?”, “where on the public site?”, and “which exact retrieval fragment?”

## Retrieval, reasoning, and memory

Retrieval is deterministic BM25-style lexical scoring. English is tokenized by word and Chinese text by overlapping character bigrams, so a query such as `上海证券交易所` has several matchable terms instead of one all-or-nothing token. It is deliberately simpler than a vector database: the corpus is small, score inputs are inspectable, it runs with no hosted dependency, and it gives an offline demo path. A user can scope the corpus before retrieval with `--company`. User preferences are a separate JSON document keyed by user ID. The memory only writes when language explicitly signals a preference (for example, “I care”, “I'm interested in”, “focus”, or “关注”), avoiding the common failure where every question becomes permanent memory. It recognizes a small auditable preference vocabulary: liquidity risk, debt maturity, cash flow, profitability, competition, and valuation.

The required two-model collaboration has distinct jobs. DeepSeek V4 makes a bounded research plan and independently verifies the final draft's citation labels. `doubao-seed-evolving` writes the filing analysis from supplied evidence. The planner is not ceremonial: its output is restricted to at most 24 lexical retrieval tokens, appended to the original question and explicit preferences before BM25 runs. It can improve a vague question such as “What should I focus on?” by supplying `liquidity`, `debt`, and `maturity`, but it cannot introduce evidence or final claims. Prompts prohibit outside facts and require `[S#]` labels. Each remote request has a 600-token completion budget so the three serial stages remain usable in an interactive CLI; source evidence is not truncated by that output cap. A final guard rejects remote prose if it has no valid supplied citations; the system emits an offline extractive answer instead. The trace reveals whether each stage used a remote model without revealing credentials.

The verifier has a concrete, testable job rather than an aspirational one. The integration test feeds a cited liquidity chunk, a planner term list, an uncited Doubao draft, and a DeepSeek verifier response. The final answer is the verifier's cited `[S1]` rewrite, not the unsupported draft. This does not claim a measured quality delta between providers; it demonstrates the intended control boundary. Removing Doubao would remove the independently specialized drafting step, while removing the verifier would allow a cited-looking but unsupported draft to reach the user. A production comparison would require a labelled evaluation set and is intentionally not fabricated for this take-home.

I considered a general ReAct loop with arbitrary tools and autonomous retries, and a vector database plus embeddings. I did not choose either for this submission. They broaden functionality but add hidden model decisions, embedding provenance, service dependencies, and difficult-to-reproduce ranking. The constrained loop is easier to demonstrate live and easier to defend in an interview.

## Known limits and failure modes

- BM25 may miss semantically relevant language with little term overlap, even with Chinese bigrams. For example, a query using `top-line pressure` may not retrieve a passage that only says `revenue decline`; the demo documents this as a known lexical failure rather than hiding it. It also does not understand financial-table structure.
- HTML flattening can join table cells or damage unusual legacy character encodings. Citation links still let a user inspect the original filing.
- SEC filings can be amended, issuer names can change, and recent-submission feeds do not necessarily expose an arbitrary long history. The manifest exposes the selected accession and dates.
- Web results are snippets, may change or be low quality, and are not a substitute for opening the target page. They remain opt-in and separately typed.
- Preference extraction is intentionally narrow. It may miss nuanced preferences and does not infer profile data.
- The local JSON store has no encryption, authentication, concurrency control, retention policy, or user deletion endpoint. It is suitable for a single-user demo only.
- Remote APIs may fail, rate-limit, or use a model deployment name that differs from the configured default. The answer transparently falls back instead of concealing that failure.
- This system does not provide investment advice, execute trades, retrieve live security-level A-share prices, or guarantee numerical extraction from SEC tables.

## First improvements with more time

1. Add XBRL-aware statement extraction and table provenance. This would most improve year-over-year revenue, margin, debt maturity, and cash-flow answers because every number could link to a fact, unit, period, and filing context.
2. Add a hybrid retriever: financial-domain embeddings plus BM25, reranking, evaluation sets, and per-query retrieval diagnostics. This addresses vocabulary mismatch while retaining lexical explainability.
3. Expand market ingestion to major A-share indices and individual securities with vendor/source health checks, trading-calendar validation, adjustment semantics, and data freshness alerts.
4. Make memory a proper user-owned store with authentication, encryption, edit/delete controls, expiration, and explicit consent. The current JSON format is intentionally visible but not production-grade.
5. Add automated source regression tests, model-output citation precision/recall checks, and an evaluation dashboard before increasing the number of tools or documents.
