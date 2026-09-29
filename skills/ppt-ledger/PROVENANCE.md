# 来源、范围与许可

- 项目：https://github.com/hugohe3/ppt-master
- 上游版本：`680de11f1bef4628b68d5daad9dffec569fbd51f`（读取 SKILL.md 与 MIT LICENSE）。
- 指定示例：https://hugohe3.github.io/ppt-master-examples/viewer.html?project=ppt169_apple_fy2025_review
- 示例版本：`5f9923ad9bb1882a88aa29e5311a6a8a28cfc77a`
- 提取日期：2026-09-29。
- 许可：MIT，Copyright (c) 2025-2026 Hugo He，完整文本见 LICENSE。

保留的上游文件为 operating-review 原始 design_spec.md、示例 spec_lock.md、
`svg_output/01_cover.svg`、`svg_output/02_scorecard.svg` 和许可。design-tokens.json 是 spec_lock.md 中使用到的色彩、字体、间距的适配。
SKILL.md 与 reference-style.md 为本项目裁剪改写。没有复制完整上游 skill、
执行脚本、示例数据表或 PPTX，不依赖上游远程服务。

实际执行接入位于 `backend/research_app/export_slides.py`：确定输出 PPT 后读取
本目录的设计契约并生成原生可编辑对象。沿用项目已锁定的 python-pptx 依赖，
不移植整个 SVG 转换器。该实现为模板风格适配，不声称调用完整 ppt-master CLI。

## 原始方法模板引用链

`ppt-master/templates/styles/operating-review/templates/design_spec.md`
→ 示例 `examples/ppt169_apple_fy2025_review/design_spec.md` 第 29 行 `Template Application`
→ 示例 `spec_lock.md`（具体字体、色彩与页面栅格）
→ 本地 `references/operating-review.md` + `design-tokens.json`
→ `LedgerDeck` 与 `export_slides`。

示例第 29 行明确声明“挂用 operating-review Style 方法模板，只取其 Direction / method 段”，
且自身也没有计划值、责任人或承诺日期，改用同期比较与待回答问题。
本项目同样不编造这些字段。逐文件固定版本、哈希与字节数见 source-manifest.json。
所有版式取值来自源规范；网页和官方缩略图仅用于视觉核对。

## 规则落地范围

| operating-review 原始规则 | 本项目实现 |
| --- | --- |
| briefing + pyramid，结果优先 | 封面关键数 → 收益风险账页 → 同口径差异 → 解释边界 → 图表证据 → 决策条件 |
| actual / plan / prior 显式区分 | 固定历史区间，无计划值；仅比较同一月末锚点的资产，差异用百分点 |
| 原因必须有证据 | 明确“原因尚未确立”，事件窗口与 CPI 分组不包装为因果 |
| 定义、来源、提取日期、期间 | 页上单位/区间/可点原文，备注字段路径、快照哈希、原始数据地址 |
| 原生可编辑图表与账页表格 | python-pptx 原生 chart + 嵌入 xlsx，原生 table；无截图化正文 |
| 保留坏数、余项、明细 | 不筛掉负收益/压力月份，敏感性全情景自动分页，事件全部保留 |
| 责任人、日期、上期承诺、预测 | 不适用：输入无此类字段，改为待验证问题与决策条件，禁止虚构 |

这是明确挂载方法与样式的本地导出实现，不把模板工作流接入 Agent loop。
