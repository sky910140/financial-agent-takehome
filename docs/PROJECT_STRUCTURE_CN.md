# 项目文件说明

## 1. 项目定位与交付边界

本项目是一个可本地运行、证据优先的金融研究 Personal Agent。它不执行交易、不输出投资建议，也不把模型生成的文字当作数据源。它的主路径是：下载公开数据，保留可追溯元数据，检索本地证据，再由两个指定模型完成受约束的分析和核验；没有模型密钥时，仍返回明确标识为离线提取模式的带引用结果。

仓库不包含下载后的 SEC 原始 HTML 和用户记忆，但已提交 6.8 MB filing 索引、三组市场 CSV 与来源元数据，使 fresh clone 可立即运行核心离线 demo。README 中的命令可重新下载原始文件并重建索引。

## 2. 目录与文件清单

| 路径 | 作用 | 是否进入 Git |
| --- | --- | --- |
| `.env.example` | 两个模型、SEC User-Agent 的环境变量模板；没有真实密钥 | 是 |
| `.gitignore` | 忽略 `.env`、虚拟环境、SEC 原始文件和记忆；显式放行 filing 索引与三组市场数据 | 是 |
| `.gitattributes` | 统一代码、文档和数据文件的 Git 行尾规则 | 是 |
| `.github/workflows/ci.yml` | 在 Python 3.11/3.13 上运行编译、覆盖率、检索/黄金问答、数据完整性和离线 demo | 是 |
| `pyproject.toml` | Python 包元数据、`src` 布局和 `finagent` 命令入口 | 是 |
| `requirements-dev.txt` | 可选 `pytest`、`coverage` 开发依赖；运行时无第三方依赖 | 是 |
| `README.md` | GitHub 首页的中文安装、配置、数据下载、命令、数据来源和限制说明 | 是 |
| `README_EN.md` | 英文安装、配置、数据下载、命令、数据来源和限制说明 | 是 |
| `DESIGN.md` | 中文 1-2 页系统设计、取舍、失败模式与后续路线 | 是 |
| `DEMO_OUTPUTS.md` | 中文说明的实际运行与确定性测试示例输出 | 是 |
| `docs/PROJECT_STRUCTURE_CN.md` | 本文件，中文文件级和运行级说明 | 是 |
| `docs/GOLDEN_QA.md` | 黄金答案逐句引用、紧邻标签和答案全覆盖规则 | 是 |
| `docs/FAILURE_MATRIX.md` | 模型、数据、评测与记忆失败时的降级和退出码 | 是 |
| `data/README.md` | SEC/市场数据来源、口径和完整性检查说明 | 是 |
| `scripts/download_sec_10k.py` | 保留题目期望的 SEC 下载脚本入口，内部转发到 CLI | 是 |
| `scripts/download_market_data.py` | 市场数据下载脚本入口，内部转发到 CLI | 是 |
| `src/finagent/__init__.py` | 包说明和版本号 | 是 |
| `src/finagent/__main__.py` | 支持 `python -m finagent` | 是 |
| `src/finagent/cli.py` | argparse 命令、UTF-8 控制台配置、错误边界、Markdown/JSON/HTML 输出 | 是 |
| `src/finagent/agent.py` | Agent 编排、规划检索扩展、市场/Web 证据、草稿/核验守卫、Markdown/安全 HTML 引用渲染 | 是 |
| `src/finagent/models.py` | 两个指定模型的 HTTP 调用、分阶段预算、Doubao non-thinking 和空响应降级 | 是 |
| `src/finagent/retrieval.py` | 停用词/金融短语/中文 bigram tokenizer、BM25、chunk、索引 JSON 读写 | 是 |
| `src/finagent/evaluation.py` | Hit@K 检索评测与黄金答案逐句引用核验 | 是 |
| `src/finagent/integrity.py` | SEC/市场数据 schema、元数据、行数、日期与 SHA-256 快照校验 | 是 |
| `src/finagent/ingest.py` | SEC HTML 文本化、排版归一化、inline-XBRL 噪声过滤和索引构建 | 是 |
| `src/finagent/sec.py` | 十家公司配置、SEC User-Agent 验证、下载、manifest 保护性追加 | 是 |
| `src/finagent/market.py` | 腾讯财经年度 K 线下载、三大指数批量入口、市场快照和 CSV 校验 | 是 |
| `src/finagent/websearch.py` | DuckDuckGo HTML 搜索、跳转 URL 解包、结果片段解析 | 是 |
| `src/finagent/memory.py` | 用户 ID 隔离的 JSON 长期偏好写入、读取、修改、清除与原子落盘 | 是 |
| `src/finagent/sources.py` | `EvidenceChunk`、`Citation`、`SearchResult` 的稳定数据结构 | 是 |
| `tests/test_finagent.py` | 单元与集成测试：来源、检索、记忆、模型守卫、市场、SEC、CLI、Web | 是 |
| `tests/test_review_readiness.py` | 提交前回归：引用审计、数据快照、非有限数值、记忆闭环和离线 demo | 是 |
| `data/market/` | 已提交的三组市场 CSV、`.meta.json` 和数据说明；支持离线市场 demo | 是 |
| `data/DATA_SNAPSHOT.json` | 10-K 与市场数据的受检记录数、日期、来源、口径和 hash | 是 |
| `evals/golden_answers.json` | 3 组黄金问答、6 个句子的 citation-to-chunk 支持映射 | 是 |
| `data/index/` | 已提交的十家公司 `filing_chunks.json` | 是 |
| `evals/retrieval_cases.json` | 五个代表性问题及预期 chunk | 是 |
| `.env`、`.env.*` | 本地模型密钥和 SEC 联系信息；仅 `.env.example` 可提交 | 否 |
| `.venv/`、`*.egg-info/`、`build/`、`dist/` | 本地解释器、安装和打包产物 | 否 |
| `.coverage*`、`coverage.xml`、`htmlcov/`、`.pytest_cache/` | 本地测试与覆盖率产物 | 否 |
| `__pycache__/`、`*.pyc`、`.ruff_cache/`、`.mypy_cache/` | Python、lint 和类型检查缓存 | 否 |
| `data/memory/` | 用户偏好 JSON；不应提交 | 否 |
| `sample_docs/sec_10k/` | SEC 原始 HTML、`manifest.jsonl`、`download_report.json` | 否 |
| `apple-liquidity-report.html` | `ask --html` 生成的本地演示报告 | 否 |

## 3. 安装与最短可运行路径

环境要求为 Python 3.11+；已在 Python 3.11、3.13 和 3.14 上实际验证。PowerShell 示例：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
python -m finagent ask "Summarize liquidity and debt-related risks." --company Apple --trace
python -m finagent eval-retrieval
```

SEC 下载会请求十家公司；当 recent 表不足以满足 `--years` 时继续读取历史 submissions 文件。少于请求数量时 CLI 返回 2。SEC User-Agent 必须使用提交者自己的应用名和可联系邮箱。

## 4. CLI 命令与输入输出

| 命令 | 关键参数 | 结果 |
| --- | --- | --- |
| `download-sec` | `--output-dir`、`--years`、`--user-agent` | 下载原始 10-K，写 `manifest.jsonl` 与 `download_report.json` |
| `download-market` | `--output`、`--symbol`、`--start-year`、`--end-year` | 下载一个指数。`sh000300`、`sh000001`、`sz399001` 分别对应沪深 300、上证综指、深证成指 |
| `download-markets` | `--output-dir`、年份范围 | 顺序下载上述三组数据到独立 CSV；任一网络失败可改用单指数命令重跑 |
| `verify-models` | 无参数；读取 `.env` 或环境变量 | 以固定 `READY` prompt 验证 Doubao 与 DeepSeek 连通性，不发送金融数据或用户内容 |
| `offline-demo` | 无参数；不读取 `.env` | 运行数据完整性、市场确定性计算、检索、逐句引用、离线问答和记忆闭环 |
| `eval-golden` | `--index`、`--cases` | 逐句核对引用标签、chunk 和证据短语 |
| `data-integrity` | `--index`、`--market-dir`、`--snapshot` | 重算快照并在不一致时返回退出码 2 |
| `memory` | `show/set/remove/clear`、`--user`、白名单偏好 | 完成长记忆读取、修改和用户级清除 |
| `smoke-demo` | 固定 Apple 问题、可选 `--limit` | 要求三阶段远程成功且最终守卫通过 |
| `eval-retrieval` | `--index`、`--cases`、`--limit` | 输出 golden-query Hit@K，失败时退出 2 |
| `index` | `--docs-dir`、`--output`、`--chunk-size` | 从 manifest 对应 HTML 构建本地 chunk 索引 |
| `market` | `--file`、`--start`、`--end` | 输出日收盘价、区间涨跌幅、平均成交量的 Markdown 表格和来源 URL |
| `ask` | 问题、`--company`、`--user`、`--web`、`--json`、`--html`、`--trace`、`--market-file` | 输出带 `[S#]` 引用的 Markdown、JSON 或安全 HTML；可选 Web、用户记忆、执行轨迹 |

命令层会捕获数据文件、JSON、输入参数和网络相关的可预期异常，向 stderr 输出 `Error: ...` 并返回退出码 2，不把 Python traceback 暴露给普通用户。启动时将 stdout/stderr 配置为 UTF-8，避免 10-K 中的项目符号或智能引号在 Windows GBK 控制台导致失败。

## 5. 数据生命周期与可追溯字段

### SEC 10-K

下载器先访问 `https://data.sec.gov/submissions/CIK##########.json`，再下载 `https://www.sec.gov/Archives/...` 的 primary document。每条 manifest 记录至少含 `document_id`、ticker、公司名、CIK、form、report/filing date、accession number、primary document、archive URL、本地文件名、下载时间和 `source_type=sec_10k`。重复运行时先读取旧 manifest；相同 `document_id` 不重复写入，不同历史记录不会被覆盖。损坏的 manifest 会拒绝写入并报明行号，防止悄悄丢失来源。

### A 股指数

腾讯财经 K 线接口单次返回有行数上限，因此下载器按自然年请求。每一个 CSV 只有 `date,close,volume` 三列；同名 `.meta.json` 还保存 SHA-256。运行时检查列、有限数字（拒绝 NaN/Inf）、日期严格递增、重复日期、正收盘价、非负成交量和 checksum。

### 索引与引用

HTML 解析会去掉脚本、样式、inline-XBRL header/hidden/resources/context/unit，再归一化空白和常见排版符号。包含两个或更多 schema/context 噪声标识的 chunk 不进入索引。每个可检索 chunk 保存 `chunk_id`、`document_id`、title、text、source URL、日期、类型和 locator。最终引用同时显示 accession 和 chunk ID，因此能从答案回到 SEC Archive，再回到本地索引片段。

## 6. Agent、模型和检索流程

1. CLI 接收问题、用户 ID、公司过滤和可选 Web/市场文件。
2. `PreferenceStore` 仅在“我关心”“focus”“I'm interested in”“关注/偏好/感兴趣”等显式表达出现时，写入六类可审计偏好；普通问题不写长期记忆。
3. DeepSeek V4 规划器只为模糊短问题提供受限扩词；明确财务问题使用确定性领域扩展，规划文本不能成为答案或证据。
4. `LocalRetriever` 用 BM25 检索。英文停用词、连字符组成词和金融短语 token 降低噪声；中文连续文本切为滑动 bigram。
5. 可选 DuckDuckGo 结果以 `web_search` 独立类型加入；市场快照以 `market_data` 独立类型加入。市场文件丢失或损坏会出现在 `warnings`，不会静默消失。
6. Doubao `doubao-seed-evolving` 在 non-thinking 模式下根据证据起草；DeepSeek V4 核验并改写。验证器不可用、标签非法、正文为空或生成数字不在 evidence 中时统一退回离线答案。
7. Markdown 输出显示答案、Sources、可选 Data warnings、可选 Agent trace；JSON 输出包含同等结构化字段；`--html` 输出独立静态报告，所有动态文本均转义，仅允许绝对 `http/https` 来源 URL 形成链接，并嵌入限制性 CSP meta 策略。

模型密钥只能来自环境变量或 `.env`：`DOUBAO_API_KEY`、`DEEPSEEK_API_KEY`。没有密钥或远程请求失败时，trace 明确记录 `offline` 和原因。运行 `python -m finagent verify-models` 可在面试前验证两家 provider；它只发送固定 `READY` prompt。代码不会打印密钥、Authorization header 或模型请求体。

## 7. 输出结构

`AgentResponse.to_dict()` 还包含 `execution_mode`、`fallback_reason` 和 `value_provenance`。每个 citation 除文档字段外保留 chunk ID、证据 SHA-256、受限摘录与检索分数。`warnings` 用于数据缺失、损坏或无法解析等非致命情况；无证据时答案明确拒绝推断。

## 8. 测试与已验证行为

测试命令：

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall -q src scripts tests
```

当前测试覆盖来源字段、BM25 与 Hit@5、黄金答案紧邻引用和答案全覆盖、数据快照、市场 checksum 与 NaN/Inf、记忆闭环、模型分阶段参数、空响应、验证器不可绕过、数字漂移、SEC recent/history 与不完整退出、Web、CLI 和安全 HTML。实际数量和覆盖率以 README 与本次 coverage 报告为准；真实模型 smoke 记录在 `DEMO_OUTPUTS.md`。

## 9. 已知限制与现场使用建议

- BM25 仍是词法检索。`top-line pressure` 与只出现 `revenue decline` 的段落可能不匹配；这是明确展示的限制，不应在 demo 中夸大为语义搜索。
- HTML 展平无法保证复杂表格列关系；需核验数字时应打开 SEC 原文，后续优先改为 XBRL fact 级别抽取。
- DuckDuckGo 结果仅是搜索片段，可能变化，不能替代原始 filing。
- `data/memory` 为单用户 demo 的本地明文 JSON，支持用户级修改和清除，但不具备认证、加密、跨进程锁和保留策略。
- `download-markets` 依赖公开网络且按年度串行下载；现场网络慢时可优先跑已下载的 CSI 300 或单独重试某一 symbol。
- 输出支持 Markdown、文本、JSON 和安全静态 HTML；PPT 没有实现，因为本次优先保证引用、离线运行和数据复现。HTML 不执行脚本，也不渲染任意用户 HTML。
