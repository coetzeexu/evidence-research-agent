# 当前工程交付

当前 P0 增量：正文核验协议 1.4、指标契约与发布包一致性，见 [本轮说明](p0-release-20260929.md)。下文历史检查保留其原版本与范围。

Evidence 是可本地运行的投研 Agent：自然语言发起研究，使用行情与资讯工具调查，确定性计算指标，通过独立核验发布文字，并按需生成 HTML、Excel、Word、PPT。

## 交付内容

- LangChain / LangGraph 主管、研究与核验职责协作；问题清单驱动调查、补证和停止判断。
- 数值引用与关系求值由程序执行；精确规范化指标前缀，分别处理带符号和绝对幅度比较，核验器通过片段 ID 定位原句。
- 显式缺口跨补丁、恢复与完成判定保留；关闭需引用已批准结论和可定位的回答依据。
- 独立 `question-review` 只用已核验段落核对完成度，区分必答事实缺失、研究局限与额外方法，不改写结论判定。
- 旧问题状态重新初始化，同输入哈希的核验结果可恢复；精确补丁无效时同轮最多重试一次，保留失败原因与已核验内容。
- API / CLI 支持只生成与查看文字；网页会话展示工具动作、来源和阶段进展，正文核验后发布。
- NVDA / GLD-BTC 样例采用 Schema 1.1，Bundle、HTML 内嵌数据、Office 文件与 manifest 一致。
- 行情、资讯、宏观能力通过 DataProviderInterface 注入，提供公共实现和服务端插件扩展接口。
- GitHub 私有仓库保留关键工程提交；Actions 执行构建、pytest、Vitest、静态检查和样例校验。

## 验证入口

| 范围                               | 证据                                                                                         |
| ---------------------------------- | -------------------------------------------------------------------------------------------- |
| 固定版本八次真实研究与本机会话验收 | [运行验收](final-evaluation.md)                                                              |
| 后端、前端、静态检查与构建         | [工程验证](validation.md)、[工程验收机器记录](../evals/acceptance-engineering-20260929.json) |
| 数值关系与缺口闭环                 | [工程复核](engineering-review.md)、[定向重放](../evals/loop-repair-validation.json)          |
| 两套样例重导出与结构一致性         | [样例校验](../evals/sample-validation.json)                                                  |
| 远程自动化                         | [GitHub Actions](https://github.com/coetzeexu/evidence-research-agent/actions)               |

每份记录保留当次版本、请求与范围。工程回归验证确定性行为，真实研究检查问题覆盖和证据链，浏览器验收检查用户操作及展示。

正文核验协议为 `1.3`，计算方法仍为 `2026.09.4`。开发快照复验使用独立 probe 标记，不计入完整八次真实研究。

## 使用与边界

[README](../README.md) 提供一键启动、环境配置、文字接口和测试命令。`./run.sh` 启动服务；`uv run research run '研究问题' --no-export` 只生成文字研究。

历史样例的离线 replay 不调用模型，因此 `research=null`、正文核验状态为 `unassessed`；新的正文结果单独保存在真实运行记录中。数据源扩展接口不等于已接入 Tushare、Wind 或 Bloomberg，商业服务需要适配真实口径与许可。密钥仅留在服务端，不进入仓库或前端。

[GitHub 私有仓库](https://github.com/coetzeexu/evidence-research-agent) · [设计说明](design.md) · [研究验收方法](agent-research-quality.md) · [数据源扩展](data-providers.md) · [AI 开发记录](ai-development.md)
