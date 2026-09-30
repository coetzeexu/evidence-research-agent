# 行情变化点归因覆盖（2026-09-30）

## 问题

面试题要求“事件与行情拐点吻合，有一定关联逻辑”。上一版 NVDA 样例（方法 `2026.09.3`）K 线上标了 23 个变化点，只有 4 个有关联事件，其余点读者无法区分两种情况：**查过但没找到**，还是**根本没查**。另外，研究 Agent 看到的变化清单（`maximum=10`）和图上发布的变化点并不一致。

## 改动

| 层                  | 改动                                                                                                                                                                                            | 文件                                                                         |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| 计算                | `detect_changes` 默认 `CHANGE_LIMIT=12`；pipeline 不再单独截断，保证研究清单等于图上标记                                                                                                        | `analytics.py`、`pipeline.py`                                                |
| 质量门禁            | `attribute_changes` 为每个点写入 `attribution={status, method, queries, leads, note}`：`linked` / `investigated_unexplained` / `not_investigated`                                               | `quality.py`                                                                 |
| Agent 分工          | 研究子 Agent 在点名事件后按 strength 逐个窄窗检索无事件的点，先查财报/指引，禁止用相近事件硬凑                                                                                                  | `prompts/researcher.md`、`skills/event-study/SKILL.md`                       |
| 代码补查（tool 层） | 子 Agent 预算用完后，代码对仍未检索的点做一次有界、不耗模型调用的窄窗检索（前 5 天至后 3 天，按公司名，限 8 个，60s 超时）。结果只作为**未读取的候选线索**写入 coverage，不生成事件、不作为证据 | `change_sweep.py`、`agents.py::sweep_moves`                                  |
| 核验误报            | “方向与报道一致”这类定性句、“最高 20 petaflops”这类原文规格上限，不再被要求写数值断言                                                                                                           | `research_logic.py`、`prompts/numeric-review.md`、`prompts/text-reviewer.md` |
| 展示                | HTML/WebUI 新增“行情变化点与事件归因”表：状态筛选、事件点击打开证据弹窗、“自动补查”标记、候选线索（经 `safeUrl` 过滤，只允许 http/https）；K 线上未关联点用实心灰（已检索）或空心（未检索）区分 | `ChangeAttribution.tsx`、`options.mjs`                                       |
| 底稿                | Excel 新增 `Changes` 表，列出状态、检索方、检索词和候选线索                                                                                                                                     | `export_workbook.py`                                                         |

**边界：** 让模型决定“查什么、怎么判断”，让代码保证“每个点至少查过一次、查的结果如实标出”。代码补查不读原文，所以永远不会把一个点变成“已关联”。

## 样例结果（NVDA，DeepSeek-V4.1-Flash，运行 `e8a8611a`）

| 事件 | 来源 | 变化点 | 已关联事件 | 已检索（附检索记录） | 未检索 |
| ---- | ---- | ------ | ---------- | -------------------- | ------ |
| 10   | 16   | 17     | 7          | 10                   | 0      |

已关联的 7 个点中，5 个是 NVDA 财报/指引（2023-02、2023-05、2024-02、2024-05、2026-08），另有 DeepSeek 冲击（2025-01-27）和 2026-02-06 的资本开支事件。2021–2022 年的回升拐点由代码补查完成窄窗检索，表中标为“自动补查”，候选线索单独列出。Blackwell 平台按官方命名（B200/GB200）标注，对应题目中的 B100 系列。

## 验证

- 新增 `tests/test_change_sweep.py`，覆盖窄窗与跳过已检索点、失败记录、上限、公司名检索、`javascript:` 线索过滤，以及 sweep 与 researcher 的区分。
- `test_loop_repairs.py` 新增“最高 20 petaflops”不误报、“强度最高”仍需断言的参数化用例。
- 前端测试断言“自动补查”标记、候选线索，以及不安全链接没有 href。
- 样例通过 `tools/verify_samples.py`。旧样例的 `export-refresh.json`、`schema-migration.json` 描述的是被替换的运行，已删除，历史可以从 Git 找回。
- 用无头 Chromium（Playwright）打开 `samples/nvda/artifacts/report.html`：无控制台错误，无任何非 `file:`/`data:` 请求（CSP 生效），归因表 17 行完整显示，文本列自适应换行。

## 同轮稳健性增强

- `research_contract.decode_json_container` 可解码“恰好一个完整 JSON 数组/对象”的字符串化输出，其余格式照常拒绝；由 `tests/fixtures/meaning-review-double-encoded.json` 与 `test_review_protocol.py` 覆盖。
- 成对的 text-reviewer / meaning-review 调用支持 `REVIEW_CALL_LIMIT=3` 次有界重试；结构化提示明确数组不得二次编码。
