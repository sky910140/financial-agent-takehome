# 可复现 Demo 输出

以下结果于 2026-07-10 在本地生成：已下载十家配置公司的各一份最新 10-K，过滤并索引出 3,978 个 chunk，同时下载了截至 2026-07-10 的沪深 300、上证综指和深证成指数据。当时未配置模型密钥，因此应用明确显示为离线提取模式。

## 沪深 300 二十年快照

命令：

```powershell
python -m finagent market --file data/market/csi300.csv --start 2006-07-10 --end 2026-07-10
```

输出：

```text
| Symbol | Start | End | Start close | End close | Change | Avg volume |
| sh000300 | 2006-07-10 | 2026-07-10 | 1412.12 | 4780.79 | 238.55% | 117740769 |
Source: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
```

同名来源 sidecar 记录了 5,164 行数据，覆盖 2005-04-08 至 2026-07-10。

## Apple 流动性与债务风险

命令：

```powershell
python -m finagent ask "Summarize liquidity and debt-related risks." --company Apple --user demo-reviewer --trace
```

选取的输出：

```text
Offline extractive mode is active because one or both required model credentials are unavailable.

- The value and liquidity of the Company's cash, cash equivalents and marketable securities may fluctuate substantially. [S1]
- Adverse economic conditions can lead to limitations on the Company's ability to issue new debt and reduced liquidity. [S2]
- Apple stated that cash, cash equivalents and marketable securities totaled $132.4 billion as of September 27, 2025, and described ongoing operating cash generation and access to debt markets as sufficient for its stated cash requirements. [S3]
```

`[S1]` 至 `[S3]` 都指向同一份原始 filing，但对应不同的检索 chunk ID：Apple Inc. Form 10-K，2025-10-31 提交，accession `0000320193-25-000079`，可在 [SEC archive](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm) 复核。

trace 显示 DeepSeek V4 是规划器/核验器，`doubao-seed-evolving` 是分析器；当时三者均为 `remote=False`，因为未提供密钥。两个密钥都配置后，同一批证据会进入两模型协作 loop；远程输出只有保留合法 `[S#]` 标签时才会被接受。

## 安全的独立 HTML 报告

命令：

```powershell
python -m finagent ask "Summarize liquidity and debt-related risks." --company Apple --html --trace > apple-liquidity-report.html
```

生成的文件是可直接在浏览器打开的独立报告，包含回答、来源列表、记忆偏好、数据 warning 和可选的执行 trace。文件以 `<!doctype html>` 开头，不嵌入 JavaScript。模型、filing 和 Web 搜索带入的动态文字均会 HTML 转义；只有绝对 `http/https` 溯源 URL 才会成为外链，并带有 `rel="noopener noreferrer"` 和限制性的 Content Security Policy meta 策略。回归测试覆盖了回答中尝试注入 `<script>` 以及来源 URL 使用 `javascript:` 的情况。

## 上证综指二十年快照

命令：

```powershell
python -m finagent market --file data/market/sse_composite.csv --start 2006-07-10 --end 2026-07-10
```

输出：

```text
| Symbol | Start | End | Start close | End close | Change | Avg volume |
| sh000001 | 2006-07-10 | 2026-07-10 | 1734.33 | 3996.16 | 130.42% | 229070678 |
Source: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
```

来源 sidecar 记录了 5,225 行数据，覆盖 2005-01-04 至 2026-07-10。

## 深证成指二十年快照

命令：

```powershell
python -m finagent market --file data/market/szse_component.csv --start 2006-07-10 --end 2026-07-10
```

输出：

```text
| Symbol | Start | End | Start close | End close | Change | Avg volume |
| sz399001 | 2006-07-10 | 2026-07-10 | 4336.24 | 15046.67 | 247.00% | 256305088 |
Source: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
```

已提交的 sidecar 记录了 5,225 行数据，覆盖 2005-01-04 至 2026-07-10，并保存了 22 个年度来源请求 URL。

## 公开 Web 搜索

命令：

```powershell
python -m finagent ask "Apple 10-K SEC filing" --company no-such-company --web --trace
```

选取的输出：

```text
- FAQ Contact SEC Filings Details Form 10-K Oct 31, 2025 Annual Report HTML Format Download. [S1]

- [S1] SEC Filings - SEC Filings Details - Apple - investor.apple.com
  https://investor.apple.com/sec-filings/sec-filings-details/default.aspx?FilingId=18880179
  source_type=web_search; locator=search result snippet; chunk=web:1
- [S3] aapl-20250927
  https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm
  source_type=web_search; locator=search result snippet; chunk=web:3
```

这里展示的是有意保留的边界：搜索摘要被标为 `web_search`，即便结果链接到 SEC，也不会被升级为 SEC filing 证据。

## 偏好记忆、JSON 与 trace

命令：

```powershell
python -m finagent ask "I'm interested in cash flow and debt maturity." --company JPM --user demo-memory --json
python -m finagent ask "What should I focus on?" --company JPM --user demo-memory --json --trace
```

第二次回答中选取的字段：

```json
{
  "preferences": ["cash flow", "debt maturity"],
  "evidence_count": 7,
  "warnings": [],
  "model_trace": [
    {"stage": "planning", "provider": "offline", "model": "deepseek-v4-pro"},
    {"stage": "analysis", "provider": "offline", "model": "doubao-seed-evolving"},
    {"stage": "verification", "provider": "offline", "model": "deepseek-v4-pro"}
  ]
}
```

第一条命令只会把显式偏好写入 `data/memory/preferences.json`；第二条会在检索中复用这些偏好。被选中的证据包含 JPMorgan 关于长期债务、现金流对冲和到期相关现金流条件的披露；每条均带 SEC URL、accession 和 chunk locator。

## 跨公司 filing 检索

命令：

```powershell
python -m finagent ask "How did revenue or profitability change compared with the prior year?" --company Microsoft --trace
```

离线检索器返回了 Microsoft 2025 财年相对 2024 财年的经营结果 chunk，包括销售与市场费用增加 12 亿美元（5%），研发费用增加 30 亿美元（10%），并附有 2025-07-30 Microsoft 10-K archive URL 和 chunk locator。这是证据检索，不代表离线提取模式已经输出完整的盈利能力分析；配置两个指定模型后，会调用受约束的起草与核验流程。

## 规划、起草与验证器守卫

确定性的集成测试 `test_planning_terms_change_retrieval_and_verifier_rewrites_draft` 在不伪装调用云模型的情况下，验证协作契约：

```text
Question: "What should I focus on?"
DeepSeek plan terms: "liquidity debt maturity"
Retrieved evidence: "Liquidity risk is driven by debt maturities in 2027." [S1]
Doubao draft: "Unsupported growth claim without a citation."
DeepSeek verifier: "Verifier kept only cited evidence. [S1]"
Final answer: verifier output, not the unsupported draft.
```

该测试证明规划词确实影响检索，验证器也可以替换草稿。它不对不同模型的相对质量做没有依据的定量主张。

## 远程模型连通性检查

在配置两家 API key 后执行：

```powershell
python -m finagent verify-models
```

该命令只向 Doubao 和 DeepSeek 发送 `Return READY.`，对每家成功 provider 输出 `Verified <provider> / <model>`；任意一家不可用时以退出码 2 结束。它不会发送 filing、市场记录、偏好或用户问题。2026-07-11 在本地 `.env` 配置完成后的实际记录为：

```text
Verified doubao / doubao-seed-evolving
Verified deepseek / deepseek-v4-pro
```

## 有意展示的 BM25 失败案例

命令：

```powershell
python -m finagent ask "top-line pressure" --company Microsoft --trace
```

观察到的输出是 `No local evidence matched this question.`。Microsoft filing 可能讨论 revenue、sales 或 decline，却不含 `top-line` 或 `pressure` 两个词；系统会拒绝推断。这正是小型词法 BM25 索引的透明失败模式，也说明后续应引入经过评测的混合检索，而不是增加未记录的语义 fallback。
