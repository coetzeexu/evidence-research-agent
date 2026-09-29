# 当前工程交付

已完成本轮明确授权的 loop 修复与工程改进。上一轮八次模型评估作为历史记录保留；本轮未将它们重新认证为全部 complete。模型语义表现不列为工程待办。

## 交付内容

- 修复数值核验协议：一次有预算的核验器修复，选择程序生成的片段 ID；程序回填原句并重新求值，不改正文、不升级原事实判定。
- 修复缺口闭环：初稿缺口跨补丁和恢复保留，关闭需显式 gap ID、已批准结论及可定位回答，开放缺口可触发定向调查。
- NVDA / GLD-BTC 样例升级至 Schema 1.1，重导出 HTML、Excel、Word、PPT；Bundle、内嵌数据与 manifest 一致。离线 replay 不生成研究，旧正文核验状态明确为 unassessed。
- 行情、资讯、宏观能力通过 DataProviderInterface 注入；默认公共实现和服务端插件注册可用。没有宣称已接入付费商业服务。
- 建立 GitHub 私有仓库并按关键阶段提交；Actions 执行构建、pytest、Vitest、静态检查和 verify_samples。

## 验证与复核

| 检查 | 结果 |
| --- | --- |
| 后端 | 156 项通过，包含 3 项实际导出测试 |
| 前端 | 28 项通过 |
| 构建及静态检查 | 构建 / TypeScript / Ruff / Prettier 通过 |
| 样例 | 两次 replay 与 verify_samples 通过 |
| GitHub CI | [实际远端运行通过](https://github.com/coetzeexu/evidence-research-agent/actions/runs/36555985127) |
| 原失败片段重放 | 五次 partial 各取一条原失败结论，5/5 通过数值关系复验，正文不变 |
| 范围 | 未再次执行八次完整研究，未换模型，未打开浏览器或加载图片 |

[工程验证记录](../evals/engineering-review-verification.json) · [五条定向重放](../evals/loop-repair-validation.json) · [样例校验](../evals/sample-validation.json)

## partial 与问题归因

partial 表示有可发布正文，但必答问题尚未完成；不是程序崩溃，也不是可信度百分比。此前五次主要卡在数值关系转录。完成状态与文件导出状态独立。

无依据 CPI / 预期推断的漏检主要体现本配置模型的语义判断表现，保留为历史观察。转录失败错误地路由给作者、以及 gaps 丢失属于确定性流程缺陷，本轮已修复。详细代码证据、五次原因与 Gemini 建议取舍见 [工程复核](engineering-review.md)。

## 入口

项目代码与一键运行：[README](../README.md)。`./run.sh` 启动服务，不自动打开浏览器；`uv run research run '研究问题' --no-export` 只生成文字研究。

[GitHub 私有仓库](https://github.com/coetzeexu/evidence-research-agent) · [Actions](https://github.com/coetzeexu/evidence-research-agent/actions) · [设计说明](design.md) · [数据源扩展](data-providers.md) · [AI 开发记录](ai-development.md)

历史八次正文、Bundle、原文引文、指标与审阅仍在 [评估目录](final-evaluation.md)，不删除或手工改写失败样例。源码与凭据分开，密钥不进入仓库或前端。
