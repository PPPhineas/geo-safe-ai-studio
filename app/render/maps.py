"""报告第四章「空间分布图」(Plotly + kaleido)。

要点(见 docs/空间分析内容与技术栈.md):
    - 图层自下而上:底图 → 影响范围 → 热点 → 连片带 → 灾圈边界 → 点位(点位置顶);
    - go.Scattermap / go.Densitymap(MapLibre),底图 style="open-street-map"(免 token);
    - 复用 spatial 算好的 WGS84 几何(不重算);
    - 点位颜色编预警、大小编规模、按类型分 trace、hover 显 monitor_point_code;
    - ⚠️ 静态导出需联网拉瓦片,内网无外网底图会空白(几何仍在)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app.api.schemas import PolygonGeometry
from app.config import get_settings
from app.render.charts import WARNING_COLORS

_SCALE_SIZE = {"小": 8, "中": 12, "大": 16, "特大": 21, "未分级": 10}


def _zoom_for(df: pd.DataFrame) -> float:
    span = max(
        float(df["longitude"].max() - df["longitude"].min()),
        float(df["latitude"].max() - df["latitude"].min()),
        1e-4,
    )
    for threshold, zoom in ((0.02, 13), (0.05, 12), (0.1, 11), (0.3, 10), (1.0, 8)):
        if span <= threshold:
            return zoom
    return 7


def render_map(
    spatial: dict,
    df: pd.DataFrame,
    geometry: PolygonGeometry,
) -> bytes:
    """渲染空间分布图,返回 PNG 字节。"""
    settings = get_settings()
    fig = go.Figure()

    # ① 影响范围
    extent = spatial.get("extent_polygon_wgs84")
    if extent:
        fig.add_trace(go.Scattermap(
            lon=[p[0] for p in extent], lat=[p[1] for p in extent],
            mode="lines", fill="toself", fillcolor="rgba(31,119,180,0.10)",
            line=dict(color="rgba(31,119,180,0.5)", width=1), name="影响范围", hoverinfo="skip",
        ))

    # ② 热点核密度
    grid = spatial.get("hotspot_grid")
    if grid:
        fig.add_trace(go.Densitymap(
            lon=grid["lon"], lat=grid["lat"], z=grid["z"],
            radius=18, opacity=0.45, colorscale="YlOrRd", showscale=False, name="风险热点",
        ))

    # ③ 连片带
    for i, hull in enumerate(spatial.get("cluster_hulls_wgs84", []), 1):
        fig.add_trace(go.Scattermap(
            lon=[p[0] for p in hull], lat=[p[1] for p in hull],
            mode="lines", fill="toself", fillcolor="rgba(214,39,40,0.12)",
            line=dict(color="rgba(214,39,40,0.7)", width=2), name=f"连片带{i}", hoverinfo="skip",
        ))

    # ④ 灾圈边界
    boundary = spatial.get("zone_boundary_wgs84")
    if boundary:
        fig.add_trace(go.Scattermap(
            lon=[p[0] for p in boundary], lat=[p[1] for p in boundary],
            mode="lines", line=dict(color="#333", width=2), name="灾圈边界", hoverinfo="skip",
        ))

    # ⑤ 点位(置顶):按类型分 trace,颜色编预警、大小编规模
    for ptype, sub in df.groupby("monitor_point_type"):
        fig.add_trace(go.Scattermap(
            lon=sub["longitude"].tolist(), lat=sub["latitude"].tolist(), mode="markers",
            marker=dict(
                size=[_SCALE_SIZE.get(s, 10) for s in sub["scale"]],
                color=[WARNING_COLORS.get(w, "#9aa0a6") for w in sub["warning_level"]],
            ),
            text=[f"{c} {n}<br>{w} | {s}"
                  for c, n, w, s in zip(sub["monitor_point_code"], sub["monitor_point_name"],
                                        sub["warning_level"], sub["scale"])],
            hoverinfo="text", name=str(ptype),
        ))

    center_lon, center_lat = spatial.get("map_center", (float(df["longitude"].mean()), float(df["latitude"].mean())))
    fig.update_layout(
        map=dict(style="open-street-map", center=dict(lon=center_lon, lat=center_lat), zoom=_zoom_for(df)),
        font=dict(family=settings.chart_font_family, size=13),
        margin=dict(l=0, r=0, t=40, b=0),
        title="四、空间分布图（监测点 / 连片带 / 热点 / 影响范围）",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor="rgba(255,255,255,0.7)"),
    )
    return fig.to_image(format="png", scale=settings.export_scale, width=900, height=680)
