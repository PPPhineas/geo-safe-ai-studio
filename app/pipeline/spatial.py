"""第 4 环:GeoPandas 空间分析(既定事实)。

「分析归分析、渲染归 Plotly」:此处只做计算几何,产出几何 + 文字摘要;出图在 render/maps.py。
空间分析**算一次**,结果既喂 AI 研判(占位符),又用于出图(见 空间分析内容与技术栈.md 五)。

坐标系铁律:DBSCAN/缓冲/面积/距离须在投影坐标系(米)下做(config.projected_crs);
渲染再转回 WGS84 经纬度交 Plotly。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import MultiPoint, Polygon
from sklearn.cluster import DBSCAN

from app.api.schemas import PolygonGeometry
from app.config import get_settings
from app.geoutil import resolve_projected_crs

try:
    import alphashape  # noqa: F401

    _HAS_ALPHASHAPE = True
except Exception:  # pragma: no cover
    _HAS_ALPHASHAPE = False


def _fmt_area(area_m2: float) -> str:
    if area_m2 >= 1_000_000:
        return f"{area_m2 / 1_000_000:.2f} km²"
    return f"{area_m2:.0f} m²"


_CLUSTER_SUMMARY_MAX = 8   # 摘要最多列出的连片带数(其余进附件)
_CLUSTER_CODES_MAX = 25    # 每带摘要最多列出的成员编号数


def _cluster_summary_text(clusters: list[dict], eps_m: float, min_samples: int) -> str:
    """连片带文字摘要(有界):头部 + Top-K 带 + 每带成员编号截断。喂 prompt/章四,不随带数膨胀。"""
    total = len(clusters)
    pts = sum(c["member_count"] for c in clusters)
    head = (
        f"识别出 {total} 个连片带(DBSCAN,eps={eps_m:.0f}m,min_samples={min_samples}),"
        f"涉及 {pts} 个点位"
    )
    lines = []
    for c in clusters[:_CLUSTER_SUMMARY_MAX]:
        codes = c["codes"]
        shown = ", ".join(codes[:_CLUSTER_CODES_MAX])
        more = f"…等{len(codes)}个" if len(codes) > _CLUSTER_CODES_MAX else ""
        lines.append(f"带{c['cluster_id']}({c['member_count']}点):[{shown}{more}]")
    text = head + ";" + ";".join(lines)
    if total > _CLUSTER_SUMMARY_MAX:
        text += f";其余 {total - _CLUSTER_SUMMARY_MAX} 个连片带从略"
    return text


def analyze_spatial(
    df: pd.DataFrame,
    geometry: PolygonGeometry,
) -> dict:
    """空间分析:连片带 / 热点 / 影响范围。

    Returns:
        含文字摘要(cluster_summary/hotspot_summary/affected_extent_summary、
        zone_geometry_desc、zone_area)与供渲染复用的 WGS84 几何 / 簇标签。
    """
    settings = get_settings()
    clon = sum(c[0] for c in geometry.coordinates) / len(geometry.coordinates)
    clat = sum(c[1] for c in geometry.coordinates) / len(geometry.coordinates)
    crs = resolve_projected_crs(settings.projected_crs, clon, clat)
    fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inv = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    lons = df["longitude"].to_numpy(dtype=float)
    lats = df["latitude"].to_numpy(dtype=float)
    codes = df["monitor_point_code"].astype(str).tolist()
    px, py = fwd.transform(lons, lats)
    px = np.asarray(px, dtype=float)
    py = np.asarray(py, dtype=float)
    xy = np.column_stack([px, py])
    n = len(df)

    result: dict = {}

    # ---- 灾圈几何描述 + 面积 + 边界(WGS84)----
    proj_poly = Polygon([fwd.transform(lo, la) for lo, la in geometry.coordinates])
    area_m2 = proj_poly.area
    result["zone_geometry_desc"] = (
        f"{len(geometry.coordinates)} 顶点多边形,外接经度 "
        f"[{min(c[0] for c in geometry.coordinates):.4f}, {max(c[0] for c in geometry.coordinates):.4f}]"
    )
    ring = list(geometry.coordinates)
    if ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    result["zone_boundary_wgs84"] = [(float(lo), float(la)) for lo, la in ring]
    result["map_center"] = (clon, clat)
    result["zone_area"] = _fmt_area(area_m2)

    # ---- DBSCAN 连片带 ----
    labels = DBSCAN(
        eps=settings.dbscan_eps_m, min_samples=settings.dbscan_min_samples
    ).fit_predict(xy)
    result["cluster_labels"] = labels.tolist()

    cluster_hulls_wgs84: list[list[tuple[float, float]]] = []
    clusters_detail: list[dict] = []
    cluster_ids = sorted(set(int(c) for c in labels if c >= 0))
    for cid in cluster_ids:
        idx = np.where(labels == cid)[0]
        member_codes = [codes[i] for i in idx]
        hull = MultiPoint([(px[i], py[i]) for i in idx]).convex_hull
        if isinstance(hull, Polygon):
            hull_wgs = [
                (float(lo), float(la))
                for lo, la in (inv.transform(x, y) for x, y in hull.exterior.coords)
            ]
            cluster_hulls_wgs84.append(hull_wgs)
        clusters_detail.append(
            {"cluster_id": cid + 1, "member_count": len(idx), "codes": member_codes}
        )
    result["cluster_hulls_wgs84"] = cluster_hulls_wgs84
    clusters_detail.sort(key=lambda c: c["member_count"], reverse=True)  # 规模降序
    result["clusters_detail"] = clusters_detail
    result["cluster_count"] = len(clusters_detail)
    result["clustered_point_count"] = int(sum(c["member_count"] for c in clusters_detail))
    # 摘要无法完整呈现(带数超上限,或某带成员超上限)→ 标记需转附件
    result["cluster_summary_truncated"] = bool(clusters_detail) and (
        len(clusters_detail) > _CLUSTER_SUMMARY_MAX
        or any(c["member_count"] > _CLUSTER_CODES_MAX for c in clusters_detail)
    )

    if clusters_detail:
        result["cluster_summary"] = _cluster_summary_text(
            clusters_detail, settings.dbscan_eps_m, settings.dbscan_min_samples
        )
    else:
        result["cluster_summary"] = (
            "未识别出明显连片带(点位分散或样本不足，每带需≥%d 点)" % settings.dbscan_min_samples
        )

    # ---- KDE 核密度热点 ----
    result["hotspot_grid"] = None
    if n >= 3 and np.unique(xy, axis=0).shape[0] >= 3:
        try:
            from scipy.stats import gaussian_kde

            kde = gaussian_kde(np.vstack([px, py]))
            gx = np.linspace(px.min(), px.max(), 40)
            gy = np.linspace(py.min(), py.max(), 40)
            mx, my = np.meshgrid(gx, gy)
            dens = kde(np.vstack([mx.ravel(), my.ravel()]))
            glon, glat = inv.transform(mx.ravel(), my.ravel())
            result["hotspot_grid"] = {
                "lon": np.asarray(glon, dtype=float).tolist(),
                "lat": np.asarray(glat, dtype=float).tolist(),
                "z": dens.tolist(),
            }
            # 峰值位置 + 邻近点位
            peak = int(np.argmax(dens))
            peak_x, peak_y = mx.ravel()[peak], my.ravel()[peak]
            dist = np.hypot(px - peak_x, py - peak_y)
            near = [codes[i] for i in np.argsort(dist)[: min(3, n)]]
            peak_lon, peak_lat = inv.transform(peak_x, peak_y)
            result["hotspot_summary"] = (
                f"核密度高值区位于 ({float(peak_lon):.6f}, {float(peak_lat):.6f}) 附近,"
                f"邻近点位:[{', '.join(near)}]"
            )
        except Exception as exc:  # 协方差奇异等
            result["hotspot_summary"] = f"核密度热点分析未完成({type(exc).__name__});点位分布退化或样本不足"
    else:
        result["hotspot_summary"] = "点位过少(<3),未做核密度热点分析"

    # ---- 影响范围:alpha-shape / 凸包 ----
    result["extent_polygon_wgs84"] = None
    if n >= 3:
        extent_proj = None
        if _HAS_ALPHASHAPE and n >= 4:
            try:
                import alphashape

                shp = alphashape.alphashape([(x, y) for x, y in xy], 0.0)
                if isinstance(shp, Polygon) and shp.area > 0:
                    extent_proj = shp
            except Exception:
                extent_proj = None
        if extent_proj is None:
            hull = MultiPoint([(x, y) for x, y in xy]).convex_hull
            extent_proj = hull if isinstance(hull, Polygon) else None
        if extent_proj is not None:
            result["extent_polygon_wgs84"] = [
                (float(lo), float(la))
                for lo, la in (inv.transform(x, y) for x, y in extent_proj.exterior.coords)
            ]
            result["affected_extent_summary"] = (
                f"圈内点集影响范围约 {_fmt_area(extent_proj.area)}"
                f"({'alpha-shape' if _HAS_ALPHASHAPE and n >= 4 else '凸包'}近似)"
            )
        else:
            result["affected_extent_summary"] = "点位共线或退化,影响范围按点位邻域估计"
    else:
        result["affected_extent_summary"] = "点位过少(<3),影响范围按单点缓冲估计"

    return result
