"""A2UI 界面构建器：研判 JSON + 统计数据 → 6 种泛化基元组件列表。

基元类型（前后端协议）:
    card     — 标题 + 键值字段列表
    chart    — 图表， props.chartType: "pie" | "bar" | ...
    list     — 通用列表，支持 columns+rows 或 groups 两种模式
    map      — 空间地图（中心点 / 边界 / 聚类凸包 / 热力格）
    text     — Markdown / 纯文本段落
    image    — 静态图片嵌入

业务 → 基元映射由下方 SPECS 注册表定义，加组件只需追加一条 spec。
"""

from __future__ import annotations

from typing import Any, Callable

from app.api.schemas import A2uiComponent, A2uiSurface

# ── 类型别名 ──
PropsBuilder = Callable[[dict | None, dict, dict | None], dict | None]
"""接收 (judgement, stats, spatial) → 返回 props dict 或 None(跳过)"""


class ComponentSpec:
    __slots__ = ("id", "type", "build_props")

    def __init__(self, id: str, type: str, build_props: PropsBuilder):
        self.id = id
        self.type = type
        self.build_props = build_props


# ════════════════════════════════════════════════════════════════
# Props builder 工厂函数
# ════════════════════════════════════════════════════════════════

def _card(title: str, field_labels: list[tuple[str, str]], data: dict | None) -> dict | None:
    """data 非空时返回 {title, fields: [{label, value}]}。

    field_labels: [(展示名, 取值键), ...]，取值键来自 data。
    """
    if not data:
        return None
    fields: list[dict[str, str]] = []
    for label, key in field_labels:
        v = data.get(key)
        fields.append({"label": label, "value": str(v) if v is not None else "—"})
    return {"title": title, "fields": fields} if fields else None


def _pie_chart(title: str, type_dist: dict | None) -> dict | None:
    if not type_dist:
        return None
    data = [{"name": str(k), "value": int(v)} for k, v in type_dist.items() if int(v) > 0]
    if not data:
        return None
    return {"chartType": "pie", "title": title, "data": data}


def _bar_chart(title: str, ordered: dict | None, series_name: str = "监测点数") -> dict | None:
    if not ordered:
        return None
    cats = list(ordered.keys())
    vals = [int(ordered[k]) for k in cats]
    return {
        "chartType": "bar",
        "title": title,
        "categories": cats,
        "series": [{"name": series_name, "data": vals}],
    }


# ── 卡片 builders ──

def _build_risk_card(j: dict | None, s: dict, z: dict | None) -> dict | None:
    return _card("整体风险等级", [("等级", "level"), ("依据", "basis")],
                 j.get("overall_risk") if j else None)


def _build_hazard_card(j: dict | None, s: dict, z: dict | None) -> dict | None:
    if not j:
        return None
    h = j.get("dominant_hazard")
    if not h:
        return None
    fields = [
        {"label": "灾害类型", "value": str(h.get("type", ""))},
        {"label": "成因分析", "value": str(h.get("cause_analysis", ""))},
    ]
    if h.get("source_note"):
        fields.append({"label": "数据来源", "value": str(h["source_note"])})
    return {"title": "主要灾害类型", "fields": fields}


# ── 图表 builders ──

def _build_type_pie(j: dict | None, s: dict, z: dict | None) -> dict | None:
    return _pie_chart("灾害类型分布", s.get("type_distribution"))


def _build_scale_bar(j: dict | None, s: dict, z: dict | None) -> dict | None:
    return _bar_chart("规模分布", s.get("scale_distribution"))


def _build_warning_bar(j: dict | None, s: dict, z: dict | None) -> dict | None:
    return _bar_chart("预警等级分布", s.get("warning_level_distribution"))


def _build_hidden_pie(j: dict | None, s: dict, z: dict | None) -> dict | None:
    hidden = int(s.get("hidden_danger_count", 0))
    total = int(s.get("point_count", 0))
    if total <= 0:
        return None
    return {
        "chartType": "pie",
        "title": "隐患识别占比",
        "data": [
            {"name": "识别为隐患", "value": hidden},
            {"name": "非隐患", "value": total - hidden},
        ],
    }


def _build_threat_bar(j: dict | None, s: dict, z: dict | None) -> dict | None:
    pop = int(s.get("threaten_population_total", 0))
    res = int(s.get("threaten_residents_total", 0))
    assets = round(float(s.get("threaten_assets_total", 0)), 1)
    if not (pop or res or assets):
        return None
    return {
        "chartType": "bar",
        "title": "威胁要素汇总",
        "categories": ["威胁人数", "威胁户数", "威胁财产(万元)"],
        "series": [{"name": "合计", "data": [pop, res, assets]}],
    }


# ── 列表 builders ──

def _build_key_points(j: dict | None, s: dict, z: dict | None) -> dict | None:
    if not j:
        return None
    points = j.get("key_points")
    if not points:
        return None
    return {
        "columns": [
            {"key": "code", "label": "编号"},
            {"key": "reason", "label": "重点关注原因"},
            {"key": "suggestion", "label": "建议"},
        ],
        "rows": [
            {
                "code": str(p.get("monitor_point_code", "")),
                "reason": str(p.get("reason", "")),
                "suggestion": str(p.get("suggestion", "")),
            }
            for p in points
        ],
        "maxDisplay": 10,
    }


def _build_recommendations(j: dict | None, s: dict, z: dict | None) -> dict | None:
    if not j:
        return None
    recs = j.get("recommendations")
    if not recs:
        return None
    groups = []
    for key, label in [("urgent", "紧急措施"), ("near_term", "近期措施"), ("routine", "常规措施")]:
        items = recs.get(key)
        if items:
            groups.append({"label": label, "key": key, "items": list(items)})
    return {"groups": groups} if groups else None


# ── 地图 builder ──

def _build_map(j: dict | None, s: dict, z: dict | None) -> dict | None:
    if not z:
        return None
    center = z.get("map_center")
    if not center or not isinstance(center, (list, tuple)) or len(center) != 2:
        return None
    props: dict = {"center": [float(center[0]), float(center[1])]}
    boundary = z.get("zone_boundary_wgs84")
    if boundary:
        props["zoneBoundary"] = [[float(p[0]), float(p[1])] for p in boundary]
    hulls = z.get("cluster_hulls_wgs84")
    if hulls:
        props["clusterHulls"] = [[[float(p[0]), float(p[1])] for p in h] for h in hulls]
    hs = z.get("hotspot_grid")
    if hs and isinstance(hs, dict):
        props["hotspotGrid"] = {
            "lon": [float(v) for v in hs.get("lon", [])],
            "lat": [float(v) for v in hs.get("lat", [])],
            "z": [float(v) for v in hs.get("z", [])],
        }
    return props


# ── 文本 builder ──

def _build_text_limitations(j: dict | None, s: dict, z: dict | None) -> dict | None:
    if not j:
        return None
    limitations = j.get("data_limitations")
    if not limitations:
        return None
    if isinstance(limitations, list):
        content = "\n\n".join(f"- {str(item)}" for item in limitations)
    else:
        content = str(limitations)
    return {"content": content, "format": "markdown"}


# ════════════════════════════════════════════════════════════════
# Spec 注册表 — 添加新组件只需在此追加一条
# ════════════════════════════════════════════════════════════════

SPECS: list[ComponentSpec] = [
    ComponentSpec("risk_card", "card", _build_risk_card),
    ComponentSpec("hazard_card", "card", _build_hazard_card),
    ComponentSpec("chart_type_distribution", "chart", _build_type_pie),
    ComponentSpec("chart_scale_distribution", "chart", _build_scale_bar),
    ComponentSpec("chart_warning_distribution", "chart", _build_warning_bar),
    ComponentSpec("chart_hidden_danger_ratio", "chart", _build_hidden_pie),
    ComponentSpec("chart_threat_summary", "chart", _build_threat_bar),
    ComponentSpec("key_points", "list", _build_key_points),
    ComponentSpec("recommendations", "list", _build_recommendations),
    ComponentSpec("chart_map", "map", _build_map),
    ComponentSpec("text_limitations", "text", _build_text_limitations),
]


def build_risk_a2ui(
    report_id: str,
    judgement: dict,
    stats: dict,
    spatial: dict | None = None,
) -> A2uiSurface | None:
    """根据研判结果生成 A2UI 交互界面（6 种泛化基元）。

    遍历 SPECS 注册表，有数据则出组件，无数据自动跳过。
    """
    components: list[A2uiComponent] = []

    for spec in SPECS:
        props = spec.build_props(judgement, stats, spatial)
        if props is not None:
            components.append(A2uiComponent(id=spec.id, type=spec.type, props=props))

    if not components:
        return None

    return A2uiSurface(
        surfaceId=f"risk-{report_id}",
        components=components,
        dataModel={
            "report_id": report_id,
            "point_count": stats.get("point_count", 0),
        },
    )
