# 项目文件说明

## 1. 项目定位与交付边界

本项目是一个可本地运行、证据优先的金融研究 Personal Agent。它不执行交易、不输出投资建议，也不把模型生成的文字当作数据源。它的主路径是：下载公开数据，保留可追溯元数据，检索本地证据，再由两个指定模型完成受约束的分析和核验；没有模型密钥时，仍返回明确标识为离线提取模式的带引用结果。

仓库源码不包含下载后的 SEC 原始 HTML、市场 CSV、索引和用户记忆。这些内容可能较大、可能过期或包含个人偏好，因此由 `.gitignore` 排除，但 README 中的命令可完整复现。

## 2. 目录与文件清单

| 路径 | 作用 | 是否进入 Git |
| --- | --- | --- |
| `.env.example` | 两个模型、SEC User-Agent 的环境变量模板；没有真实密钥 | 是 |
| `.gitignore` | 忽略 `.env`、虚拟环境、生成数据、SEC 原始文件、缓存 | 是 |
| `pyproject.toml` | Python 包元数据、`src` 布局和 `finagent` 命令入口 | 是 |
| `requirements-dev.txt` | 可选 `pytest`、`coverage` 开发依赖；运行时无第三方依赖 | 是 |
| `README.md` | 英文安装、配置、数据下载、命令、数据来源和限制说明 | 是 |
| `DESIGN.md` | 英文 1-2 页系统设计、取舍、失败模式与后续路线 | 是 |
| `DEMO_OUTPUTS.md` | 实际运行与确定性测试产生的示例输出 | 是 |
| `PROJECT_FILES_CN.md` | 本文件，中文文件级和运行级说明 | 是 |
| `REMEDIATION_CN.md` | 对审查意见的逐项采纳、延期和依据 | 是 |
| `scripts/download_sec_10k.py` | 保留题目期望的 SEC 下载脚本入口，内部转发到 CLI | 是 |
| `scripts/download_market_data.py` | 市场数据下载脚本入口，内部转发到 CLI | 是 |
| `src/finagent/__init__.py` | 包说明和版本号 | 是 |
| `src/finagent/__main__.py` | 支持 `python -m finagent` | 是 |
| `src/finagent/cli.py` | argparse 命令、UTF-8 控制台配置、错误边界、Markdown/JSON 输出 | 是 |
| `src/finagent/agent.py` | Agent 编排、规划检索扩展、市场/Web 证据、草稿/核验守卫、引用渲染 | 是 |
| `src/finagent/models.py` | 仅配置 `doubao-seed-evolving` 与 `deepseek-v4` 的 OpenAI 兼容 HTTP 调用和离线降级 | 是 |
| `src/finagent/retrieval.py` | 中英文 tokenizer、BM25、chunk、索引 JSON 读写 | 是 |
| `src/finagent/ingest.py` | SEC HTML 文本化、排版归一化、inline-XBRL 噪声过滤和索引构建 | 是 |
| `src/finagent/sec.py` | 十家公司配置、SEC User-Agent 验证、下载、manifest 保护性追加 | 是 |
| `src/finagent/market.py` | 腾讯财经年度 K 线下载、三大指数批量入口、市场快照和 CSV 校验 | 是 |
| `src/finagent/websearch.py` | DuckDuckGo HTML 搜索、跳转 URL 解包、结果片段解析 | 是 |
| `src/finagent/memory.py` | 用户 ID 隔离的 JSON 长期偏好存储与显式意图检测 | 是 |
| `src/finagent/sources.py` | `EvidenceChunk`、`Citation`、`SearchResult` 的稳定数据结构 | 是 |
| `tests/test_finagent.py` | 单元与集成测试：来源、检索、记忆、模型守卫、市场、SEC、CLI、Web | 是 |
| `data/market/` | 生成的市场 CSV 与 `.meta.json`；当前可有 `csi300.csv`、`sse_composite.csv` | 否 |
| `data/index/` | 生成的 `filing_chunks.json` | 否 |
| `data/memory/` | 用户偏好 JSON；不应提交 | 否 |
| `sample_docs/sec_10k/` | SEC 原始 HTML、`manifest.jsonl`、`download_report.json` | 否 |

## 3. 安装与最短可运行路径

环境要求为 Python 3.11+；实际验证使用 Python 3.14。PowerShell 示例：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e . --no-build-isolation
Copy-Item .env.example .env
$env:SEC_USER_AGENT = "FinancialAgent your-email@example.com"
python -m finagent download-markets --output-dir data/market --start-year 2005
python scripts/download_sec_10k.py --years 1 --output-dir sample_docs/sec_10k
python -m finagent index --docs-dir sample_docs/sec_10k --output data/index/filing_chunks.json
python -m finagent ask "Summarize liquidity and debt-related risks." --company Apple --trace
```

SEC 下载会请求 Apple、Microsoft、NVIDIA、Amazon、Alphabet、Tesla、JPMorgan、Berkshire Hathaway、Walmart、Exxon Mobil 的最近 10-K。`--years 5` 会在 SEC recent submissions 中选择每家公司最近五份 10-K。SEC User-Agent 必须使用提交者自己的应用名和可联系邮箱。

## 4. CLI 命令与输入输出

| 命令 | 关键参数 | 结果 |
| --- | --- | --- |
| `download-sec` | `--output-dir`、`--years`、`--user-agent` | 下载原始 10-K，写 `manifest.jsonl` 与 `download_report.json` |
| `download-market` | `--output`、`--symbol`、`--start-year`、`--end-year` | 下载一个指数。`sh000300`、`sh000001`、`sz399001` 分别对应沪深 300、上证综指、深证成指 |
| `download-markets` | `--output-dir`、年份范围 | 顺序下载上述三组数据到独立 CSV；任一网络失败可改用单指数命令重跑 |
| `index` | `--docs-dir`、`--output`、`--chunk-size` | 从 manifest 对应 HTML 构建本地 chunk 索引 |
| `market` | `--file`、`--start`、`--end` | 输出日收盘价、区间涨跌幅、平均成交量的 Markdown 表格和来源 URL |
| `ask` | 问题、`--company`、`--user`、`--web`、`--json`、`--trace`、`--market-file` | 输出带 `[S#]` 引用的 Markdown 或 JSON；可选 Web、用户记忆、执行轨迹 |

命令层会捕获数据文件、JSON、输入参数和网络相关的可预期异常，向 stderr 输出 `Error: ...` 并返回退出码 2，不把 Python traceback 暴露给普通用户。启动时将 stdout/stderr 配置为 UTF-8，避免 10-K 中的项目符号或智能引号在 Windows GBK 控制台导致失败。

## 5. 数据生命周期与可追溯字段

### SEC 10-K

下载器先访问 `https://data.sec.gov/submissions/CIK##########.json`，再下载 `https://www.sec.gov/Archives/...` 的 primary document。每条 manifest 记录至少含 `document_id`、ticker、公司名、CIK、form、report/filing date、accession number、primary document、archive URL、本地文件名、下载时间和 `source_type=sec_10k`。重复运行时先读取旧 manifest；相同 `document_id` 不重复写入，不同历史记录不会被覆盖。损坏的 manifest 会拒绝写入并报明行号，防止悄悄丢失来源。

### A 股指数

腾讯财经 K 线接口单次返回有行数上限，因此下载器按自然年请求。每一个 CSV 只有 `date,close,volume` 三列；同名 `.meta.json` 保存 symbol、来源名、端点、完整 request URL 列表、下载 UTC 时间、行数、覆盖起止日期和字段语义。`market_snapshot()` 会在计算前检查三列是否完整，至少需要两行数据。

### 索引与引用

HTML 解析会去掉脚本、样式、inline-XBRL header/hidden/resources/context/unit，再归一化空白和常见排版符号。包含两个或更多 schema/context 噪声标识的 chunk 不进入索引。每个可检索 chunk 保存 `chunk_id`、`document_id`、title、text、source URL、日期、类型和 locator。最终引用同时显示 accession 和 chunk ID，因此能从答案回到 SEC Archive，再回到本地索引片段。

## 6. Agent、模型和检索流程

1. CLI 接收问题、用户 ID、公司过滤和可选 Web/市场文件。
2. `PreferenceStore` 仅在“我关心”“focus”“I'm interested in”“关注/偏好/感兴趣”等显式表达出现时，写入六类可审计偏好；普通问题不写长期记忆。
3. DeepSeek V4 规划器只返回最多八个检索词或短语。代码仅取其最多 24 个 tokenizer 结果，并始终保留原问题和偏好；规划文本不能成为答案或证据。
4. `LocalRetriever` 用 BM25 检索。英文按词，中文连续文本切为滑动 bigram，降低整句中文全匹配失败的概率。
5. 可选 DuckDuckGo 结果以 `web_search` 独立类型加入；市场快照以 `market_data` 独立类型加入。市场文件丢失或损坏会出现在 `warnings`，不会静默消失。
6. Doubao `doubao-seed-evolving` 只能根据已给证据起草；DeepSeek V4 再核验并改写。若远程回答没有合法 `[S#]`，系统拒绝它，退回离线提取答案。
7. Markdown 输出显示答案、Sources、可选 Data warnings、可选 Agent trace；JSON 输出包含同等结构化字段。

模型密钥只能来自环境变量或 `.env`：`DOUBAO_API_KEY`、`DEEPSEEK_API_KEY`。没有密钥或远程请求失败时，trace 明确记录 `offline` 和原因。代码不会打印密钥、Authorization header 或模型请求体。

## 7. 输出结构

`AgentResponse.to_dict()` 的字段为：`answer`、`citations`、`preferences`、`model_trace`、`evidence_count`、`warnings`。每个 citation 为 `label`、title、`source_url`、`published_at`、`source_type`、`document_id`、locator。`warnings` 用于数据缺失、损坏或无法解析等非致命情况；无证据时答案明确拒绝推断。

## 8. 测试与已验证行为

测试命令：

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall -q src scripts tests
```

当前测试覆盖：chunk 来源字段、BM25 排序、中文 bigram、市场快照与坏 CSV、三大指数批量参数、显式偏好与持久化、离线模型状态、规划词影响检索、核验改写草稿、SEC User-Agent、manifest 历史记录保留、XBRL 噪声识别、索引到 Agent、Web URL 解包、Web 证据类型、UTF-8 控制台配置、CLI 友好错误和市场数据 warning。没有把网络请求或真实模型调用写入单元测试；这些调用以 mock 隔离，真实命令记录在 `DEMO_OUTPUTS.md`。

## 9. 已知限制与现场使用建议

- BM25 仍是词法检索。`top-line pressure` 与只出现 `revenue decline` 的段落可能不匹配；这是明确展示的限制，不应在 demo 中夸大为语义搜索。
- HTML 展平无法保证复杂表格列关系；需核验数字时应打开 SEC 原文，后续优先改为 XBRL fact 级别抽取。
- DuckDuckGo 结果仅是搜索片段，可能变化，不能替代原始 filing。
- `data/memory` 为单用户 demo 的本地明文 JSON，不具备认证、加密、并发控制和删除 API。
- `download-markets` 依赖公开网络且按年度串行下载；现场网络慢时可优先跑已下载的 CSI 300 或单独重试某一 symbol。
- 输出支持 Markdown、文本和 JSON；HTML/PPT 没有实现，因为本次优先保证引用、离线运行和数据复现。
