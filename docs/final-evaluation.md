# 当前版本运行验收

固定版本八次真实研究已完成，自动检查 **8/8 通过**，八次正文状态均为 `complete`。NVDA 与 GLD/BTC 各连续三次，AMD 与 GLD/ETH 各一次；未混用旧批次成功记录，也未手改输出。

自动检查验证任务执行、必答问题状态、引用与数值计算、时间窗口、比较口径、预算及核验发布。独立阅读另外保留模型表述观察：部分输出仍有日期换算、比较关系或推断措辞错误，所以自动通过不等于“正文全部无误”。严格内容标记按原始复核结果保留于机器记录；按本轮收尾范围，不继续调模型，也不将这些观察列为新增工程待办。

| 场景 | 运行正文 | 自动检查 | 耗时（秒） | 模型调用 |
| --- | --- | --- | ---: | ---: |
| nvda | [ab95141d29e24af5](../evals/text-research/Acceptance20260929EventsE/nvda-ab95141d29e24af5.txt) | 通过 | 346.1 | 50 |
| nvda | [632f8c401c004cbf](../evals/text-research/Acceptance20260929EventsE/nvda-632f8c401c004cbf.txt) | 通过 | 417.2 | 50 |
| nvda | [438cd152d4364176](../evals/text-research/Acceptance20260929EventsE/nvda-438cd152d4364176.txt) | 通过 | 378.7 | 48 |
| amd | [1f50da840f0e4b14](../evals/text-research/Acceptance20260929EventsE/amd-1f50da840f0e4b14.txt) | 通过 | 301.3 | 52 |
| gold-bitcoin | [69400e6337754c84](../evals/text-research/Acceptance20260929ComparisonE/gold-bitcoin-69400e6337754c84.txt) | 通过 | 216.3 | 23 |
| gold-bitcoin | [00a13c2c3fe04940](../evals/text-research/Acceptance20260929ComparisonE/gold-bitcoin-00a13c2c3fe04940.txt) | 通过 | 207.9 | 24 |
| gold-bitcoin | [702591e91b73439d](../evals/text-research/Acceptance20260929ComparisonE/gold-bitcoin-702591e91b73439d.txt) | 通过 | 261.8 | 23 |
| gold-ethereum | [945a08d57adf4bd7](../evals/text-research/Acceptance20260929ComparisonE/gold-ethereum-945a08d57adf4bd7.txt) | 通过 | 250.2 | 23 |

八次研究的生产代码、Prompt、技能和来源目录哈希均为 `e3c22e0b481d11f4ebf5398c91ed136710a8397d20842026e139fbc2995b5085`。服务实际返回模型标识为 `/workspace/model`，不据代理配置推断模型身份。研究文字、Bundle、请求、用量、版本及独立复核记录全部保存。

独立 Python 标准库重算共 884 项通过：覆盖日线收益风险、已存执行净值与现金/资产对账、压力月计数及 CPI 分组。它没有重新模拟全部交易执行引擎，也不替代文字语义复核。

本机浏览器会话 `1359d9b1848e49dd` 完成请求提交、312 条顺序过程事件、核验后正文展示，四类文件实际保存成功。HTML 以 `file://` 打开并切换视图，Office 文件结构、来源超链接和 Excel 缓存无错误。未进行 Office 逐页视觉审计。

收尾补丁另加来源临时错误一次重试，并移除所有 tab 共用的范围核对面板；没有修改模型、Prompt 或计算口径。八次固定版本运行先于此传输/UI 补丁，其版本不被替换为补丁后的版本。补丁由定向传输测试、完整工程回归、前端构建及样例校验验证。

[机器可读汇总](../evals/text-research/acceptance-20260929-summary.json) · [浏览器证据](../evals/browser-acceptance-20260929.json) · [工程验证](validation.md)
