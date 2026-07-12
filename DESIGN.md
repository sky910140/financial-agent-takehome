# 系统设计说明

## 目标与边界

本系统是金融研究 Personal Agent，不是自动交易系统，也不输出投资建议。它的承诺刻意收窄：对于已支持的 filing 或市场数据问题，返回可让 reviewer 回溯的证据。这一取舍优先保证可追溯性，而不是堆叠大量无法验证的工具。

当前语料为十家指定公司的 SEC 10-K，以及自 2005 年起的沪深 300、上证综指、深证成指每日收盘价与成交量。可选 Web 搜索用于发现公开信息，但其结果摘要绝不会被静默混入一级 filing 证据。每一条来源都会明确标记为 `sec_10k`、`market_data` 或 `web_search`。

```mermaid
flowchart TB
  Q["问题 + 公司 + 用户 ID"] --> M["显式偏好记忆"]
  M --> P["DeepSeek V4：受限检索规划"]
  D["SEC 10-K 索引 / 指数 CSV / 可选 Web"] --> R["BM25 检索与市场确定性计算"]
  P --> R
  R --> E["编号证据集<br/>URL + 日期 + accession + chunk ID"]
  E --> A["doubao-seed-evolving：仅基于证据起草"]
  A --> V["DeepSeek V4：使用相同证据核验"]
  V --> G{"远程阶段、引用与数字守卫"}
  G -->|"通过"| O["Markdown / JSON / HTML<br/>答案 + 实际来源 + trace"]
  G -->|"失败"| F["离线提取式降级<br/>显示具体原因"]
```

## 数据接入与溯源

SEC 下载器先查询每家公司的 `data.sec.gov/submissions` feed，从 recent 表选择 `10-K`；当 `--years` 尚未满足时继续读取 SEC 声明的历史 submissions 文件，再从 SEC Archives 下载主文档。它强制要求符合 SEC 规范、且含联系邮箱的 User-Agent。追加式 `manifest.jsonl` 会记录 CIK、ticker、form、filing/report date、accession number、archive URL、本地路径和抓取时间；原始 HTML 随之保存在本地。任一公司下载失败时，`download_report.json` 会暴露失败，CLI 也会以非零状态结束，不把不完整语料伪装成完整结果。

沪深 300、上证综指和深证成指数据来自腾讯财经公开 K 线端点。由于单次响应有行数上限，下载器按自然年分段请求；输出规范化的 `date,close,volume` CSV，并写入 metadata sidecar，其中包含来源端点、全部请求 URL、下载时间、行数、覆盖区间和 SHA-256。程序拒绝 NaN/Inf、非递增或重复日期、非正收盘价、负成交量和 checksum 不匹配。区间涨跌由程序计算，不依赖模型。

索引器会移除 script/style、隐藏的 inline-XBRL header/resources 及高密度 schema/context 模板噪声，再把正文切为重叠 chunk。每个 chunk 保留文档与 chunk ID、标题、来源 URL、filing date、来源类型和 accession locator。这些字段会穿过检索流程，并在最终来源列表中显示 document ID、accession、chunk ID、证据 SHA-256、检索分数和受限摘录，支持定位文档、公开原文、命中片段，并核对本地证据是否变化。

## 检索、推理与记忆

检索使用确定性的 BM25 词法评分。英文移除通用问句停用词，连字符词同时保留整体与组成词，并为 `risk factors`、`cash flow`、`debt maturity`、`operating income` 等少量金融短语生成可审计 token；中文按重叠字符 bigram 切分。明确财务问题使用确定性领域扩词，只有很短的模糊问题才采用 DeepSeek 规划词，避免随机规划破坏重复运行。五个 retrieval cases 可通过 `eval-retrieval` 复现 Hit@5；另有三组黄金问答通过 `eval-golden` 对 6 个句子的引用标签、chunk 映射和支持短语逐句核验。

用户偏好独立保存在以 user ID 为键的 JSON 中。只有明确表达偏好时才写入，例如 “I care”、“I'm interested in”、“focus” 或“关注”；普通提问不会变成永久记忆。当前只识别可审计的小型白名单：liquidity risk、debt maturity、cash flow、profitability、competition 和 valuation。CLI 支持用户级 `show`、`set`、`remove` 和 `clear`，写盘使用原子替换；偏好会追加到检索 query，因而“写入、读取、影响、修改、清除”均有可观察行为。

两个指定模型承担不同职责。DeepSeek V4 生成受限检索计划，并独立核验最终草稿的引用标签；`doubao-seed-evolving` 仅根据提供的证据起草分析。规划器并非形式化步骤：其输出最多取 24 个 lexical retrieval token，追加到原问题和显式偏好后才进入 BM25。对于“我应该重点关注什么？”这类模糊问题，它可以补充 `liquidity`、`debt`、`maturity` 等检索词；但它不能引入证据或形成最终主张。提示词禁止外部事实，并要求使用 `[S#]` 标签。

三个远程阶段使用独立预算与超时。Doubao 起草显式关闭 thinking，使受证据约束的短答案能在交互式 CLI 中返回；DeepSeek 核验保留更高推理预算。网关把空正文视为失败。最终程序要求规划、起草、核验全部远程成功，并同时检查引用标签与数值集合；否则回退到离线提取式回答。市场来源值标记为 `disclosed`，Python 公式结果标记为 `calculated`，通过全部守卫的生成性文字才标记为 `model_interpretation`。模型不得自行做算术。

验证器是可测试的控制点，而不是抽象口号。测试覆盖验证器成功改写、验证器不可用时拒绝 Doubao 草稿、空模型正文、非法标签和数值漂移。`smoke-demo` 进一步要求三阶段真实远程成功并通过程序守卫。移除 Doubao 会失去独立起草阶段；移除验证器则会让貌似带引用但未经复核的草稿到达用户。

我考虑过带任意工具和自主重试的通用 ReAct loop，以及向量数据库加 embedding。它们能扩展功能面，却增加隐藏的模型决策、embedding 溯源、服务依赖和难以复现的排序。这个受约束的 loop 更适合现场演示，也更容易在面试中说明取舍。

## 已知限制与失败模式

- 即使有中文 bigram，BM25 仍可能漏掉词面重叠很少但语义相关的段落。例如 `top-line pressure` 未必能召回只写了 `revenue decline` 的文字；demo 公开展示这一词法失败，而非隐藏它。它也不理解复杂财务表格的列关系。
- HTML 展平可能把表格单元格拼接，或破坏罕见的旧字符编码。引用链接仍允许用户打开原始 filing 核验。
- SEC filing 可能修订、发行人名称可能变化，recent-submission feed 也不一定暴露任意长的历史；manifest 会明确记录本次选中的 accession 与日期。
- Web 结果是可变且质量不一的摘要，不能替代打开目标页面；它们始终是 opt-in 且独立标注的来源。
- 偏好提取故意保持保守，可能遗漏细腻表达，也不推断用户画像。
- 本地 JSON 记忆已有用户级修改和清除，但没有加密、认证、跨进程锁和保留策略，只适用于单用户 demo。
- 远程 API 可能失败、限流，或要求不同的模型部署名称。系统会透明地回退，而不是掩盖失败。
- HTML 报告是仅用标准库实现的静态展示层：所有动态内容都会转义，只有绝对 HTTP(S) 来源 URL 能成为链接，并嵌入限制性 CSP meta 策略。它不是交互式 Web 应用，也不渲染任意 Markdown 或用户 HTML。
- 本系统不提供投资建议、不执行交易、不获取实时 A 股个股数据，也不保证能从 SEC 复杂表格中准确抽取数值。

## 更多时间时的优先改进

1. 增加 XBRL-aware 报表抽取与表格溯源。这会首先改善同比收入、利润率、债务到期和现金流回答，因为每个数字都能链接到 fact、单位、期间和 filing context。
2. 增加混合检索：金融领域 embedding + BM25、reranker、评测集和逐查询检索诊断。它能缓解词汇失配，同时保留词法可解释性。
3. 扩展市场接入至更多主要 A 股指数和个股，同时加入数据源健康检查、交易日历校验、复权语义与新鲜度告警。
4. 将记忆升级为真正用户拥有的存储：认证、加密、并发控制、过期与显式同意。当前 JSON 的可见性是为了 demo 可解释性，而不是生产安全性。
5. 将当前 retrieval 和 sentence-level golden cases 扩展为人工标注的 section/claim 级评测集，并增加引用 precision/recall 与非数值 claim-evidence 审计面板。
