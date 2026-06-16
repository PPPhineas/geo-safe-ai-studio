"""第 1 环:CH 空间筛选。

从 ClickHouse 取灾圈(多边形)范围内监测点,**筛选阶段即剔除 is_hex=1(已核销)**,
不进入后续任何统计(铁律 5,见 配套装配与渲染说明.md 一)。

如果配置了 ch_mock_csv,则从 CSV 加载替代 CH 查询(开发/演示阶段)。
策略:SQL 侧用经纬度 bbox 粗筛(库内坐标为 NULLABLE(DECIMAL),用 toFloat64 防混型),
拉回后在 Python 侧用 shapely 做点在多边形内精筛。坐标:库内/请求均为 WGS84 经纬度。
"""

from __future__ import annotations

import csv
from pathlib import Path

from shapely.geometry import Point, Polygon

from app.api.schemas import PolygonGeometry
from app.config import get_settings


def _load_mock_csv(path: str) -> list[dict]:
    """从 CSV 加载模拟监测点数据，跳过脏点 (0,0 附近) 和 is_hex=1 的记录。"""
    records: list[dict] = []
    with Path(path).open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lon, lat = float(row.get("longitude", "")), float(row.get("latitude", ""))
            except (TypeError, ValueError):
                continue
            # 跳过脏点
            if abs(lon) < 0.1 and abs(lat) < 0.1:
                continue
            # 跳过已核销
            if str(row.get("is_hidden_danger", "0")).strip() == "1":
                continue
            records.append(row)
    return records


def _polygon_bbox(geom: PolygonGeometry) -> tuple[float, float, float, float]:
    """多边形 → WGS84 外接 bbox (lon_min, lon_max, lat_min, lat_max)。"""
    lons = [c[0] for c in geom.coordinates]
    lats = [c[1] for c in geom.coordinates]
    return (min(lons), max(lons), min(lats), max(lats))


def select_points_in_zone(
    geometry: PolygonGeometry,
    client: ClickHouseClient | None = None,
) -> list[dict]:
    """返回灾圈(多边形)内有效监测点记录(原始字段,未清洗)。

    如果配置了 ch_mock_csv,从 CSV 加载 + 空间筛选替代 CH 查询。
    """
    settings = get_settings()

    # 模拟模式：从 CSV 加载替代 CH 查询
    if settings.ch_mock_csv:
        all_records = _load_mock_csv(settings.ch_mock_csv)
        lon_min, lon_max, lat_min, lat_max = _polygon_bbox(geometry)
        candidates = [
            r for r in all_records
            if lon_min <= float(r.get("longitude", 0)) <= lon_max
            and lat_min <= float(r.get("latitude", 0)) <= lat_max
        ]
        return _precise_filter(candidates, geometry)

    from app.clients.clickhouse import ClickHouseClient  # noqa: PLC0415  仅非 mock 时才加载

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
