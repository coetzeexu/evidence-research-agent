# Evidence · 可溯源投研 Agent

Python / LangChain / LangGraph / React / ECharts。本地研究工作台：根据自然语言调查行情与资讯，计算事件窗口和资产配置，发布经过证据与数值核验的中文正文；保留独立 HTML、Excel、PowerPoint、Word 导出能力。

本轮方法版本 `2026.09.4`，重点是调研文字可信度。**8 次固定版本真实评估已结束：3 次自动通过、5 次 partial，严格内容验收未通过；按用户要求交付当前版本并暂停目标。** 已实现的门禁仍会漏检夸大推断，也会误拦截正确比较，不能把自动 complete 当作内容可靠性的保证。当前入口见 [交付说明](docs/final-handoff.md)、[评估结果](docs/final-evaluation.md) 和 [方案与验收](docs/agent-research-quality.md)。旧报告样例不代表经过新版全文核验。

## 本地一键运行

需要 Node.js 22+、uv，Python 3.12 由 uv 安装。首次运行联网安装依赖：

```bash
./run.sh
# Windows: ./run.ps1
```

服务启动于 http://127.0.0.1:8000，不自动打开浏览器。启动脚本按依赖锁与源码指纹安装依赖、构建前端。旧样例离线可读；新研究需要在服务端 `.env` 配置支持工具调用的 OpenAI Chat Completions 兼容模型：

```dotenv
LLM_MODEL=你的模型或部署别名
LLM_BASE_URL=https://你的服务/v1
LLM_API_KEY=你的密钥
```

变量说明见 `.env.example`。可选 `LLM_PLATFORM` 请求头、`LLM_VLLM_THINKING` 适配部署网关。修改配置后重启服务。密钥不进入浏览器、Bundle 或交付包。Docker 可使用 `docker compose up --build`；该部署路径本机未实测。

## 只运行和查看文字

```bash
uv sync --frozen
uv run research run '回顾 NVDA 近五年，核实 ChatGPT、Blackwell 和 DeepSeek-R1 发布，解释行情变化和证据边界' --no-export
uv run research show RUN_ID --format text
uv run research show RUN_ID --format json
```

`--no-export` 持久化到任务，恢复时仍不生成文件。`show` 只读取研究快照，不调用模型。API 同样支持：

```bash
curl -X POST http://127.0.0.1:8000/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"比较 GLD 与 BTC-USD 近五年避险、抗通胀和配置价值","export_reports":false}'
curl http://127.0.0.1:8000/api/runs/RUN_ID/research
```

研究记录含 `research.status`、问题清单、证据原文片段、指标、结论、逐轮核验和预算。完成状态为 `complete / partial / failed`；旧 Bundle 缺少此记录时为 `unassessed`。关闭导出的任务状态为 `researched`，与研究是否完整分开。

网页会话显示真实工具动作、来源进展及核验正文。研究和追问的草稿均留在后端，核验后一次发布；聊天保留 `accepted / delta / done / error` 协议。追问使用当前快照与同一研究最近 12 条消息，换资产、更新日期或新增数据需重新研究。

## Agent 如何工作

```text
主管拆解问题 → 行情/宏观采集 → 研究子 Agent 调查
  → 确定性计算 → 结论草稿 → 独立正文核验 → 发布
                        ↑          │
                        └─补查/重算/改写─┘
```

- **主管**：解析资产、区间、点名事件与研究问题；额外问题绑定用户原话，不能自行扩写验收条件。
- **研究子 Agent**：调用来源目录、检索、原文读取、问题记录工具；搜索对应具体未解决问题，补查保留已有证据。
- **核验子 Agent**：分别用独立上下文检查原文/数值及推断边界，两项都通过才发布。工具计算高低、正负、居中等关系，模型口头通过不能覆盖程序失败。
- **技能**：约定事件研究、资产比较、证据检查的步骤和停止条件。价格、窗口、回测与敏感性由 Python 计算，模型不能补造数值。

完整运行上限 15 分钟实际执行时间，排队不计；前 12 分钟调查，最后 3 分钟预留综合核验。最多 34 次搜索、50 次原文读取、64 次模型调用，两轮检索补查和两轮正文修复。恢复继承已消耗预算，追问单独限制 180 秒。到期仅保留已核验内容与明确缺口，无可发布正文则失败。

## 数据与计算口径

- 行情：Yahoo 完整日线 OHLCV、复权收盘与公司行动；资讯：公开网页、HN、Yahoo 等；通胀：FRED CPI。保存来源、实际覆盖时间与快照哈希，不能把搜索摘要充当已读原文。
- 事件区分发生、首次公开、报道、市场反应时间。精确时刻按交易日历对齐；日期精度检查当日与下一交易日。回顾报道不能冒充历史公开时刻。
- 反应强度默认按 5 日相对基准收益除以事前波动计算，高/中/低与方向、证据可信度分开。相对收益只是标的减基准，不能解释为独立因果贡献。
- 比较使用共同股票月末锚点，不使用在锚点之后才形成的加密资产收盘。组合与单资产均使用同一初始资本、区间、费用及下一可交易日开盘执行引擎；包含现金、持仓、费用台账。
- GLD 是黄金 ETF 代理，不等于现货黄金。基金费用已体现在价格，不再重复扣减；交易成本另计。
- 避险区分正收益与相对抗跌；压力样本是事后 SPY 最差六个月。实际购买力、资产月收益与 CPI 同比的关联分开讨论；当前历史版 CPI 仅支持回顾分析。
- 成本、频率、权重和分段敏感性进入正文上下文。历史分段不是样本外验证，不能从网格选择事后最优配置。

## 验证与样例

本轮禁止报告导出、图片加载与浏览器验证。纯文字回归命令：

```bash
uv run pytest -q -k 'not workbook_real and not docx_and_native and not offline_html_embeds'
uv run ruff check backend tests tools
npm ci
npm test
npx tsc -b
npm run format:check
# 真实服务评估，会消耗模型与检索额度；不导出报告
uv run python tools/evaluate_text_research.py --case all --suite Final01
```

最终评估固定日期、问题与配置：NVDA / GLD-BTC 各连续三次、AMD / GLD-ETH 各一次，8 次均已完成。每轮保存正文、JSON、失败记录、代码版本、实际模型、用量和耗时；全部在执行预算内且未导出报告。自动检查通过 3 次，独立内容复核后仍有待修订项，整体未通过原定验收。逐次结果和文字样例见 [固定版本评估](docs/final-evaluation.md)，机器记录见 [final-summary.json](evals/text-research/final-summary.json)。开发试验与历史失败均保留；基线文字在 `evals/text-baseline/`。

本轮工程验证为后端 142 项、前端 28 项通过，TypeScript / Prettier / Ruff 通过。3 项真实报告导出测试按范围约束未执行；[工程记录](evals/engineering-verification.json) 与 [API/CLI 实测](evals/text-api-cli-verification.json) 不替代内容验收。

`samples/nvda/` 和 `samples/gold-bitcoin/` 是历史报告快照，包含 Bundle、执行轨迹及四种产物，本轮未重新生成。已有导出能力仍可使用 `research export RUN_ID` 或 `research replay nvda`，默认创建任务也保留导出兼容性。离线 HTML 内嵌脚本、样式与数据；Excel 的公式近似模型与下一开盘执行回测有差异，已分开标记。报告功能与视觉历史验证见 [验证记录](docs/validation.md)。

## 工程结构与边界

| 模块 | 职责 |
| --- | --- |
| `backend/research_app/agents.py` | SDK 主管、研究/核验上下文与工具 |
| `pipeline.py`、`budget.py` | LangGraph、持久化预算与有界修复 |
| `research_contract.py`、`research_text.py` | 问题/证据/结论契约、正文发布门禁 |
| `research_metrics.py`、`research_logic.py` | 数值引用、格式化及关系求值 |
| `research_semantics.py`、`tool_protocol.py` | 推断审查门禁、严格结构化输出适配 |
| `analytics.py`、`sensitivity.py` | 交易时序、同口径回测与敏感性 |
| `providers.py`、`security.py` | 行情/资讯/宏观采集与网络边界 |
| `api.py`、`storage.py` | FastAPI、队列、SSE、原子快照、SQLite |
| `apps/web/`、`packages/charts/` | React 会话及共享图表 |
| `prompts/`、`skills/`、`resources/` | 可版本化提示、方法和来源目录 |
| `tests/`、`tools/`、`evals/` | 自动化回归、独立评估与真实记录 |

单用户本地服务，串行任务队列，无多租户认证。免费数据源可能限流或缺页；不可用不能自动标记为核验通过。网页读取逐跳校验域名/IP、拒绝私网与元数据地址；前端同源调用后端，离线文件不依赖 CDN，HTML 使用 CSP，Excel 禁止资讯字符串转公式。提示注入内容仅作为不可信证据，工具白名单不提供任意代码执行。

[设计说明](docs/design.md) · [方案与验收](docs/agent-research-quality.md) · [AI 开发记录](docs/ai-development.md) · [评分框架](docs/rubric.md) · [历史界面规范](docs/youmind-reference.md)
