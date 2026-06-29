# Changelog — A2UI 接入



## 2026-06-26 — CH 时序聚合下推：大规模多边形性能优化

**问题**：甘陕青三省（201 顶点，14,123 监测点，24 万传感器）多边形 API 请求超时 600s+。根因是原始数据拉取量过大（L3 单层 22k 传感器 × 30 天 × 96 条/天 ≈ 6400 万行，~12GB HTTP 传输）。

**方案**：将 daily 聚合（min/max/avg/sum）下推到 ClickHouse，Python 只收聚合结果。

**修改文件**:
- `app/pipeline/timeseries.py`：
  - 新增 `_build_daily_sql(level)`：按 `(SensorCode, toDate(Time))` 构造 daily 聚合 SQL，每指标计算 min/max/avg/sum。
  - 新增 `_query_level_rows_daily()`：使用 daily 聚合 SQL 执行分批查询，SQL 模板缓存于 `_DAILY_SQL_CACHE`。
  - 新增 `_explode_daily_observations()`：将聚合行展开为与原有 `_explode_observations` 兼容的 observation dict 列表。totalValue 每日期发两条（日 min + 日 max），下游窗口 max-min 自然正确；L3 value 用日 max（小时雨强）；其余指标用日 avg。
  - 新增 `_as_date()`：统一 CH Date/Datetime 类型转 `datetime.date`。
  - 新增 `_mk_daily_obs()`：构造 observation dict 的辅助函数。
  - `fetch_time_series_for_points()`：调用链路切换为 `_query_level_rows_daily` → `_explode_daily_observations`。
  - 修复 `from datetime import date`（原缺少 `date` 导入，导致 `datetime.date` 实例处理失败）。
- 保留原 `_query_level_rows` 和 `_explode_observations`（未删除，备用）。

**效果**:
- 甘陕青三省多边形（14,123 点）从 600s+ 超时降至 **283s** 成功完成。
- 58,636 个传感器 → 5,446,879 条观测 → 识别 3,334 个时序异常点位（含降雨诱因：403mm 大暴雨）。
- 数据传输量从 ~12GB 降至 ~200MB（~60x 缩减）。

**验证**:
- `pytest -q`：10 passed。
- `python -m tests.smoke_offline`：通过。
- API 实测：甘陕青三省 201 顶点多边形 200 OK，283s 完成。

---
## 2026-06-26 — 雨量分析增强：基于 mschema L3 雨量表字段完善趋势分析

**修改文件**:
- `app/config.py`：新增 `rain_intensity_moderate/heavy/storm/severe_storm` 雨强分级阈值（中国气象局标准）。
- `app/pipeline/trends.py`：
  - `_analyze_point_series`：分离雨量计与变形指标处理，雨量计不再通过 `_metric_summary`（避免无意义的变化率/加速比）；改用 `totalValue` 窗口差值（max-min）计算 24h/72h 雨量，`value` 间隔雨量累加作为回退；新增雨强分级（小雨/中雨/大雨/暴雨/大暴雨）、小时雨强峰值、逐日雨量序列；新增 `temp` 温度分析。
  - `_analyze_time_series_bundle`：新增 `rain_summary`/`rain_detail` 雨量专项汇总输出。
  - `analyze_deformation_trends`：透传 `time_series_rain_summary`/`time_series_rain_detail`。
- `app/pipeline/rain_deformation_coupling.py`：`_daily_series` 改用 `totalValue` 日差值计算日雨量，`value` 累加回退。
- `app/pipeline/assembly.py`：新增 `time_series_rain_summary`/`time_series_rain_detail` 占位符。
- `app/prompts/risk_judgement.py`：AI 研判输入第五部分新增"监测点位降雨实况"与"各监测点雨情节选"。

**关键发现**:
- `totalValue` 字段实测为持续累积值（不清零），非文档所述的"当日雨量累积值"；代码采用窗口内 max-min 差值校正。

**验证**:
- `pytest -q`：10 passed。
- `python -m tests.smoke_offline`：通过。

---

## 2026-06-23 — 专业增强分析：降雨-变形耦合、预警历史

**新增文件**:
- `app/pipeline/rain_deformation_coupling.py`：降雨-变形耦合分析，识别同步或滞后 1 天响应关系。
- `app/pipeline/warning_history.py`：预警历史分析，汇总近 N 天预警次数、最高等级、未关闭记录和误报标记。
- `tests/test_rain_deformation_coupling.py`：覆盖降雨-变形滞后响应识别。
- `tests/test_warning_history.py`：覆盖预警历史汇总。

**核心能力**:
- 降雨-变形耦合：按点位聚合雨量与累计位移/宏观位移日变化量，识别同步或滞后 1 天响应关系。
- 预警历史分析：查询近 `warning_history_lookback_days` 天预警记录，汇总预警次数、最高等级、未关闭记录和误报标记。
- 降级策略：CH 或时序数据不可用时不阻断报告生成，结果中写入局限说明。

**修改文件**:
- `app/config.py`：新增 `warning_history_lookback_days`。
- `app/pipeline/orchestrator.py`：报告生成链路接入专业增强分析；SSE 增加 `professional` 阶段提示。
- `app/pipeline/assembly.py`：新增 `rain_deformation_*`、`warning_history_*` 占位符。
- `app/prompts/risk_judgement.py`：AI 研判输入增加降雨-变形耦合、预警历史摘要。
- `app/render/report.py` 与 `docs/灾圈监测点风险研判_报告成稿模板.md`：第五章增加“专业增强分析”小节。
- `docs/灾圈监测点风险研判提示词.md`、`docs/灾圈监测点风险研判_配套装配与渲染说明.md`：同步占位符、分析方法和章节映射说明。

**验证**:
- `pytest -q`：11 passed。
- `python -m tests.smoke_offline`：通过；地图导出仍可能因内网瓦片环境触发 `KaleidoError: Map error`，属既有降级路径。

---

## 2026-06-23 — 趋势分析升级：时序接入、短期预测与分设备类型模型

**新增文件**:
- `app/pipeline/timeseries.py`：基于 `mschema` 建立时序监测数据接入框架，按“监测点名称 → 传感器 → L1/L2/L3/L4 数据”归一化观测。
- `app/pipeline/trends.py`：新增趋势分析模块，支持文本趋势识别、传感器时序异常识别、短期趋势预测。
- `tests/test_trends.py`：覆盖趋势词识别、设备模型识别、时序异常与短期预测。

**核心能力**:
- 文本趋势：从 `current_status` 识别“恶化/发展、稳定/趋稳、缓解/减弱、未填报”，处理“无明显变形”“停止发展”等否定/缓解边界。
- 时序接入：支持 L1 变形、L2 物理场、L3 雨量、L4 宏观现象数据，默认通过 `TREND_ENABLE_TIMESERIES=false` 关闭，避免无真实 CH 时序环境影响报告生成。
- 短期预测：基于近期位移/宏观位移变化率、加速倍率、24h/72h 雨量触发，输出未来 `trend_forecast_days` 天预测风险与预测变化量。
- 分设备类型模型：按 `sensor_type` / `sensor_type_name` 识别裂缝计、GNSS/地表位移、倾角计、加速度/振动、雨量计、声发射/次声/物理场、宏观现象等设备模型，并选择对应指标与分析逻辑。

**修改文件**:
- `app/config.py`：新增趋势时序与预测配置项，包括 `trend_enable_timeseries`、`trend_lookback_days`、`trend_forecast_days`、位移速率阈值、加速倍率阈值、24h/72h 雨量阈值。
- `app/pipeline/orchestrator.py`：在统计/空间分析后接入时序读取与趋势分析；SSE 增加 `timeseries` / `trend` 阶段提示。
- `app/pipeline/assembly.py`：将趋势摘要、时序异常点位、短期预测结果注入 prompt 和报告占位符，并把趋势异常纳入重点点位优先级。
- `app/prompts/risk_judgement.py`：发展趋势研判任务优先引用代码侧趋势识别、传感器时序趋势和短期趋势预测。
- `app/render/report.py` 与 `docs/灾圈监测点风险研判_报告成稿模板.md`：第五章增加代码侧趋势识别、传感器时序识别、短期趋势预测和中高预测风险点位。
- `docs/灾圈监测点风险研判提示词.md`、`docs/灾圈监测点风险研判_配套装配与渲染说明.md`：同步占位符、设备模型、指标和报告映射说明。

**验证**:
- `pytest -q`：8 passed。
- `python -m tests.smoke_offline`：通过；地图导出仍可能因内网瓦片环境触发 `KaleidoError: Map error`，属既有降级路径。

---

## 2026-06-18 — 新增企业级知识库构建方案

**新增文件**:
- `docs/企业级知识库构建_向量关键字检索与LLM-Wiki方案.md`

**变更说明**:
- 补充企业级知识库建设方案,覆盖向量检索、关键字检索、LLM Wiki、权限治理、审计、分阶段实施与测试场景。
- 明确默认落地边界:企业通用平台、私有化优先、LLM Wiki 作为受控派生层而非唯一事实源。

---

## 2025-06-13 — A2UI 组件泛化：Spec 注册表 + 6 种基元类型

**`app/pipeline/a2ui_builder.py`** 重写：
- 拆除硬编码的 7 种业务组件（`risk_card` / `hazard_card` / `key_points_list` / `recommendation_actions` / `chart_pie` / `chart_bar` / `chart_map`）
- 改为 **Spec 注册表模式**：`ComponentSpec(id, type, build_props)` + `SPECS` 列表，加组件只需追加一条 spec
- 组件类型泛化为 6 种基元：`card` / `chart` / `list` / `map` / `text` / `image`
- `chart` 类型通过 `props.chartType` 区分 `"pie"` / `"bar"` 等子类型
- `list` 类型统一支持 `columns+rows`（表格式）和 `groups`（分组式）两种模式
- 新增 `text`（Markdown 段落，如 data_limitations）和 `image` 基元
- 外部签名 `build_risk_a2ui(report_id, judgement, stats, spatial)` 不变

**`app/api/schemas.py`** — `A2uiComponent` docstring 补充 6 种泛化 type 约定

**pi-gui 前端对应同步（见 pi-gui-electron 仓库）**：
- `catalog/index.tsx`：注册 `card` / `chart` / `list` / `map` / `text` / `image`
- 新建 `Card.tsx` / `Chart.tsx` / `List.tsx` / `Text.tsx` / `Image.tsx`
- `ChartInline.tsx`：`matchChart` 由 `chart_pie|chart_bar` 改为 `chart` 类型匹配；新增 `a2ui:` 协议支持
- `ChartMap.tsx`：注册名由 `chart_map` 改为 `map`

---

## 2025-06-13 — A2UI 组件嵌入报告正文

**核心思路**：报告 Markdown 中发出 `![component_id](a2ui:component_id)` 引用，前端 `ChartInline.tsx` 拦截 `<img>` 标签，匹配组件后渲染为交互式 A2UI 组件，无匹配时降级显示静态内容。

**后端改动**：
- `app/render/report.py`：`repl` 新增 4 个 A2UI 占位符（`a2ui_risk_card` / `a2ui_key_points` / `a2ui_recommendations` / `a2ui_text_limitations`），替换为 `a2ui:` 伪协议 Markdown 图片引用
- `docs/灾圈监测点风险研判_报告成稿模板.md`：在第五章、六、七、八章对应位置插入 `{{a2ui_*}}` 占位符，补充索引与说明

**前端改动（pi-gui-electron）**：
- `lib/a2ui/ChartInline.tsx`：`matchChart` 新增 `a2ui:component_id` 精确匹配逻辑（剥离 `a2ui:` 前缀后按组件 id 查找，不限 chart 类型）
- `components/Markdown.tsx`：新增 `onA2uiAction` prop 透传，`img` 处理器对 `a2ui:` 前缀的 src 返回 null（不渲染破损 img）交由 A2UI 处理
- `panels/RiskPanel.tsx`：移除独立 `risk-a2ui` non-chart 区域和 `risk-gallery` 静态图廊，统一将完整 `a2uiSurface` + `onA2uiAction` 传给 `Markdown` 组件，由 `img` 拦截分发

**渲染流**：
```
Markdown `<img src="a2ui:risk_card">`
  → ChartInline.matchChart 按 "risk_card" 精确匹配
  → A2uiRenderer 渲染交互式 Card 组件
  → 无匹配 → 返回 null（不渲染破损 img 标签）
```

---

## 概述

新增 A2UI 交互界面产出能力。研判完成后，将 AI 研判 JSON 转为声明式 A2UI 组件列表，通过 SSE 流发给 pi-gui 前端渲染。同时新增 `POST /api/v1/a2ui/action` 端点接收前端用户操作回传。

**与 pi-gui 的契约**:
- SSE 事件名: `a2ui`，data 为完整 `A2uiSurface` JSON
- Action 回传: `POST /api/v1/a2ui/action`
- 组件类型（6 种泛化基元）: `card` / `chart` / `list` / `map` / `text` / `image`

---

## 新增文件

| 文件 | 说明 |
|---|---|
| `app/pipeline/a2ui_builder.py` | `build_risk_a2ui(report_id, judgement, stats, spatial)` — 研判 JSON + 统计数据 → A2UI 组件列表。图表 ID 约定等于占位符名（`chart_type_distribution` 等），前端自动匹配无需额外映射。包含 7 个组件：risk_card / hazard_card / key_points_list / recommendation_actions / chart_type_distribution(pie) / chart_scale_distribution(bar) / chart_warning_distribution(bar) / chart_hidden_danger_ratio(pie) / chart_threat_summary(bar) / chart_map。无有效数据返回 `None`。 |

## 修改文件

| 文件 | 改动 |
|---|---|
| `app/api/schemas.py` | 新增 `A2uiComponent` / `A2uiSurface` / `A2uiActionRequest` Pydantic 模型 |
| `app/pipeline/orchestrator.py` | 导入 `build_risk_a2ui`；`generate_risk_report_stream` 中研判校验后、渲染前插入 `yield _sse("a2ui", ...)`（含 spatial 参数）；两处 `get_region_maps()` 包裹 try-except，CH 不通时降级为空 maps |
| `app/api/routes.py` | 新增 `POST /api/v1/a2ui/action` → `handle_a2ui_action` 处理器 |
| `app/render/report.py` | 补全 5 个图件占位符映射：`chart_scale_distribution` / `chart_hidden_danger_ratio` / `chart_threat_summary`（原来只映射 3 个） |
| `docs/灾圈监测点风险研判_报告成稿模板.md` | 图表占位符散到各自小节：3.1→类型饼图、3.2→规模柱状图、3.3→预警柱状图、3.4→隐患饼图、3.5→威胁双轴图 |

## SSE 事件流（新增）

```
... (已有 stage / reasoning / content / validation 事件)
    ↓
event: a2ui
data: {"surfaceId":"risk-ab12cd34","components":[...],"dataModel":{...}}
    ↓
event: stage (render)
event: done
```

## Action 端点

```
POST /api/v1/a2ui/action
{
  "report_id": "ab12cd34",
  "surfaceId": "risk-ab12cd34",
  "action": "click_detail",
  "componentId": "key_points",
  "payload": { "monitor_point_code": "MP001", "index": 0 }
}
→ 200 {"status": "acknowledged", "report_id": "ab12cd34", "action": "click_detail"}
```

---

## CH 模拟数据支持

开发/演示阶段无需 CH 连接，用 CSV 文件替代 ClickHouse 数据源。

| 文件 | 改动 |
|---|---|
| `app/config.py` | Settings 新增 `ch_mock_csv` 字段（默认空，非空时启用 mock 模式） |
| `app/pipeline/selection.py` | 新增 `_load_mock_csv()` 函数；`select_points_in_zone` 在 mock 模式下从 CSV 加载 + bbox 粗筛 + shapely 精筛；`ClickHouseClient` import 移入函数内部 |
| `app/pipeline/regions.py` | `ClickHouseClient` import 移入 `get_region_maps()` 函数内部，避免模块级加载 |
| `app/pipeline/orchestrator.py` | `get_region_maps()` 调用包裹 try-except，CH 不通时降级为空 maps |
| `.env` | 配置 `CH_MOCK_CSV=示例\figures\monitor_points.csv` |
| `.env.example` | 文档化 `CH_MOCK_CSV` 配置项 |

**Mock 模式逻辑**：
1. 从 CSV 加载全部记录（~14000 条），跳过脏点 (0,0) 和 `is_hidden_danger=1`
2. 按请求灾圈的 bbox 粗筛
3. shapely `polygon.covers()` 精筛
4. 返回的记录结构与 CH 查询一致，链路后续各环（cleaning/statistics/spatial/assembly/judgement）不受影响

**已知问题修复**：
- CSV BOM 导致第一列名变为 `\ufeffmonitor_point_code`，下游 `KeyError`。修复：`_load_mock_csv` 打开文件时用 `encoding="utf-8-sig"` 自动剥离 BOM。
- `clickhouse-connect` HTTP driver 异常：`selection.py` 和 `regions.py` 中 `ClickHouseClient` import 移入函数内部（仅非 mock 路径/`get_region_maps` 内触发），避免模块级加载 driver 冲突。
