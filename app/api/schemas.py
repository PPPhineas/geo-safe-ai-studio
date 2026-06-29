"""接口请求/响应模型(Pydantic)。

灾圈几何为多边形(见 配套装配与渲染说明.md 二「zone_geometry_desc」):
    - 多边形:顶点经纬度列表
坐标按 WGS84 经纬度传入;后端分析阶段再转投影坐标系(见 config.projected_crs)。

A2UI 交互界面模型见文件末尾(见 pi-gui src/lib/a2ui/types.ts)。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PolygonGeometry(BaseModel):
    """多边形灾圈。"""

    kind: Literal["polygon"] = "polygon"
    coordinates: list[tuple[float, float]] = Field(
        ..., min_length=3, description="顶点 (lon, lat) 列表(WGS84)"
    )


class RiskReportRequest(BaseModel):
    """风险报告生成请求。"""

    geometry: PolygonGeometry = Field(...)
    report_id: str | None = Field(default=None, description="可选:外部报告编号")


class RiskReportResponse(BaseModel):
    """风险报告生成响应。"""

    report_id: str
    point_count: int = Field(..., description="圈内有效监测点数(已剔除 is_hex=1)")
    report_markdown: str = Field(..., description="渲染后的报告正文(成稿模板拼装)")
    judgement: dict = Field(default_factory=dict, description="AI 研判 JSON(已通过校验)")
    # 图件以独立资源返回或外链
    figures: dict[str, str] = Field(default_factory=dict, description="图件标识 → 资源地址")
    # 附件(如点位过多时的完整监测点清单 CSV):文件名 → 资源地址
    attachments: dict[str, str] = Field(default_factory=dict, description="附件名 → 资源地址")


class ReportAnnotationInput(BaseModel):
    """报告段落批注输入。"""

    block_id: str = Field(..., min_length=1, description="前端生成的块级锚点")
    block_text: str = Field(..., min_length=1, description="被批注段落原文")
    comment: str = Field(..., min_length=1, description="用户批注意见")


class RiskReportReviseRequest(BaseModel):
    """报告二次修订请求。"""

    base_version_id: str = Field(..., min_length=1, description="作为修订基准的版本 ID")
    annotations: list[ReportAnnotationInput] = Field(
        ..., min_length=1, description="待应用的段落批注列表"
    )
    mode: Literal["full_markdown"] = Field(
        default="full_markdown", description="修订模式；当前仅支持返回完整 Markdown"
    )


class ReportVersion(BaseModel):
    """报告版本元数据。"""

    version_id: str
    version: int
    created_at: str
    source: Literal["initial", "revision"]
    figures: dict[str, str] = Field(default_factory=dict)
    attachments: dict[str, str] = Field(default_factory=dict)
    change_summary: list[str] = Field(default_factory=list)


class RiskReportVersionContent(BaseModel):
    """报告版本正文与资源。"""

    version_id: str
    version: int
    report_markdown: str
    figures: dict[str, str] = Field(default_factory=dict)
    attachments: dict[str, str] = Field(default_factory=dict)


class RiskReportDetailResponse(BaseModel):
    """报告版本详情响应。"""

    report_id: str
    current_version: int
    versions: list[ReportVersion]
    current: RiskReportVersionContent


class RiskReportReviseResponse(BaseModel):
    """报告二次修订响应。"""

    report_id: str
    version_id: str
    version: int
    report_markdown: str
    figures: dict[str, str] = Field(default_factory=dict)
    attachments: dict[str, str] = Field(default_factory=dict)
    change_summary: list[str] = Field(default_factory=list)


# ── A2UI 交互界面(Pydantic 模型与 pi-gui src/lib/a2ui/types.ts 契约对齐) ──


class A2uiComponent(BaseModel):
    """A2UI 组件描述（扁平组件列表项）。

    泛化 type 约定（前后端契约）:
        card     — 标题 + 键值字段列表, props: {title?, fields: [{label, value}]}
        chart    — 图表, props: {chartType, title, ...ECharts option}
        list     — 通用列表, props: {columns?, rows, groups?, maxDisplay?}
        map      — 空间地图, props: {center, zoneBoundary?, clusterHulls?, hotspotGrid?}
        text     — Markdown/纯文本, props: {content, format?}
        image    — 静态图片, props: {src, alt?, width?}
    """

    id: str = Field(..., description="组件唯一标识")
    type: str = Field(..., description="组件类型（card / chart / list / map / text / image）")
    children: list[str] | None = Field(default=None, description="子组件 id 列表")
    props: dict | None = Field(default=None, description="组件属性")


class A2uiSurface(BaseModel):
    """一次完整的 A2UI 界面意图。"""

    surfaceId: str = Field(..., description="surface 标识")
    components: list[A2uiComponent] = Field(..., description="扁平组件列表")
    dataModel: dict | None = Field(default=None, description="共享数据模型")


class A2uiActionRequest(BaseModel):
    """前端 A2UI 交互操作回传。"""

    report_id: str = Field(..., description="报告编号")
    surfaceId: str = Field(..., description="操作所在的 surface")
    action: str = Field(..., description="动作类型：click_detail / mark_done 等")
    componentId: str = Field(..., description="触发操作的组件 id")
    payload: dict | None = Field(default=None, description="附加数据")
