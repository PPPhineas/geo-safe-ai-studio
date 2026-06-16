"""由 monitor_point_code 反推省市县。

monitor_point_code 前 6 位 = GB/T 2260 行政区划代码(= county_code):
    省 = 前2位 + "0000"，市 = 前4位 + "00"，县 = 前6位。
对照表从库内自身 DISTINCT 各级 code→name 构建;富集时**库字段优先**、缺失再由 code 反推补全。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import pandas as pd

_NON_DIGIT = re.compile(r"\D")


@dataclass(frozen=True)
class RegionMaps:
    """各级 行政区划码 → 名称 对照表。"""

    province: dict[str, str] = field(default_factory=dict)
    city: dict[str, str] = field(default_factory=dict)
    county: dict[str, str] = field(default_factory=dict)


_EMPTY = RegionMaps()


def _put(d: dict[str, str], code, name) -> None:
    code_s = str(code).strip() if code is not None else ""
    name_s = str(name).strip() if name is not None else ""
    if code_s and name_s:
        d.setdefault(code_s, name_s)


@lru_cache(maxsize=1)
def get_region_maps() -> RegionMaps:
    """从库内 DISTINCT 各级 code→name 构建对照表(进程级缓存)。"""
    from app.clients.clickhouse import ClickHouseClient  # noqa: PLC0415

    client = ClickHouseClient()
    rows = client.query(
        "SELECT DISTINCT province_code, province_name, city_code, city_name, "
        f"county_code, county_name FROM {client.settings.ch_table} WHERE is_hex=0"
    )
    province: dict[str, str] = {}
    city: dict[str, str] = {}
    county: dict[str, str] = {}
    for r in rows:
        _put(province, r.get("province_code"), r.get("province_name"))
        _put(city, r.get("city_code"), r.get("city_name"))
        _put(county, r.get("county_code"), r.get("county_name"))
    return RegionMaps(province, city, county)


def region_from_code(code, maps: RegionMaps) -> tuple[str | None, str | None, str | None]:
    """前6位行政区划码 → (省, 市, 县) 名称;非数字(如脏 __ 前缀)先剥离。不足6位返回三个 None。"""
    digits = _NON_DIGIT.sub("", str(code or ""))
    if len(digits) < 6:
        return (None, None, None)
    return (
        maps.province.get(digits[:2] + "0000"),
        maps.city.get(digits[:4] + "00"),
        maps.county.get(digits[:6]),
    )


def enrich_regions(df: pd.DataFrame, maps: RegionMaps | None = None) -> pd.DataFrame:
    """填补省市县三列:库字段优先 → code 反推补全 → 仍无则「未知」。保证三列存在。

    maps=None 时只用库字段(供离线测试,不连 CH)。
    """
    maps = maps or _EMPTY
    if df.empty:
        for col in ("province_name", "city_name", "county_name"):
            if col not in df.columns:
                df[col] = []
        return df

    def cell(v) -> str:
        return str(v).strip() if v is not None and not pd.isna(v) else ""

    prov: list[str] = []
    city: list[str] = []
    county: list[str] = []
    for _, row in df.iterrows():
        dp, dc, dx = region_from_code(row.get("monitor_point_code"), maps)
        prov.append(cell(row.get("province_name")) or dp or "未知")
        city.append(cell(row.get("city_name")) or dc or "未知")
        county.append(cell(row.get("county_name")) or dx or "未知")
    df["province_name"] = prov
    df["city_name"] = city
    df["county_name"] = county
    return df
