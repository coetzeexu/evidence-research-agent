---
name: ppt-ledger
description: 按已核验研究数据制作账页式、可编辑、可溯源的 PPT；仅在选择 PPT 输出时使用。
---

# 账页式研究决策稿

这是用户指定 `hugohe3/ppt-master` 的 `ppt169_apple_fy2025_review` 风格子集，
不是完整上游工作流。只迁移版式与原生对象要求，不带入苹果数据、品牌、图标、
模型路由、外部下载、动画或其他产物。来源与 MIT 许可见 [PROVENANCE.md](PROVENANCE.md)。

## 执行

1. 输入为已有 `ResearchBundle`，不发起研究、不改结论、不改 Agent loop。
2. 先读取原始方法模板 [operating-review.md](references/operating-review.md)，按结果 → 偏差 → 原因/未知 → 证据 → 决策条件组织材料，再读取 [design-tokens.json](design-tokens.json)；导出器以它作为唯一色彩、字体和固定栅格来源。
3. 按需编排：封面关键数、收益风险账页、共同净值、压力样本、通胀分组、
   配置回测与全部敏感性情景、决策条件、事件证据、来源索引。
4. 调用 `research_app.export_slides.export_slides(bundle, path)`。只生成 PPTX。
5. 长内容换页，不隐藏行、不删减敏感性情景。每页来源可点击，备注保存对应
   原始 URL、数据哈希、时间区间、字段路径与研究边界。拒绝不安全链接。
6. 验证原生图表/嵌入工作簿、可编辑表格、几何边界、数字格式和分页；
   通过 LibreOffice PDF 渲染检查实际文字和版面。不得以“测试通过”代替视觉检查。

## 版式契约

- 16:9 白底，顶部标题、中部证据、底部来源三段固定；细线形成账页栅格。
- 文本深灰，数据蓝/绿/红，正负由符号同时表达，灰度仍可辨认。
- 数字使用等宽字族、表内右对齐。指标必须保留单位、样本数、比较口径。
- 无渐变、阴影、圆角 KPI 卡、产品导航、执行进度、交付文件清单。
- 封面只给主题、区间、关键指标。标题不凭空拔高；证据不足时用主题标题。
- 全部表格、折线图保持 PowerPoint 原生可编辑，图表内含数据工作簿。
- 不承诺另有 HTML/Excel/Word，PPT 必须可独立阅读与溯源。

## 参考

- [reference-style.md](references/reference-style.md)：经过裁剪的视觉规范。
- upstream-cover.svg / upstream-scorecard.svg：上游两张示例供版式复核；包含苹果历史
  示例数据，仅作参考，不进入生成产物，不作为金融事实来源。
