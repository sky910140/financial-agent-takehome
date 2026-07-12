# Evidence-First Financial Agent

[![CI](https://github.com/sky910140/financial-agent-takehome/actions/workflows/ci.yml/badge.svg)](https://github.com/sky910140/financial-agent-takehome/actions/workflows/ci.yml)

中文 | [English](README_EN.md)

一个可本地运行、可追溯、可验证的个人金融研究 Agent。系统先从 SEC 10-K、A 股指数和公开网页中获取带来源的证据，再由 `doubao-seed-evolving` 起草、DeepSeek V4 规划和核验；引用或数字校验失败时，明确降级为离线提取式回答。

本项目不提供投资建议，不执行交易，也不会把模型训练知识伪装成当前数据来源。

## 可验证结果

| 项目 | 当前结果 |
| --- | --- |
| SEC 数据 | 10 家公司各 5 年 10-K，50 份 filing、19,975 个可检索片段 |
| A 股市场数据 | 沪深 300、上证综指、深证成指，20 年以上日收盘价和成交量 |
| 检索评测 | 5 个黄金问题，Hit@5 = 5/5 |
| 黄金答案核验 | 10 组问答、13 个句子，逐句引用与证据短语核验 13/13 |
| 自动化测试 | 64/64 通过，总覆盖率 90% |
| Python 兼容性 | 3.11、3.13、3.14 实测通过 |
| 多模型链路 | DeepSeek 规划 → Doubao 起草 → DeepSeek 核验 |
| 严格远程链路 | Doubao + DeepSeek 三阶段 smoke 实测进入 `remote_verified` |
| 输出格式 | Markdown、JSON、安全的独立 HTML 报告 |
| 失败处理 | 模型、网络、引用或数字守卫失败时明确降级，不伪装成功 |

## 系统架构

```mermaid
flowchart TB
    U["用户问题 + 公司 + 用户 ID"] --> M["显式偏好记忆"]
    M --> P["DeepSeek V4<br/>受限检索规划"]

    subgraph DATA["带来源的数据与证据"]
        S["SEC 10-K 本地索引"]
        K["A 股指数 CSV + SHA-256"]
        W["可选 Web Search 摘要"]
    end

    P --> R["BM25 检索 / 市场确定性计算"]
    S --> R
    K --> R
    W --> R
    R --> E["编号证据集 [S1]...[S#]<br/>URL + 日期 + accession + chunk ID"]
    E --> A["Doubao<br/>仅基于证据起草"]
    A --> V["DeepSeek V4<br/>使用相同证据核验"]
    V --> G{"程序守卫<br/>远程阶段 + 引用标签 + 数字证据"}
    G -->|"通过"| O["Markdown / JSON / HTML<br/>答案 + 实际来源 + trace"]
    G -->|"失败"| F["离线提取式降级<br/>显示具体失败原因"]
```

关键设计不是“多调用一个模型”，而是职责分离和确定性信任边界：模型只能生成候选答案，程序决定候选答案能否交付。完整取舍见 [DESIGN.md](DESIGN.md)。

## 五分钟评审路径

要求 Python 3.11+。运行时没有强制第三方依赖，仓库已提交市场数据和 SEC 检索索引，因此首次克隆后无需下载外部数据即可演示。

Windows PowerShell：

```powershell
git clone https://github.com/sky910140/financial-agent-takehome.git
cd financial-agent-takehome
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

macOS / Linux：

```bash
git clone https://github.com/sky910140/financial-agent-takehome.git
cd financial-agent-takehome
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

安装后只需一条命令完成可靠的现场主路径；该命令显式传入空模型凭据，不读取远程模型配置，不发网络请求，也不修改仓库内记忆：

```powershell
python -m finagent offline-demo
```

预期输出：

```text
Data integrity: PASS (50 filings, 19975 chunks, 3 market datasets)
Market deterministic calculation: 1412.12 -> 4780.79 = 238.55%
Retrieval Hit@5: 5/5
Golden sentence citations: 13/13
Offline cited Q&A: PASS (4 cited chunks)
Memory lifecycle: PASS (write/read/influence/modify/clear)
OFFLINE DEMO: PASS
```

剩余时间按以下顺序抽查：

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

`ask` 输出会明确标记 `execution_mode=offline_extractive` 和具体降级原因，并保留 SEC URL、filing date、document ID、accession、chunk ID、证据 SHA-256 与检索分数。

现场运行清单：确认 Python 3.11+；不依赖公网先运行 `offline-demo`；核对退出码 0 和最后一行 `PASS`；抽查任一 `[S#]` 的 SEC URL、accession、chunk 与 hash；确认市场值标记为披露值或确定性计算值；演示记忆影响后执行 `memory clear`；只有现场明确要求远程链路时才配置 `.env` 并执行 `smoke-demo`。失败演练和退出行为见 [失败矩阵](docs/FAILURE_MATRIX.md)。

## 配置两个指定模型

复制配置模板：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中填写以下变量。`.env` 已被 Git 忽略，严禁提交真实密钥。

```dotenv
DOUBAO_API_KEY=你的_Ark_API_Key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3/chat/completions
DOUBAO_MODEL=doubao-seed-evolving

DEEPSEEK_API_KEY=你的_DeepSeek_API_Key
DEEPSEEK_BASE_URL=https://api.deepseek.com/chat/completions
DEEPSEEK_MODEL=deepseek-v4-pro
```

先检查模型连通性，再运行严格的完整链路：

```powershell
python -m finagent verify-models
python -m finagent smoke-demo
```

`verify-models` 只发送固定的 `READY` 请求，不发送金融文件。`smoke-demo` 只有在规划、起草、核验三个远程阶段都成功，并且最终引用与数字守卫通过时才返回退出码 0。

成功的执行轨迹应包含：

```text
planning: deepseek / deepseek-v4-pro / remote=True / ok
analysis: doubao / doubao-seed-evolving / remote=True / ok
verification: deepseek / deepseek-v4-pro / remote=True / ok
```

## 代表性 Demo

```powershell
# 公司主要风险
python -m finagent ask "What are this company's main risk factors?" --company Tesla --trace

# 收入与盈利能力同比变化
python -m finagent ask "How did revenue or profitability change compared with the prior year?" --company Microsoft --trace

# 竞争情况
python -m finagent ask "What does the company say about competition?" --company Amazon --trace

# 长期偏好记忆
python -m finagent ask "I care most about liquidity risk and debt maturity." --company JPM --user alice
python -m finagent ask "What should I focus on?" --company JPM --user alice --json --trace

# 可选公开网页搜索；搜索摘要始终标记为 web_search
python -m finagent ask "Apple 10-K SEC filing" --company Apple --web --trace
```

真实运行记录和预期输出见 [DEMO_OUTPUTS.md](DEMO_OUTPUTS.md)。

## 输出格式

默认输出 Markdown；`--json` 用于机器集成；`--html` 生成可直接在浏览器打开的独立报告；`--trace` 展示非敏感执行状态。

```powershell
python -m finagent ask `
  "Summarize liquidity and debt-related risks." `
  --company Apple `
  --html `
  --trace |
  Set-Content -Encoding utf8 apple-liquidity-report.html

Start-Process .\apple-liquidity-report.html
```

HTML 对所有动态文本转义，只允许绝对 HTTP(S) 来源形成链接，并包含限制性 Content Security Policy。`--json` 与 `--html` 互斥。

## 数据与溯源

| 数据集 | 本地交付物 | 保留的来源信息 |
| --- | --- | --- |
| SEC 10-K | `data/index/filing_chunks.json` | 公司、CIK、filing/report date、accession、SEC URL、document/chunk ID |
| 沪深 300、上证综指、深证成指 | `data/market/*.csv`、`.meta.json` | 数据端点、全部年度请求 URL、下载时间、覆盖范围、SHA-256 |
| 公开网页 | 当前请求内存中的 `web_search` 证据 | 标题、结果 URL、搜索摘要；不会自动升级为 SEC 原文证据 |
| 用户偏好 | 本地 `data/memory/preferences.json` | 仅保存用户明确表达的白名单主题；文件不提交 Git |

`data/DATA_SNAPSHOT.json` 是 2026-07-12 的受检快照，列出十家公司各五年 10-K 的 ticker、公司、CIK、报告期、提交日、accession、SEC URL 和 chunk 数，以及三组市场数据的来源、下载时间、覆盖日期、记录数和 SHA-256。市场 CSV 的收盘价与成交量属于来源披露值；区间涨跌幅和平均成交量由 Python 公式确定性计算；模型只能解释已有值，不得自行做算术。`python -m finagent data-integrity` 会重新计算并逐项核对快照。

SEC 原始 HTML 不提交，避免仓库膨胀；下载脚本和重建命令完整保留：

```powershell
$env:SEC_USER_AGENT = "FinancialAgent your-email@example.com"
python scripts/download_sec_10k.py --years 5 --output-dir sample_docs/sec_10k
python -m finagent index --docs-dir sample_docs/sec_10k --output data/index/filing_chunks.json
python -m finagent download-markets --output-dir data/market --start-year 2005
```

## 测试与评测

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

测试覆盖 SEC recent/history 下载、不完整下载退出码、XBRL 噪声过滤、BM25 和金融短语、市场日期、checksum 与 NaN/Inf、长期记忆、模型分阶段预算、空正文、核验器不可绕过、数字漂移、逐句引用紧邻绑定与答案全覆盖、Web 分类、CLI 错误和安全 HTML。

GitHub Actions 在 Ubuntu Python 3.11/3.13 和 Windows Python 3.11 上运行编译、覆盖率、检索评测、黄金答案核验、数据完整性和离线 demo，不需要模型密钥或外部网络。

## 项目结构

```text
src/finagent/                 Agent、检索、模型、数据、记忆和输出实现
src/finagent/integrity.py     SEC/市场数据快照与完整性门禁
scripts/                      SEC 与市场数据下载入口
tests/                        64 项单元、集成与提交前回归测试
evals/                        检索与黄金答案评测集
data/index/                   已提交的 SEC 检索索引
data/market/                  三组指数 CSV 与来源元数据
data/DATA_SNAPSHOT.json       受检数据记录、口径与 SHA-256
docs/                         黄金核验、失败矩阵和文件级实现说明
DESIGN.md                     1-2 页系统设计与取舍
DEMO_OUTPUTS.md               可复现命令和真实输出
```

## 已知边界

- BM25 是可解释的词法检索，不等同于开放域语义检索；当前 5/5 只代表五个黄金问题。
- HTML 展平不能保证复杂财务表格的列关系；数值结论应回到 SEC 原文核验，后续优先补 XBRL fact 层。
- Web Search 依赖可变公网结果，搜索摘要不是一级财务证据。
- 数字守卫能拒绝 evidence 中不存在的数字，但不能证明所有非数值陈述都满足语义蕴含。
- 本地偏好记忆支持用户级读取、白名单修改和清除，并使用原子文件替换；它仍没有认证、加密、跨进程锁和保留策略，不应直接作为生产存储。
- 当前提供 CLI 和静态 HTML 报告，没有实现多轮聊天 UI；这是为了优先保证可复现、引用和失败降级。

更多信息：

- [系统设计说明](DESIGN.md)
- [可复现 Demo 输出](DEMO_OUTPUTS.md)
- [项目文件与实现映射](docs/PROJECT_STRUCTURE_CN.md)
- [市场数据说明](data/market/README.md)
- [黄金问答与逐句引用核验](docs/GOLDEN_QA.md)
- [失败矩阵与降级行为](docs/FAILURE_MATRIX.md)
- [数据快照](data/DATA_SNAPSHOT.json)
