# 按需产物与独立报告展示

本轮仅改产物契约、导出器、独立报告视图和 PPT 模板。`agents.py`、`pipeline.py`、预算、检索、研究/核验 loop 均未修改；主管的 planner 提示仅更新产物选择语义。

## 格式契约

`ResearchSpec.outputs` 表示实际交付集合，四种受支持格式不等于默认四份文件。去重保留顺序，不再强制加 HTML；空集合表示不导出报告文件。未限定格式的报告默认 HTML。

| 用户描述                                                 | 产物             |
| -------------------------------------------------------- | ---------------- |
| 原题 NVDA，最终生成一个 HTML                             | html             |
| 原题黄金/比特币，Excel 底稿、PPT 决策框架、Word 策略报告 | xlsx、pptx、docx |
| 报告、策略报告、分析报告、交互报告                       | html             |
| 文档、策略文档、Word 报告                                | docx             |
| 回测底稿、电子表格、Excel                                | xlsx             |
| 汇报材料、演示文稿、PPT                                  | pptx             |
| 仅文字、不导出文件                                       | 空集合           |

明确格式优先于泛词。“Word 策略报告”只选 Word。明确列出 Excel/PPT/Word 时，不因为上文说“可交互体系”而补 HTML。后续改时间/资产保留产物；“只要”替换，“再加”增加，“不要”删除。支持新请求显式选全部四种。

导出器严格按集合调用；仅 Word 需要离线图表图片预处理。成功重导出后清理已不再请求的旧格式，下载 API 同时按当前规格拒绝旧文件，manifest 写入 requested_outputs。research-data.json 与 manifest 是审计元数据，不属于用户报告格式。

## 独立 HTML

`StandaloneReport.tsx` 与工作台 `ResearchView` 分开。报告使用封面、目录锚点、连续章节与来源附录；不复用工作区 tab，不显示“研究范围与依据”、产物列表、其他格式下载入口、包体积或开发实现说明。

保留 K 线缩放、事件反应筛选、事件证据详情、原始链接、来源与数据底稿。多资产 HTML 可切换名义净值/购买力/回撤，并连续展示配置、压力月份、通胀和敏感性。离线页面不放无法执行的重算输入框。生成内容使用 React 转义与 Markdown 安全链接，不执行原文 HTML。

继续单文件内联 JS/CSS/数据，CSP 固定脚本 SHA-256，connect-src none，无 CDN、字体下载、服务端 API 或运行时跨域依赖。没有为了减小文件而改成需联网的分包。依赖按 ECharts 已用组件构建；页面只展示研究内容。

## PPT 方法模板

使用用户指定的 [ppt-master](https://github.com/hugohe3/ppt-master) 及 [Apple FY2025 账页示例](https://hugohe3.github.io/ppt-master-examples/viewer.html?project=ppt169_apple_fy2025_review)。先定位原始 `operating-review` 方法模板，再沿示例 `design_spec.md` / `spec_lock.md` 提取规则与参数，图片仅核对视觉结果。

精简 skill 位于 [skills/ppt-ledger](../skills/ppt-ledger/SKILL.md)，保留原方法模板、必要参考、MIT 许可、固定提交和逐文件哈希。导出器按此契约生成原生可编辑表格/图表和来源备注；不搬入整套上游脚本，也不将模板工作流接入 Agent loop。具体规则落实与不适用项见 [PROVENANCE](../skills/ppt-ledger/PROVENANCE.md)。

## 验证与样例

- 真实模型仅调用现有 planner：13 个案例全部通过，原始请求、预期与实际格式保存在 `evals/output-selection-20260929.json`。不是完整研究内容评估。
- 单元回归覆盖全部 16 种格式子集、默认值、去重、不支持格式、旧格式清理及下载拒绝。
- HTML 组件测试检查连续章节、目录锚点、没有工作区/产物入口、事件筛选、证据链接、比较章节；构建测试检查离线脚本不读取 Node 环境。
- 样例按原题重新导出：NVDA 只有 HTML，黄金/比特币只有 Excel、PPT、Word。保留原行情、事件、方法版本和未核验标识；本轮没有重新研究或改变历史结论。
- 完整测试、PPT 渲染和最终交付包核验记录单独保存。未经实测的平台与研究质量不因导出修复而宣称通过。

## AI 开发记录

Codex 主 agent 负责格式契约、导出分发、HTML、样例与交付；用户授权的 PPT 子 agent 负责源 skill 提取、PPT 导出实现和渲染检查。用户修正“报告/策略报告→HTML，文档→Word”，并指出应追溯 operating-review 原始方法模板；两项判断均进入实现与验收。没有调整研究 loop，也没有以重新生成正文掩盖历史内容缺口。

## 对齐与重叠修复

用户截图暴露了此前检查遗漏：表头逐单元格按文字左对齐，数值按数字右对齐；文本框保留 SHAPE_TO_FIT_TEXT，实际字体替换可能让文本框高于分页估算并压住下一行。

现改为整列统一对齐、固定行距与零段间距、禁止自动增高/二次换行，正文高度和分页使用同一个行高函数。表格同样使用明确换行与高度，保留全部文字。两项回归修复前失败、修复后通过，完整后端 308 项通过。已重渲染黄金 39 页及 NVDA 兼容输出 30 页，Poppler 全文字框检查未发现重叠或页外文字；目检收益风险页与事件长段落页。验证引擎为 LibreOffice，未声称 Microsoft PowerPoint 实机验收。见 [本轮验证](../evals/ppt-layout-fix-20260929.json)。

本轮只替换正式黄金 PPT 和相应 manifest，Excel、Word、HTML 及研究 loop 未修改。此前导出验证记录保留原版本与哈希。
