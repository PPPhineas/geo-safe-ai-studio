# Changelog — A2UI 接入

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
