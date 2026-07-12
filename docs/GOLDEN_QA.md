# 黄金问答与逐句引用核验

`evals/golden_answers.json` 保存 3 组人工可读的黄金问答，共 6 个事实句。它与检索 Hit@5 评测相互独立：检索评测检查目标 chunk 是否进入前五，黄金答案评测检查每个交付句子是否显式引用已登记的 chunk，以及人工指定的关键证据短语是否确实出现在该 chunk 原文中。

## 当前用例

| ID | 问题 | 逐句核验点 | 来源 chunk |
| --- | --- | ---: | --- |
| `apple-liquidity-debt` | Apple 流动性和债务情况 | 2 句：`$132.4B` 现金与证券；`$91.3B` notes 和 12 个月内 `$12.4B` | `aapl-...:0105` |
| `microsoft-year-over-year-results` | Microsoft 收入和盈利同比 | 2 句：收入 `+$36.6B / +15%`；经营利润 `+$19.1B / +17%` | `msft-...:0139` |
| `amazon-competition` | Amazon 竞争披露 | 2 句：竞争加剧；更高支出或更低价格可能压低销售和利润 | `amzn-...:0021` |

完整答案、引用映射和 required evidence phrases 以 JSON 文件为准，避免文档副本成为第二事实源。

## 核验规则

对每个 `sentence_support` 项，程序同时要求：

1. 句子完整出现在黄金答案中。
2. 声明的 `[S#]` 标签紧邻该句，不能借用后续句子的引用，也不能附带未声明标签。
3. 每个标签映射到索引中真实存在的 chunk ID。
4. 所有 `required_evidence_phrases` 经大小写和空白归一化后都存在于这些 chunk 的原文。
5. 黄金答案除空白外必须被 `sentence_support` 完整覆盖；任何未登记句子或游离引用都会使整个用例失败。

任一条件失败，该句和所属问答均失败，CLI 返回退出码 2。报告同时给出实际紧邻标签和未覆盖答案文本，便于定位数据问题。该核验是可重复的字符串级审计，不声称自动证明开放域语义蕴含。

```powershell
python -m finagent eval-golden
```

2026-07-12 的脱敏真实输出：

```text
Golden answers: 3/3; sentence citations: 6/6
- PASS apple-liquidity-debt: Summarize liquidity and debt-related risks.
- PASS microsoft-year-over-year-results: How did revenue or profitability change compared with the prior year?
- PASS amazon-competition: What does the company say about competition?
```
