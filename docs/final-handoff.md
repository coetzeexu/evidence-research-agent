# 本轮交付：Agent 文字调研可信度

当前版本 `2026.09.4`，代码与记录已交付。按用户明确选择暂停目标，**未通过原定整体内容验收，未标记目标完成**。本轮没有导出报告、加载图片或打开浏览器。

## 已交付内容

- 主管、研究与核验职责仍基于 LangChain / LangGraph；增加问题驱动调查、定向补查和持久化执行预算。
- `ResearchBundle.research` 保存问题、原文片段与哈希、指标口径、结论及逐轮核验。旧 Bundle 标记为未评估。
- 同一执行引擎计算组合和单资产基线；正文上下文包含压力期、实际购买力、通胀关联与敏感性。事件区分信息公开、报道与市场反应时间。
- 首次研究和追问共用正文发布门禁：指标引用、确定性求值、独立语义核验、最多两轮正文修复；草稿不进入用户会话。
- 可持久化 `export_reports`，`GET /api/runs/{id}/research`、CLI 文字查看和无文件研究状态。完整研究最多 15 分钟，恢复不重置预算。
- 更新 README、架构说明、研究技能、Prompt、回归用例与 AI 开发记录。源码、锁文件和运行脚本位于本项目目录；本轮以该目录交付，历史报告和旧归档不代表新版验证结果。

以上是已实现的机制；真实研究仍会漏检或误判，具体限制如下。

## 验证结果与样例

| 项目 | 结果 |
| --- | --- |
| 后端功能回归 | 142 项通过；3 项实际报告导出测试按范围未执行 |
| 前端功能回归 | 28 项通过 |
| 静态检查 | TypeScript、Prettier、Ruff 通过 |
| API / CLI | 对实际 partial 快照读取成功，正文一致且无导出文件 |
| 固定版本真实研究 | NVDA、GLD/BTC 各 3 次，AMD、GLD/ETH 各 1 次，8 次全部结束 |
| 自动检查 | 3 次通过、5 次 partial；全部在时间及调用预算内 |
| 独立内容复核 | 8 份均有待修订项，严重程度不同；整体内容验收未通过 |
| 真实故障夹具 | 仅两条正确对照获准发布；不替代完整研究验收 |

[逐次评估与全部文字样例](final-evaluation.md) · [机器汇总](../evals/text-research/final-summary.json) · [模型 / Prompt / 技能版本](../evals/text-research/final-versions.json) · [工程验证](../evals/engineering-verification.json) · [API / CLI 验证](../evals/text-api-cli-verification.json)

原始 `.txt`、`.research.json`、`.bundle.json` 和 `.result.json` 在 `evals/text-research/FinalNVDA`、`FinalGoldBTC`、`FinalAMD`、`FinalGoldETH`。每次独立复核保存为 `<运行 ID>.content-audit.json`。这些是未经人工改写的实际结果，包含失败样例；自动 complete 不代表独立内容验收通过。原始结果里的 `independent_content_audit: pending` 是生成时状态，审阅结论在独立文件及汇总中，保留原始文件不覆盖。

## 尚未解决的问题

1. **语义漏检。** 部分文字仍以有限 CPI 相关性否定机制，或在没有预期证据时声称市场提前定价。增加核验上下文后仍未可靠消除。
2. **数值关系误拦截。** 数值本身可重算，但模型改写引文或绑定错误，使正确正负关系被拒绝，导致必答段落缺失。不能通过删除检查或手改结果获得通过。
3. **完成度误判。** 有运行明确缺少用户要求的论文日期，却标记 complete。问题账本和模型覆盖判断仍不足以保证真实完整性。

AMD 复核目前是措辞与方法说明警告，其他运行含严重推断或必答缺失；不能把所有失败等同于同一种错误。逐条引文、原因与严重程度以审阅 JSON 为准。生产起草与核验使用同一配置模型，独立上下文不等于消除共同偏差。

## 运行与项目文档

从项目根目录执行 `./run.sh` 启动本地服务，不会自动打开浏览器。依赖、服务端模型配置、Windows / Docker 说明见 [README](../README.md)。仅运行和查看文字：

```bash
uv sync --frozen
uv run research run '比较 GLD 与 BTC-USD 近五年的避险、抗通胀与组合价值' --no-export
uv run research show RUN_ID --format text
```

真实运行需要有效的服务端模型凭据并消耗额度；密钥不进入前端、研究样例或代码。本轮暂停后不再自动发起研究。历史 `samples/` 报告保留原样，未重新生成或重新核验。

[设计说明](design.md) · [原方案与验收清单](agent-research-quality.md) · [AI 开发与用户决策记录](ai-development.md)
