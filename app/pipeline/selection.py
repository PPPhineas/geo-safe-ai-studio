"""第 1 环:CH 空间筛选。

从 ClickHouse 取灾圈(多边形)范围内监测点,**筛选阶段即剔除 is_hex=1(已核销)**,
不进入后续任何统计(铁律 5,见 配套装配与渲染说明.md 一)。

拉回后在 Python 侧用 shapely 做点在多边形内精筛。坐标:库内/请求均为 WGS84 经纬度。
"""

from __future__ import annotations

from app.clients.clickhouse import ClickHouseClient

from shapely.geometry import Point, Polygon

from app.api.schemas import PolygonGeometry
from app.config import get_settings




def _polygon_bbox(geom: PolygonGeometry) -> tuple[float, float, float, float]:
    """多边形 → WGS84 外接 bbox (lon_min, lon_max, lat_min, lat_max)。"""
    lons = [c[0] for c in geom.coordinates]
    lats = [c[1] for c in geom.coordinates]
    return (min(lons), max(lons), min(lats), max(lats))


def select_points_in_zone(
    geometry: PolygonGeometry,
    client: ClickHouseClient | None = None,
) -> list[dict]:
    """返回灾圈(多边形)内有效监测点记录(原始字段,未清洗)。"""
    settings = get_settings()

    client = client or ClickHouseClient()

    lon_min, lon_max, lat_min, lat_max = _polygon_bbox(geometry)

    sql = (
        f"SELECT * FROM {settings.ch_table} "
        "WHERE is_hex = 0 "
        "AND longitude IS NOT NULL AND latitude IS NOT NULL "
        "AND toFloat64(longitude) BETWEEN {lon_min:Float64} AND {lon_max:Float64} "
        "AND toFloat64(latitude) BETWEEN {lat_min:Float64} AND {lat_max:Float64}"
    )
    candidates = client.query(
        sql,
        {"lon_min": lon_min, "lon_max": lon_max, "lat_min": lat_min, "lat_max": lat_max},
    )

    return _precise_filter(candidates, geometry)


def _precise_filter(candidates: list[dict], geometry: PolygonGeometry) -> list[dict]:
    """bbox 粗筛后的精确判断:点在多边形内(shapely,WGS84 经纬度)。"""
    polygon = Polygon(geometry.coordinates)
    kept: list[dict] = []
    for rec in candidates:
        try:
            lon, lat = float(rec["longitude"]), float(rec["latitude"])
        except (TypeError, ValueError):
            continue
        if polygon.covers(Point(lon, lat)):
            kept.append(rec)
    return kept
