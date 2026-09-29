# 工程开发与复现指南

产品介绍与一键启动见 [README](../README.md)，研究质量与文件验证分开记录在 [validation.md](validation.md)。本页用于定位代码、调试接口、运行评估与导出可校验的交付包。

## 本地开发

```bash
uv sync --frozen
npm ci
npm run build
uv run research serve
```

后端默认 http://127.0.0.1:8000，API 文档在 `/docs`，健康检查为 `/api/health`。生产运行由 FastAPI 托管 `dist/web`，浏览器同源访问 API。另开终端执行 `npm run dev` 可用 Vite 开发前端，`/api` 代理到 8000；更改后端端口时也需调整开发代理。

配置来自 `.env` 和环境变量，变量定义见 [.env.example](../.env.example)。运行数据库、LangGraph 检查点、证据缓存和研究快照保存在 `RESEARCH_DATA_DIR`（默认 `.research-data`），该目录不入库、不进入交付 ZIP。不要为了调试打印密钥或把整份运行目录提交到仓库。

如果只需查看样例，保持模型字段为空即可。文档配图曾用隔离目录启动服务，避免混入个人会话；截图采集没有创建真实模型任务。

## 从哪里改代码

| 需求                         | 主要入口                                                                           |
| ---------------------------- | ---------------------------------------------------------------------------------- |
| 主管、研究工具、独立核验调用 | `backend/research_app/agents.py`                                                   |
| 流程节点、补查、预算、恢复   | `pipeline.py`、`budget.py`、`storage.py`                                           |
| 问题/证据/结论结构、正文发布 | `research_contract.py`、`research_text.py`、`research_semantics.py`                |
| 指标单位、格式化、数值关系   | `research_metrics.py`、`research_logic.py`                                         |
| 行情、事件窗口、组合、敏感性 | `analytics.py`、`sensitivity.py`                                                   |
| 兼容模型的结构化输出协议     | `tool_protocol.py`                                                                 |
| 数据源与外部读取安全         | `data_providers.py`、`providers.py`、`security.py`                                 |
| 格式选择与产物生成           | `domain.py`、`prompts/planner.md`、`exporters.py`、`export_slides.py`              |
| 会话、图表、独立 HTML        | `apps/web/App.tsx`、`ResearchView.tsx`、`StandaloneReport.tsx`、`packages/charts/` |

路径未写前缀的 Python 文件均位于 `backend/research_app/`。角色提示在 `prompts/`，研究方法在 `skills/`。具体运行职责见 [设计说明](design.md)，Prompt 与人工决策索引见 [AI 开发记录](ai-development.md)。

## CLI 与 API

仅研究、不导出；下列 `RUN_ID` 使用首条命令返回的实际 ID：

```bash
uv run research run '比较 GLD 与 BTC-USD 近五年的避险与抗通胀证据' --no-export
uv run research show RUN_ID --format text
uv run research show RUN_ID --format json
```

`show` 只读保存的研究结果，不调用模型。`--no-export` 会持久化，恢复时仍不生成文件。历史样例没有新协议正文时，`show` 会提示 `unassessed`，不要用它证明新核验已通过。

```bash
curl -X POST http://127.0.0.1:8000/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"比较 GLD 与 BTC-USD 近五年避险、抗通胀和配置价值","export_reports":false}'
curl http://127.0.0.1:8000/api/runs/RUN_ID/research
```

新任务接口返回任务 ID，结果异步生成。HTTP 状态和任务状态以接口返回为准，不要在刚创建后假定正文已经存在。`research.status` 为 `complete / partial / failed`；任务 `researched` 表示文字流程结束且关闭文件导出，两者含义不同。

重导出已有任务：`uv run research export RUN_ID`，按快照中的 `outputs` 生成文件。离线重放内置样例不调用模型或重新拉取行情：

```bash
uv run research replay nvda --output /tmp/evidence-nvda
uv run research replay gold-bitcoin --output /tmp/evidence-gold-bitcoin
```

省略 `--output` 会更新仓库里的样例产物及必要的 Schema 迁移记录，通常只在主动刷新交付样例时使用。离线 replay 不会更新历史计算方法或补出缺失的正文核验记录。

## 功能验证与真实评估

先构建，再测试：导出测试需要实际构建的 HTML 资源。

```bash
npm run build
uv run pytest -q
npm test
uv run ruff check backend tests tools
uv run ruff format --check backend tests tools
npm run format:check
uv run python tools/verify_samples.py
```

`verify_samples.py` 会更新 `evals/sample-validation.json` 的运行记录。提交前检查 diff，保留真实验证时间。CI 配置为 [.github/workflows/checks.yml](../.github/workflows/checks.yml)，无需模型密钥；不要将离线 CI 描述为真实研究效果评估。

以下命令使用实际模型/检索服务，会消耗所配置服务的额度：

```bash
uv run python tools/evaluate_text_research.py --case all --suite LocalAcceptance01
uv run python tools/evaluate_saved_research.py --run-dir /absolute/path/to/runs/RUN_ID --suite LocalProbe01
```

第一类检查完整采集与研究，第二类复用已有证据定位问题。开发 probe 不计入端到端验收，不能拼接不同版本或重复运行来凑通过数。真实验收与独立内容复核的区别见 [运行记录](final-evaluation.md)。

PPT 回归覆盖布局契约；视觉检查需将 PPT 转为 PDF，再用 Poppler 输出文字边界。当前脚本读取已有边界文件：

```bash
pdftotext -bbox-layout report.pdf report-bounds.html
uv run python tools/verify_ppt_render.py report-bounds.html
```

边界检查只检测文字框的相交与越界，不能替代字体、留白或 PowerPoint 实机检查。最近 PPT 修复过程见 [导出说明](export-presentation-20260929.md)。

## 打包与发布

交付脚本使用白名单文件集合，不直接压缩工作目录；排除 `.env`、运行数据、`.git`、虚拟环境及依赖目录。附带文件哈希清单与 Git 提交/工作区状态，打包时执行凭据检查。

```bash
uv run python tools/package_delivery.py --output ../research-agent-delivery.zip
uv run python tools/package_delivery.py --verify ../research-agent-delivery.zip
```

`verified:true` 表示包内文件及哈希通过，`source_matches:true` 表示与当前白名单源码逐文件一致。正式交付应在相关改动提交并 push、工作区干净后重新打包；`.sha256` 随包生成。截图保存在 `docs/assets/`，因此会与 README 一起进入 ZIP，本地查看不依赖外链图片。

## 常见问题

| 现象                         | 排查方式                                                                   |
| ---------------------------- | -------------------------------------------------------------------------- |
| 无法新建研究，提示模型未配置 | 查看 `.env` 三个模型字段，确认服务支持工具调用，修改后重启；样例仍可浏览   |
| 8000 端口被占用              | 在 `.env` 修改 `RESEARCH_PORT`；Vite 开发模式同时调整代理                  |
| API 可用但首页不存在         | 执行 `npm run build` 后重启服务；静态目录在后端启动时挂载                  |
| 下载 HTML 后空白             | 使用完整的当前产物；开发时先构建再导出，避免引用旧运行包；检查浏览器控制台 |
| 研究部分完成 / 数据缺页      | 看具体缺口、覆盖时间与来源失败；不能以手改状态或补写数字绕过核验           |
| PPT 在另一台电脑换行不同     | 核对中文字体与 Office 渲染差异；当前校验基于 LibreOffice，保留必要复核     |
| 离线 HTML 无法追问或更新价格 | 文件不连接服务；这些操作在运行中的 WebUI 完成                              |

Docker 提供 `docker compose up --build`，Windows 提供 `run.ps1`；这两条部署路径尚未做实机验收。当前服务面向本地单用户，若部署到公网，需要另行设计认证、租户隔离和运行资源限制。
