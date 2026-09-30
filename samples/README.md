# 产物样例（面试题两道原始问题）

本目录保存两道题目**真实运行**生成的交付物。打开它们不需要模型或密钥。GitHub 不会运行 HTML，请下载后用浏览器打开；Office 文件请用 Excel、PowerPoint 或 Word 打开。

## 题目一：NVDA 行情与 AI 事件 → 交互 HTML

> 回顾英伟达（NVDA）近五年行情数据（开盘价、收盘价、最高价、最低价、成交量），梳理同期 AI 行业大事件（如 ChatGPT 发布、B100 芯片发布、DeepSeek 等），在 K 线图上标记行情变化（如：拐点、加速、下跌、上涨等变化）触发时刻的主要事件、影响评级，产物可交互、可溯源，最终生成一个 HTML。

| 交付物                | 仓库位置                                                                            |
| --------------------- | ----------------------------------------------------------------------------------- |
| **交互 HTML 报告**    | [`samples/nvda/artifacts/report.html`](nvda/artifacts/report.html)                  |
| 报告数据（同源 JSON） | [`samples/nvda/artifacts/research-data.json`](nvda/artifacts/research-data.json)    |
| 文件哈希清单          | [`samples/nvda/artifacts/manifest.json`](nvda/artifacts/manifest.json)              |
| 研究快照 / 运行来源   | [`bundle.json`](nvda/bundle.json) · [`provenance.json`](nvda/provenance.json)       |
| 执行轨迹 / 审核记录   | [`trace.json`](nvda/trace.json) · [`review-history.json`](nvda/review-history.json) |

- 运行 `e8a8611a8d1a42d3`，方法版本 `2026.09.4`，研究状态 `partial`。
- 共 10 个事件、16 个来源、17 个变化点。其中 7 个关联到事件，10 个已检索但未发现，未检索 0 个。
- 唯一缺口是 B100：官方发布的是 B200/GB200，系统没有用它们顶替 B100。

HTML 是单文件，带严格 CSP，不加载任何外部资源，也不含密钥。点击 K 线标记或归因表中的事件，可以打开原始证据和来源链接。

## 题目二：黄金 vs 比特币 → Excel / PPT / Word

> 请构建黄金与比特币作为避险/抗通胀资产的可交互比较分析体系，产物包括 Excel 回测底稿、PPT 决策框架、Word 策略报告。

| 交付物              | 仓库位置                                                                                                                    |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **Excel 回测底稿**  | [`samples/gold-bitcoin/artifacts/report.xlsx`](gold-bitcoin/artifacts/report.xlsx)                                          |
| **PPT 决策框架**    | [`samples/gold-bitcoin/artifacts/report.pptx`](gold-bitcoin/artifacts/report.pptx)                                          |
| **Word 策略报告**   | [`samples/gold-bitcoin/artifacts/report.docx`](gold-bitcoin/artifacts/report.docx)                                          |
| 图表（PNG / SVG）   | [`samples/gold-bitcoin/artifacts/charts/`](gold-bitcoin/artifacts/charts/)                                                  |
| 报告数据 / 哈希清单 | [`research-data.json`](gold-bitcoin/artifacts/research-data.json) · [`manifest.json`](gold-bitcoin/artifacts/manifest.json) |
| 研究快照 / 运行来源 | [`bundle.json`](gold-bitcoin/bundle.json) · [`provenance.json`](gold-bitcoin/provenance.json)                               |
| 执行轨迹 / 审核记录 | [`trace.json`](gold-bitcoin/trace.json) · [`review-history.json`](gold-bitcoin/review-history.json)                         |

- 运行 `3302715305fc4dac`，方法版本 `2026.09.3`，运行状态 `complete`。
- 共 10 个事件、15 个来源。黄金用 GLD ETF 作为代理。
- Excel 里的指标用公式计算，可以改参数后重算。PPT 中的图表是原生可编辑图表。

## 怎么复核

```bash
uv run python tools/verify_samples.py   # 校验快照与 HTML 一致性、manifest 哈希、Excel 公式缓存值、OOXML 结构
```

这项校验不包括浏览器或 Office 的视觉验收。

每套样例都是某次真实运行原样导出的结果（`provenance.json` 里 `manual_event_edits: false`），没有人工改动事件。
