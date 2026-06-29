"""坐标系工具。

投影坐标系铁律:DBSCAN/缓冲/面积/距离须在投影坐标系(米)下做。
为适配全国分布(数据可能跨多个 3 度带),支持 PROJECTED_CRS=auto:
按灾圈中心经纬度就近取 UTM 带,避免固定单一带在远离中央经线处的尺度畸变。
"""

from __future__ import annotations


def resolve_projected_crs(crs: str, lon: float, lat: float) -> str:
    """解析投影 CRS:非 'auto' 原样返回;'auto' 时按中心点就近取 UTM 带。"""
    if crs and crs.strip().lower() != "auto":
        return crs
    zone = int((lon + 180) / 6) % 60 + 1
    epsg_base = 32600 if lat >= 0 else 32700  # WGS84 / UTM N or S
    return f"EPSG:{epsg_base + zone}"
