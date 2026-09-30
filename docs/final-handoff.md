# 当前交付状态

截至 2026-09-30，Evidence 已提供本地 WebUI、CLI/API、SDK 研究流程、证据与指标核验，以及按用户请求选择的 HTML / Excel / PPT / Word 导出。阅读顺序：[README](../README.md) → [WebUI 图文指南](webui.md) → [设计说明](design.md)。

## 已交付能力

| 部分       | 当前实现                                                                     |
| ---------- | ---------------------------------------------------------------------------- |
| 本地工作台 | 首页提问、历史会话、执行进展、核验正文、追问、报告图表、来源与下载           |
| Agent      | LangChain / LangGraph；主管、研究与独立核验职责；受限 tools 与方法 skills    |
| 可复核计算 | 事件窗口、行情异动、资产比较、下一开盘执行回测、敏感性、显式指标单位与格式化 |
| 运行控制   | 持久预算、检查点、串行队列、有界补查与修复、缺口保留                         |
| 按需导出   | 报告默认 HTML、文档默认 Word、明确格式优先；不固定生成四种文件               |
| 独立报告   | HTML 连续章节、交互图表和来源附录；无工作台 tab 或产物信息                   |
| PPT        | operating-review 源 skill 提取、可编辑表格/图表、列对齐与长文字分页修复      |
| 工程交付   | 锁文件、一键脚本、CI、样例、开发记录、白名单 ZIP、逐文件 SHA-256 和凭据检查  |

当前计算方法 `2026.09.4`、正文核验协议 `1.5`。原题样例：NVDA 仅 HTML，黄金/比特币仅 Excel/PPT/Word。两套样例均由 DeepSeek-V4.1-Flash 真实运行产出；NVDA 样例为 2026-09-30 运行 `e8a8611a`，每个 K 线变化点都有可追溯的归因状态，见 [归因覆盖说明](attribution-20260930.md)。

## 最近验证与已知边界

| 范围                 | 最近证据                                                                                            |
| -------------------- | --------------------------------------------------------------------------------------------------- |
| 后端                 | 340 项（2026-09-30，归因覆盖）；[308 项回归及 PPT 检查](../evals/ppt-layout-fix-20260929.json)      |
| 前端、构建与静态检查 | 32 项（2026-09-30）；[31 项前端及导出工程检查](../evals/export-engineering-20260929.json)           |
| 格式解析             | [13 个真实 planner 案例](../evals/output-selection-20260929.json)                                   |
| 样例及产物一致性     | [sample-validation](../evals/sample-validation.json)                                                |
| 真实研究             | [历史八次运行](final-evaluation.md)、[P0 两次及内容复核](../evals/p0-live-validation-20260929.json) |
| 本次文档整理         | [截图、链接与文档验证记录](../evals/docs-refresh-20260929.json)                                     |

PPT 检查采用 LibreOffice 渲染与 Poppler 字框检查。服务面向本地单用户，免费数据源会限流或缺页，GLD 为黄金代理，日线按请求刷新而非逐笔实时。

## 如何检查交付版本

正式 ZIP 由 `tools/package_delivery.py` 生成，包含 `DELIVERY-INFO.json` 的 Git 提交、工作区状态和交付树哈希，以及 `DELIVERY-MANIFEST.json` 的逐文件 SHA-256。使用 `--verify` 可核对包内完整性及与当前源码的一致性，命令见 [工程指南](development.md#打包与发布)。

版本顺序：`a713520` 指标/交付 P0 → `0c3c36d` 按需导出与报告 → `39ea1be` planner 格式规则 → `e76b82e` PPT 排版修复。本轮文档提交在这些功能提交之后，仅补充说明、架构图、截图与文档验证记录；具体文档提交以 Git 和包内记录为准。

[AI 开发过程](ai-development.md) · [Prompt / 技能源码](../prompts/) · [验证命令](validation.md) · [数据源扩展](data-providers.md) · [文档总览](README.md)
