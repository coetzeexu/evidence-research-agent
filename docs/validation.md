# 验证记录与复现

本页汇总截至 2026-09-29 的验证证据。当前代码的计算方法为 `2026.09.4`、正文核验协议为 `1.4`。各批次独立保留当时的版本、输入和结果；后续导出或文档修复不重新授权旧结论。

## 最近验证概览

| 批次         | 实际结果                                                                      | 证据与边界                                                                                                       |
| ------------ | ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| PPT 对齐修复 | 后端 308 项通过；黄金 39 页、NVDA 兼容输出 30 页未发现文字框重叠/越界         | [版面验证](../evals/ppt-layout-fix-20260929.json)；LibreOffice + Poppler，关键两页目检，未做 PowerPoint 实机验证 |
| 按需导出     | 后端 306 / 前端 31 项；构建、类型、格式与静态检查通过；全部 16 种格式集合覆盖 | [导出工程记录](../evals/export-engineering-20260929.json)；后端数量随后增加至 308                                |
| 格式意图     | 13/13 真实 planner 案例通过                                                   | [格式选择](../evals/output-selection-20260929.json)；仅 planner，不是完整研究                                    |
| 正式样例     | 两套样例结构与哈希校验通过                                                    | [样例验证](../evals/sample-validation.json)；NVDA HTML，黄金 XLSX/PPTX/DOCX                                      |
| 文档与截图   | 当前 WebUI 五张真实截图；本地文档链接、图片和版本一致性检查                   | [文档记录](../evals/docs-refresh-20260929.json)；无新模型任务，不新增研究通过数                                  |

此前 [工程验收](../evals/acceptance-engineering-20260929.json) 的 251 项后端、28 项前端属于早期批次，保留其原记录。最近前端 31 项与后端 308 项来自不同批次，不描述为同一条刚执行的测试命令。

## 工程回归

GitHub Actions 在 push / PR 上执行相同离线门禁，不依赖模型密钥。构建先于 pytest，确保导出资源存在；远程结果以[实际 Actions 记录](https://github.com/coetzeexu/evidence-research-agent/actions)为准。

| 检查层     | 主要断言                                                                    |
| ---------- | --------------------------------------------------------------------------- |
| 数据与计算 | OHLCV 契约、交易时序、共同锚点、费用台账、同口径基线、回撤与敏感性          |
| 证据与正文 | 引用定位、指标单位/区间、数值关系、缺口关闭、核验中断和草稿不泄漏           |
| 运行控制   | 持久预算、检查点恢复、队列领取、取消竞争、结构化模型返回、并发原子存储      |
| 前端状态   | 中文输入、重复发送、SSE 跨块解析、流式状态、来源更新、跨会话隔离与滚动跟随  |
| 文件交付   | Bundle / HTML / JSON 一致性、manifest 哈希、Office 原生结构、Excel 公式缓存 |

数值关系协议用五个冻结的真实片段做[定向重放](../evals/loop-repair-validation.json)，检查正文不变时转录能否恢复。它验证核验接口；完整研究另由八次固定问题运行检查。

新增回归覆盖指标 ID 精确规范化、绝对幅度的正负值与反例、完成度核验不能覆盖结论拒绝、明确事实缺口持续阻断、旧问题状态不淘汰本轮有效结果，以及无效补丁的一次有界重试。补丁用例同时断言调用预算、正文轮次和失败原因记录。

提取与修复分流回归验证：统一结构化提取保留原文、旧事件、补查要求和局部预算；格式、数值及措辞错误先本地修复，纯粹的必答证据缺失仍进入补查；提取调用上限耗尽后旧事实、原文和已有缺口不丢失，新失败原因传入分析且不能标记完成。

开发用 `tools/evaluate_saved_research.py` 读取指定运行的 Bundle、证据和原请求，重新执行正文生成与核验，不重新采集行情或资讯。结果写入 `evals/boundary-probes/`，模式为 `saved-evidence-development-probe`。完整验收汇总只接受独立 `live-end-to-end` 运行；快照、重复 ID、缺失必要检查或混合版本均不能计入八次通过。

## 真实研究与浏览器

下述八次是冻结版本的历史验收。后续指标 P0 的两次最终研究自动检查 2/2 通过，事后正文复核 0/2 通过，仍存在推断与必答覆盖问题，见 [P0 内容复核](../evals/p0-live-validation-20260929.json)。不能将自动通过与独立内容正确合并计算。最近导出、PPT 和文档阶段均没有重跑完整研究。

真实研究固定 NVDA / GLD-BTC 各三次、AMD / GLD-ETH 各一次，保存全部请求、正文、Bundle、版本、调用用量和核验结果。基础验收覆盖必答事实、有效引用、确定性数字、时间窗口、比较口径、预算和发布状态，结果见[运行验收](final-evaluation.md)。

本机浏览器按实际操作验证以下路径：

1. 新建并发送研究请求，服务端创建任务后打开对应会话。
2. 运行中出现真实阶段、工具开始/结束及来源进展；最终核验正文和过程信息区分展示。
3. 执行完成后正文、引用和产物入口可用，下载文件与该次 Bundle 对应。
4. 刷新或切换会话后记录归属正确，追问和迟到响应不会污染其他会话。

浏览器检查按用户明确授权执行，结果不能由 JSDOM 测试或旧截图代替。单次本机检查也不扩展为全浏览器、全尺寸或完整无障碍审计。

## 样例与独立重算

`samples/nvda/` 与 `samples/gold-bitcoin/` 已迁移至 Schema 1.1，按请求分别生成 NVDA HTML 与黄金/比特币 Excel、PPT、Word；[样例校验](../evals/sample-validation.json)记录 Bundle、内嵌数据、manifest 和 Office 结构的一致性。离线 replay 不调用模型，旧 `research=null` / `unassessed` 与原计算版本保留。

[Excel 独立重算记录](../evals/excel-recalculation.json)使用 LibreOffice 对原参数和修改参数的四组情景重算，共 240 行，最大净资产差异约 `1.52e-9` 美元。重算前清除旧缓存，避免读取交付缓存而误称独立验证。Excel 公式近似与逐日下一开盘执行回测分别标明口径。

历史 Office 检查记录包括 DOCX / PPTX 原生结构、中文字体及方法页排版。缩略总览、局部原图和全尺寸逐页检查分别记录，不相互替代。

## 既有证据索引

| 记录                                                          | 范围                                           |
| ------------------------------------------------------------- | ---------------------------------------------- |
| [API / CLI 文字验证](../evals/text-api-cli-verification.json) | 研究接口、正文快照、只读查看与无导出状态       |
| [流式交付](../evals/streaming-validation.json)                | 真实 SSE 文本、工具生命周期、来源、追问和刷新  |
| [使用动线](../evals/usage-flow-validation.json)               | 新建入口、容器滚动、固定输入区与帮助交互       |
| [清洁目录启动](../evals/clean-delivery.json)                  | 安装、构建、本地服务及产物下载                 |
| [凭据检查](../evals/credential-validation.json)               | 源码、构建资产、样例压缩文件与配置边界         |
| [事件时间修复](nvda-repair-2026-09-29.md)                     | 来源日期、事后报道对齐与检查点接续的方法和证据 |
| [早期工程复核](../evals/engineering-review-verification.json) | Schema、数据源接口及首轮 loop 修复的检查记录   |

这些文件保留对应版本的实际结果；当前验收入口不据旧记录自动继承通过状态。Windows 和 Docker 仍保留运行脚本，未声明已完成实机验证。

## 可复现命令

```bash
npm ci
npm run build
uv sync --frozen
uv run pytest -q
uv run ruff check backend tests tools
npm test -- --run
npm run format:check
uv run research replay nvda
uv run research replay gold-bitcoin
uv run python tools/verify_samples.py
# 使用真实模型与数据服务，消耗配置的服务额度
uv run python tools/evaluate_text_research.py --case all --suite Acceptance01
# 开发快照复验：调用模型，不计入完整八次；run-dir 指向保存的运行目录
uv run python tools/evaluate_saved_research.py --run-dir /absolute/path/to/runs/RUN_ID --suite LocalProbe01
# Excel 独立重算需已安装 LibreOffice
uv run python tools/verify_recalculation.py --soffice /absolute/path/to/soffice --work-dir /absolute/path/to/qa
```

最近配图仅操作隔离数据目录中的样例视图；记录见 [截图说明](assets/README.md)。文档改动没有重跑 308/31 项功能测试，沿用相应功能提交的已存结果，本轮单独检查文档链接、图片、CLI 参数和交付包一致性。
