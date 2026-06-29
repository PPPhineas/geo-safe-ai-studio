# 灾圈监测点风险研判

「地灾预警 AI Studio」的一个功能模块：根据灾圈圈定范围，对圈内地质灾害监测点做综合风险研判，生成结构化研判结果、可视化报告和 A2UI 交互组件。

当前项目已实现 FastAPI 后端主链路，支持 Mock CSV 开发演示、ClickHouse 真实数据接入、LLM 研判、报告版本修订与离线打包下载。

> 设计原则：**数字交代码、语义交模型、结论可溯源、来源要标注**。详见 `CLAUDE.md` 与 `docs/` 设计文档。

## 数据链路

```text
灾圈多边形
  → CH/Mock 空间筛选
  → 字段清洗 + 区域补全
  → 代码统计 + 空间分析
  → 时序接入 + 趋势预测
  → 降雨-变形耦合 + 预警历史
  → 三层装配
  → AI 研判 JSON
  → 校验 / A2UI / 报告渲染 / 版本归档
```

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env
# 开发演示可配置 CH_MOCK_CSV=示例\figures\monitor_points.csv
# 真实环境需填写 ClickHouse 与 LLM 配置

uvicorn app.main:app --reload
```

打开：

- API 文档：http://127.0.0.1:8000/docs
- 简易调试 UI：http://127.0.0.1:8000/ui/
- 健康检查：http://127.0.0.1:8000/health

## API 能力

| 接口 | 说明 |
|---|---|
| `POST /api/v1/risk-report` | 一次性生成完整风险研判报告 |
| `POST /api/v1/risk-report/stream` | SSE 流式生成，按阶段返回进度、LLM 输出、校验、A2UI 和最终报告 |
| `GET /api/v1/risk-report/{report_id}` | 获取报告版本列表和当前版本正文 |
| `POST /api/v1/risk-report/{report_id}/revise` | 根据段落批注生成新的完整 Markdown 报告版本 |
| `GET /api/v1/risk-report/{report_id}/bundle` | 下载报告 zip，包含 Markdown、图件、附件和研判 JSON |
| `POST /api/v1/a2ui/action` | 接收前端 A2UI 交互操作回传 |

## 已实现能力

- 空间筛选：ClickHouse 多边形筛选，开发阶段可用 CSV Mock 数据源。
- 统计分析：灾害类型、规模等级、预警等级、威胁人口与财产等代码侧统计。
- 空间分析：DBSCAN 连片带、KDE 热点、影响范围与空间分布图。
- 趋势分析：文本趋势识别、L1/L2/L3/L4 传感器时序接入、短期趋势预测。
- 雨量分析：按雨量计字段计算 24h/72h 雨量、小时雨强峰值和雨强等级。
- 专业增强：降雨-变形耦合分析、近 N 天预警历史分析。
- AI 研判：Prompt 装配、LLM JSON 输出、研判结果校验与重试降级。
- 报告渲染：Markdown 成稿、Plotly 图表、地图图件、CSV 附件、离线 zip 打包。
- A2UI：生成声明式组件，支持前端在报告正文中嵌入交互式卡片、图表、列表和地图。
- 版本管理：报告 v1 自动归档，批注修订生成后续版本。

## 代码结构

| 路径 | 职责 | 对应设计文档 |
|---|---|---|
| `app/main.py` / `app/api/` | FastAPI 入口、路由、请求/响应模型 | `docs/灾圈监测点风险研判_前端集成对接说明.md` |
| `app/config.py` | CH、LLM、聚类、趋势、雨量、预警历史等配置 | `.env.example` |
| `app/pipeline/selection.py` | CH/Mock 空间筛选，剔除无效点 | `docs/灾圈监测点风险研判_配套装配与渲染说明.md` |
| `app/pipeline/cleaning.py` | 字段清洗、归一化、缺失计数 | `docs/灾圈监测点风险研判_配套装配与渲染说明.md` |
| `app/pipeline/statistics.py` | 代码统计、分布与汇总 | `docs/统计图表内容与技术栈.md` |
| `app/pipeline/spatial.py` | 空间分析、聚类、热点、凸包 | `docs/空间分析内容与技术栈.md` |
| `app/pipeline/timeseries.py` | 传感器时序读取与日聚合下推 | `mschema` |
| `app/pipeline/trends.py` | 趋势识别、异常点识别、短期预测 | `docs/灾圈监测点风险研判_配套装配与渲染说明.md` |
| `app/pipeline/rain_deformation_coupling.py` | 降雨-变形耦合分析 | `docs/灾圈监测点风险研判_配套装配与渲染说明.md` |
| `app/pipeline/warning_history.py` | 预警历史分析 | `docs/灾圈监测点风险研判_配套装配与渲染说明.md` |
| `app/pipeline/assembly.py` | 三层装配、重点点位筛选、报告占位符 | `docs/灾圈监测点风险研判_报告成稿模板.md` |
| `app/pipeline/judgement.py` | AI 研判调用与 JSON 解析 | `docs/灾圈监测点风险研判提示词.md` |
| `app/pipeline/validation.py` | 渲染前校验 | `docs/灾圈监测点风险研判_配套装配与渲染说明.md` |
| `app/pipeline/orchestrator.py` | 全链路编排、SSE、版本、打包 | 全链路 |
| `app/render/` | Plotly 图表、地图、报告拼装 | `docs/灾圈监测点风险研判_报告成稿模板.md` |
| `app/prompts/` | System/User prompt 模板 | `docs/灾圈监测点风险研判提示词.md` |
| `app/clients/` | ClickHouse / LLM 客户端 | `.env.example` |

## 测试

```powershell
pytest -q
python -m tests.smoke_offline
```

说明：地图导出依赖底图和 Kaleido 环境，内网或离线环境中可能触发地图渲染降级；报告生成主链路会保留数据局限说明并继续返回。

## 文档

设计文档集中在 `docs/`，是接口、Prompt、报告模板和前端集成契约的单一事实源。修改 schema、Prompt、报告章节或 A2UI 契约时，需要同步更新对应文档与 `docs/changelog.md`。
