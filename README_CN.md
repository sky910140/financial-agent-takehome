# Financial Agent Take-Home

中文 | [English](README.md)

这是一个以证据为中心的金融研究 Personal Agent。它面向公开金融文件和中国市场指数数据：先检索本地证据，再生成带来源的回答。每条引用保留 URL、日期、文档 ID、accession 和 chunk 定位信息，便于 reviewer 复核。

本项目是研究辅助工具，不提供投资建议，不执行交易。

## 已实现能力

- 通过 DuckDuckGo HTML 搜索公开网页；搜索结果在引用中明确标注为 `web_search`。
- 已提交沪深 300、上证综指和深证成指的 20 年以上日收盘价与成交量 CSV，以及每个文件的来源元数据。
- SEC 合规下载器可下载十家公司最近的 10-K：Apple、Microsoft、NVIDIA、Amazon、Alphabet、Tesla、JPMorgan、Berkshire Hathaway、Walmart、Exxon Mobil。
- 本地 BM25 检索。英文按词切分，中文连续文本采用滑动 bigram；支持 `--company` 先缩小 corpus。
- 每个 filing chunk 保存原文片段、source URL、filing date、source type、accession 和 chunk ID。
- 按 user ID 持久化的长期偏好记忆。仅在“我关心”“focus”“I'm interested in”“关注/感兴趣”等明确表达出现时写入。
- 两模型协同：DeepSeek V4 Pro 做检索规划和引用核验，`doubao-seed-evolving` 根据证据起草。没有第三个主推理模型。
- Markdown、JSON、市场表格、source list、数据 warning 和非敏感执行 trace。
- 没有模型密钥时，系统返回明确标识的离线提取答案，不会伪装成模型推理结果。

## 快速开始

要求 Python 3.11+；项目已使用 Python 3.14 验证。运行时没有第三方依赖。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e . --no-build-isolation
Copy-Item .env.example .env
```

已提交的市场数据支持离线市场 demo；SEC filing 问答首次运行前仍需下载并建立本地索引。

```powershell
$env:SEC_USER_AGENT = "FinancialAgent your-email@example.com"
python scripts/download_sec_10k.py --years 1 --output-dir sample_docs/sec_10k
python -m finagent index --docs-dir sample_docs/sec_10k --output data/index/filing_chunks.json
python -m finagent ask "Summarize liquidity and debt-related risks." --company Apple --trace
```

如需重新抓取三组市场数据：

```powershell
python -m finagent download-markets --output-dir data/market --start-year 2005
```

也可以单独下载或更新某一个指数：

```powershell
python -m finagent download-market --output data/market/sse_composite.csv --symbol sh000001 --start-year 2005
python -m finagent download-market --output data/market/szse_component.csv --symbol sz399001 --start-year 2005
```

## 模型配置

将以下变量填入项目根目录的 `.env`。该文件已被 Git 忽略，严禁提交 key。

```dotenv
DOUBAO_API_KEY=你的_Ark_API_Key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3/chat/completions
DOUBAO_MODEL=doubao-seed-evolving

DEEPSEEK_API_KEY=你的_DeepSeek_API_Key
DEEPSEEK_BASE_URL=https://api.deepseek.com/chat/completions
DEEPSEEK_MODEL=deepseek-v4-pro
```

其中 `deepseek-v4-pro` 是服务端接受的 DeepSeek V4 模型名。配置完成后先运行以下命令：

```powershell
python -m finagent verify-models
```

它只向两家 provider 发送固定的 `READY` 连通性请求，不发送 10-K、市场数据、用户问题或偏好。两行都显示 `Verified ...` 后，再运行完整 Agent demo。若任一家不可用，命令返回退出码 2。

每次远程完成请求均设置 600 token 输出预算。它用于保证三个串行阶段在 CLI 中保持可接受的响应时间，不会截断传给模型的检索证据。

完整远程运行时，`--trace` 应显示：

```text
planning: deepseek / deepseek-v4-pro / remote=True
analysis: doubao / doubao-seed-evolving / remote=True
verification: deepseek / deepseek-v4-pro / remote=True
```

若远程回答没有合法的 `[S#]` 标签，系统拒绝该回答并使用离线提取结果。引用标签校验是程序守卫，不等同于对每个财务 claim 的独立审计。

## 数据与溯源

| 数据集 | 加载方式 | 本地文件 | 可追溯字段 |
| --- | --- | --- | --- |
| 沪深 300、上证综指、深证成指 | 腾讯财经 K 线接口，按自然年请求 | `data/market/*.csv` 与 `.meta.json` | endpoint、全部 request URL、下载时间、行数、覆盖区间、字段定义 |
| SEC 10-K | SEC submissions API 加 SEC Archives | `sample_docs/sec_10k/*.html`、`manifest.jsonl` | ticker、CIK、form、report/filing date、accession、archive URL、下载时间 |
| Filing chunks | 本地 HTML 转文本、XBRL 噪声过滤、chunker | `data/index/filing_chunks.json` | chunk/document ID、text、URL、日期、source type、accession locator |
| 公共网页 | DuckDuckGo，仅在 `--web` 时启用 | 当前请求内存中 | result URL、title、snippet、`web_search` 类型 |

市场 CSV 和 metadata 已随仓库提交，详见 [data/market/README.md](data/market/README.md)。SEC 原始 HTML、filing index 和用户偏好不提交，因为可能较大、过期或具有个人属性；README 的命令可重建它们。

## 可复现 Demo

```powershell
# 20 年市场快照
python -m finagent market --file data/market/csi300.csv --start 2006-07-10 --end 2026-07-10
python -m finagent market --file data/market/sse_composite.csv --start 2006-07-10 --end 2026-07-10
python -m finagent market --file data/market/szse_component.csv --start 2006-07-10 --end 2026-07-10

# Filing 问答
python -m finagent ask "What are this company's main risk factors?" --company Tesla --trace
python -m finagent ask "How did revenue or profitability change compared with the prior year?" --company Microsoft
python -m finagent ask "What does the company say about competition?" --company Amazon
python -m finagent ask "Summarize liquidity or debt-related risks." --company Apple

# 用户长期偏好
python -m finagent ask "I care most about liquidity risk and debt maturity." --company JPM --user alice
python -m finagent ask "What should I focus on?" --company JPM --user alice --json --trace

# 显式标记为 web_search 的网页检索
python -m finagent ask "Apple 10-K SEC filing" --company no-such-company --web --trace
```

真实运行记录、市场快照、Web、JSON、偏好记忆、多模型守卫和 BM25 失败案例见 [DEMO_OUTPUTS.md](DEMO_OUTPUTS.md)。

## 命令入口

| 命令 | 用途 |
| --- | --- |
| `download-sec` | 下载十家公司 10-K，写 manifest 和下载报告 |
| `download-market` | 下载单个指数历史数据 |
| `download-markets` | 下载/更新三组主要 A 股指数 |
| `verify-models` | 不发送金融数据地验证两家模型的真实连通性 |
| `index` | 将 SEC manifest 对应文件构建为本地 chunks |
| `market` | 输出指定日期区间的价格、涨跌幅、平均成交量表格 |
| `ask` | 发起带引用的 filing、市场或 Web 问答 |

为机器集成添加 `--json`；为演示模型阶段添加 `--trace`；为 Web 检索添加 `--web`。

## 测试

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall -q src scripts tests
```

当前 26 项测试覆盖 chunk 来源、BM25 与中文 bigram、市场数据校验、三指数、偏好记忆、SEC manifest、XBRL 过滤、Agent 引用守卫、Web URL、CLI 错误、UTF-8 输出、模型连通性成功/失败，以及配置 `.env` 时的测试隔离。

## 设计边界与取舍

- BM25 被保留是为了可复现、可检查、无托管服务依赖和离线可用；它对 `top-line pressure` 与 `revenue decline` 等词法不匹配会失败，项目明确展示而非隐藏该限制。
- 当前 verifier 校验引用标签与允许来源，不证明每个 claim 的语义蕴含。下一优先级是 XBRL fact 级别的数值抽取和 claim-evidence audit。
- Web snippet 是发现工具，不是一级财务证据；其类型始终保留为 `web_search`。
- 偏好 memory 是单用户 demo 的本地 JSON，没有认证、加密、删除 API、短期会话上下文或并发控制。
- 市场自然语言问答默认使用本地文件覆盖区间；精确日期区间使用 `market --start --end`。
- 不实现多轮 chat UI、HTML/PPT、向量数据库或全市场个股数据，是为了优先保证引用、可解释性、离线降级和现场可运行性。

进一步的系统设计、文件说明、审查整改与未来优先级见：[DESIGN.md](DESIGN.md)、[PROJECT_FILES_CN.md](PROJECT_FILES_CN.md)、[REMEDIATION_CN.md](REMEDIATION_CN.md)。
