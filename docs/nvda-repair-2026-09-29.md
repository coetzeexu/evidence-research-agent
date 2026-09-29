# NVDA 研究缺口修复

2026-09-29。本轮修复的是检索、事件时间与独立核验的通用逻辑，没有手工修改真实运行事件或降低需求覆盖门槛。

## 原因与改动

1. 原文提取只读取少量 meta 标签，NVIDIA 公告独立日期栏被正文清洗丢失。现支持发布元数据、文章 JSON-LD 和公告日期栏，忽略更新日期与相关报道日期，不从 URL 猜日期。
2. 补查把 critical 的事件 ID 交给提取器，却没有上一轮事件。现传递 previous_events，要求保留稳定 ID 并逐项修复；按最新未覆盖年份优先安排调查。
3. 失败搜索与无法读取的官方页重复消耗预算。现对 web 累计两次失败进行熔断，同一页面最多失败两次，并返回可供替代检索的来源目录线索；失败计数持久化，重启不清零。
4. 新事件要求 date_source_id/date_quote：日期必须能定位到已读原文或同日发布元数据。程序检查引用存在，独立核验器再判断日期语义。历史样例不会被冒充经过这项新检查。
5. 市场反应的事后报道被当作新公告，盘后文章会把窗口错移到次日反弹。现用 timing_basis 区分公告与事后报道，后者按原事件日展示，关联明确标记 retrospective_report，不传播为随后几天的候选原因，也不作为当时可用信号。
6. 核验器曾把 71.5 亿美元与 7.15 billion 美元误判为量级错误。现要求比较同一指标的实际数值与单位，对 critical 另用独立上下文复核，保存初审与争议复核完整记录；真正的 critical 继续阻断完成。

## 最新验证结果

已按用户确认接入部署模型 `self-evo-glm-atl-260826`，使用 `X-PLATFORM: maas`。服务实际返回模型标识 `/workspace/model`；DeepSeek 身份由用户确认，未将模型自述作为独立证明。密钥仅留在本机服务端配置，交付包不包含密钥。

NVDA 运行 `15412514d7234a05` 从原检查点恢复，经自动补查和独立核验后通过全部 7 项检查，状态为 `complete`：7 个事件、17 个来源，点名事件与 2026 年覆盖均满足，最终核验无 findings。2025-01-27 下跌按事后报道对齐至当日，收益约 -16.97%，未错用次日反弹。未经人工修改事件或通过状态。HTML、Excel、PPT、Word 与本机运行产物均已更新。

部署模型新建 Blackwell 用例 `ac2e3a4796fc46b3` 首次遇提取调用上限，保留失败记录后从检查点恢复，全部 8 项检查通过。独立复核仍保留两条非阻断 warning：发布详情和合作公告与主事件存在重复计数风险；通过不代表无任何警告。GLD/BTC 保留此前通过的研究，本轮仅重验产物与 Excel，不声称使用新端点重新研究。

后端 **91/91**、前端 **27/27**、Ruff、TypeScript、Web/离线 HTML 构建与两套样例一致性检查通过。Excel 四组独立重算共 240 行通过，最大净资产差异约 `1.52e-9`。新版 NVDA Word 8 页、PPT 10 页已渲染并查看全部缩略总览，另对 PPT 长标题页按原图检查；未宣称所有页面全尺寸验收。本轮未打开浏览器，未重启占用 8000 端口的其他进程。

## 部署兼容修复

网关默认推理曾耗尽输出预算，导致结构化结果为空；实测关闭 vLLM thinking 后可正常输出。配置新增可选 `LLM_PLATFORM=maas`、`LLM_VLLM_THINKING=false`，其他服务可留空。内部子 Agent 禁用自身 checkpoint，避免恢复外层流水线时误取历史空结果；外层 LangGraph 检查点继续保留。结构化结果缺失现在明确报错，不会误判通过。

## 历史失败与审计

此前运行遇到核验量级误报和 HTTP 402 余额不足；失败记录 `research-quality-repair-pass1.json`、`research-quality-repair-pass2.json`、`research-quality-nvda-source-fix.json` 均保留。网关初次空结构化失败记录为 `research-quality-maas-first.json`；单事件首次调用上限记录为 `research-quality-focused-maas-initial.json`。

最终结果见 `evals/research-quality-nvda-maas.json` 与 `evals/research-quality-focused-maas.json`。NVDA 为跨服务检查点接续，实际观察过 `deepseek-flash` 与 `/workspace/model`，样例 provenance 保留配置变更历史，不冒充全程由新服务重新研究。研究原文和检查点留在本机私有运行目录，不随交付 ZIP 发布。
