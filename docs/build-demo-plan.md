# A2UI 前端对接工作计划

## Summary

当前后端已经具备 A2UI 基础能力：`app/api/schemas.py` 定义了 `A2uiSurface` / `A2uiComponent` / `A2uiActionRequest`，`app/pipeline/a2ui_builder.py` 可把研判结果转成组件列表，`generate_risk_report_stream()` 已通过 SSE `a2ui` 事件下发组件。

前端对接主要要补齐三件事：消费 SSE `a2ui` 事件、按组件协议渲染 UI、把用户交互通过 `/api/v1/a2ui/action` 回传。后端还需要做一个小的契约补强：让最终 `done` 响应也带上 `a2ui`，避免前端只依赖中间事件。

## Key Changes

- 后端契约补强：
  - 在 `RiskReportResponse` 增加可选字段 `a2ui: A2uiSurface | null`。
  - `_render_response()` 内部生成并返回 `a2ui`，同步接口 `/api/v1/risk-report` 也可消费。
  - SSE 保留现有独立 `event: a2ui`，同时在最终 `event: done` payload 中也包含 `a2ui`。
  - 空结果 `point_count == 0` 时 `a2ui = null`，前端正常渲染空报告。

- 前端数据接入：
  - 使用 `POST /api/v1/risk-report/stream` 作为主路径，必须用 `fetch + ReadableStream` 解析 SSE，不能用 `EventSource`。
  - 处理事件：`stage` 更新进度，`reasoning/content` 更新模型输出，`validation/warn/error` 更新状态，`a2ui` 缓存并渲染结构化组件，`done` 渲染最终报告。
  - 所有后端返回的 `/static/...`、附件、bundle URL 都按 `API_BASE_URL` 拼成绝对地址。

- 前端 A2UI renderer：
  - `card`：渲染 `props.title` 和 `props.fields[{label,value}]`。
  - `chart`：按 `props.chartType` 渲染 `pie` / `bar`，数据直接来自 `data` 或 `categories + series`。
  - `list`：支持两种模式，`columns + rows` 表格模式，以及 `groups` 分组列表模式；`maxDisplay` 控制默认折叠。
  - `map`：消费 `center`、`zoneBoundary`、`clusterHulls`、`hotspotGrid`；demo 可先展示静态摘要或后端 `map_figure`，正式前端可接 MapLibre。
  - `text`：`format: "markdown"` 时按 Markdown 渲染。
  - `image`：`src` 统一转绝对 URL 后渲染。

- 前端交互回传：
  - 对需要交互的组件，例如重点点位列表、建议措施、地图点位，统一 POST `/api/v1/a2ui/action`。
  - 请求体使用现有 `A2uiActionRequest`：`report_id`、`surfaceId`、`action`、`componentId`、`payload`。
  - 当前后端只返回 ack，前端只需展示交互已接收；后续再扩展二次研判或报告刷新。

- 与对话流集成：
  - pi agent/模型负责输出 `[TRIGGER_GEO_UPLOAD]`。
  - 前端检测该标记后插入上传组件，上传 GeoJSON 后调用 GeoSafeAIStudio 的 SSE 研判接口。
  - 研判完成后，把 `a2ui` 作为结构化报告消息插入对话流，Markdown 报告作为详情/附录视图。

## Test Plan

- 后端验证：
  - 调用 `/api/v1/risk-report/stream`，确认事件流包含 `a2ui`，最终 `done` 也包含 `a2ui`。
  - 调用 `/api/v1/risk-report`，确认同步响应包含 `a2ui`。
  - 调用 `/api/v1/a2ui/action`，确认返回 `{status:"acknowledged"}`。
  - 空灾圈验证 `a2ui` 为 `null`。

- 前端验证：
  - 上传测试 GeoJSON 后，能看到进度、A2UI 结构化卡片/图表/列表/地图/文本、Markdown 报告和导出入口。
  - 断网或图件失败时，A2UI 结构化数据仍能展示，图件区域降级提示。
  - 点击重点点位或操作按钮时，能成功 POST `/a2ui/action`。
  - 跨域部署时，静态图件、附件、bundle 下载 URL 均能正常访问。

## Assumptions

- A2UI 协议以 `app/api/schemas.py` 为准，前端类型定义需要与其保持一致。
- 当前 A2UI 是扁平组件列表，不要求前端处理复杂嵌套布局。
- 本阶段只做展示和 ack 回传，不实现二次研判、报告局部刷新或复杂工作流状态机。
- 图表正式实现可接 ECharts，demo 可以先用轻量 HTML/CSS 或已有图件 PNG 降级展示。
