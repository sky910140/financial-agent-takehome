# 失败矩阵与明确降级行为

默认 `ask` 的可交付模式只有两种：`remote_verified` 表示规划、起草、核验三个远程阶段全部成功且引用和数字守卫通过；`offline_extractive` 表示输出本地检索原文并显示具体 `fallback_reason`。系统不会把部分远程成功包装成完整成功。

| 失败条件 | 检测点 | `ask` 行为 | 严格命令 / 退出码 |
| --- | --- | --- | --- |
| 缺少任一 API key、超时、HTTP 错误或空模型正文 | 每个模型阶段的 `used_remote_model` 与安全错误摘要 | `offline_extractive`；显示失败阶段；不采用远程草稿 | `smoke-demo` 退出 2 |
| 规划失败但起草/核验可用 | 三阶段全成功守卫 | `offline_extractive`；不把两阶段结果标记为完整链路 | `smoke-demo` 退出 2 |
| 核验器给出未知 `[S#]` 或无有效引用 | 引用标签白名单守卫 | 丢弃远程答案，返回带引用的本地摘录 | `smoke-demo` 退出 2 |
| 远程答案出现 evidence 中不存在的数字 | Decimal 归一化数字集合守卫 | 丢弃远程答案，返回本地摘录 | `smoke-demo` 退出 2 |
| SEC 索引缺失、为空、公司过滤无匹配或 BM25 无匹配 | 本地 evidence 集为空 | 明确回答 `No local evidence matched`，不无来源推断 | `offline-demo` / 评测命令退出 2 |
| 市场 CSV 缺失、字段错误、日期乱序、NaN/Inf、非法值或 checksum 不匹配 | 市场 schema、日期、有限数值和 SHA-256 校验 | 返回 data warning；纯市场问题不使用 filing 中偶然出现的 “index” 冒充市场证据 | `data-integrity`、`offline-demo` 退出 2 |
| 可选 Web 搜索无可用结果或网络失败 | `--web` 返回空证据集 | 增加 `Web search returned no usable results` warning，继续本地证据路径 | `ask` 仍可退出 0；warning 可见 |
| 数据文件与受检快照的行数、日期或 hash 不一致 | `data-integrity` 重算并对比 | 不影响普通 filing 问答，但完整性状态为 FAIL | `data-integrity`、`offline-demo` 退出 2 |
| 黄金答案缺句、借用后续引用、存在未登记文本、chunk 不存在或支持短语缺失 | 逐句引用评测 | 报告具体失败句、紧邻标签、未覆盖文本和缺失短语 | `eval-golden`、`offline-demo` 退出 2 |
| 记忆 user ID 非法或主题不在白名单 | 写入前输入校验 | 拒绝写入并返回友好错误；不修改已有文件 | CLI 退出 2 |
| 记忆 JSON 损坏 | 读取解析保护 | 按空记忆继续；后续显式写入会生成有效 JSON | 普通读取不崩溃 |

## 数值降级边界

- `disclosed`：直接来自受检 CSV 或 filing evidence 的值。
- `calculated`：仅由 Python 确定性公式产生，目前为 `(end_close / start_close - 1) * 100` 和成交量算术平均。
- `model_interpretation`：只有完整远程链路通过后才出现；模型不得自行做算术，所有数字仍必须通过 evidence 数字守卫。

复杂 SEC 表格目前没有 XBRL fact 级确定性计算，因此系统只引用披露值，不用模型计算同比、利润率或债务合计。这个限制优先于生成看似完整但不可复算的答案。

## 现场失败演练

无需破坏已提交数据即可演练模型降级：暂不配置 `.env`，运行普通 `ask --trace`，应看到三个阶段 `remote=False`、`execution_mode=offline_extractive` 和仍可追溯的来源。严格远程演示使用 `smoke-demo`；任一阶段失败时它返回 2，而可靠现场主路径始终是 `offline-demo`。
