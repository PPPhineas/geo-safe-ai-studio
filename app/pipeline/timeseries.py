"""时序监测数据接入框架。

基于 `mschema` 的当前结构，监测点与时序数据的关联链路为：

    dwd_monitor_point_info_view.monitor_point_name
    -> dwd_monitor_sensor_info_view.monitor_point_name / sensor_code / sensor_type
    -> ods_gh_v1.datapointsL1/L2/L3/L4.SensorCode

注意：传感器表未暴露 monitor_point_code，因此这里用监测点名称做桥接；若后续表结构补齐
点位编号，应优先改为 monitor_point_code 关联。
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from app.clients.clickhouse import ClickHouseClient
from app.config import get_settings

SENSOR_TABLE = "dwd_gh_v1.dwd_monitor_sensor_info_view"

TIME_SERIES_TABLES: dict[str, dict[str, Any]] = {
    "L1": {
        "table": "ods_gh_v1.datapointsL1",
        "metrics": (
            "value",
            "gpsTotalX",
            "gpsTotalY",
            "gpsTotalZ",
            "dispsX",
            "dispsY",
            "gX",
            "gY",
            "gZ",
            "X",
            "Y",
            "Z",
            "angle",
            "PLX",
            "PLY",
            "PLZ",
            "SJX",
            "SJY",
            "SJZ",
            "SJValue",
        ),
        "kind": "deformation",
    },
    "L2": {
        "table": "ods_gh_v1.datapointsL2",
        "metrics": ("value", "OSP", "VSP", "freq", "amplitude", "energy", "ringing", "RMS", "ASL"),
        "kind": "physical",
    },
    "L3": {
        "table": "ods_gh_v1.datapointsL3",
        "metrics": ("value", "totalValue", "temp"),
        "kind": "rainfall",
    },
    "L4": {
        "table": "ods_gh_v1.datapointsL4",
        "metrics": ("value", "x", "y", "speed"),
        "kind": "macro",
    },
}


def _point_name_map(df: pd.DataFrame) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = defaultdict(list)
    if "monitor_point_name" not in df.columns:
        return {}
    for _, row in df.iterrows():
        name = str(row.get("monitor_point_name", "")).strip()
        code = str(row.get("monitor_point_code", "")).strip()
        if name and code:
            mapping[name].append(code)
    return dict(mapping)



def _sensor_level(sensor_type: str | None) -> str | None:
    text = str(sensor_type or "").upper()
    for level in TIME_SERIES_TABLES:
        if text.startswith(level + "_") or text == level:
            return level
    return None


def classify_device_model(sensor_type: str | None, sensor_type_name: str | None = None) -> str:
    """按传感器编码/中文名识别分析模型。

    编码规则未在 schema 中完全展开，因此优先使用中文名关键词，编码作为兜底。
    """
    code = str(sensor_type or "").upper()
    name = str(sensor_type_name or "")
    text = f"{code} {name}"
    if "雨量" in name or "_YL_" in code:
        return "rain_gauge"
    if "裂缝" in name or "_LF_" in code:
        return "crack_meter"
    if "GNSS" in text or "GPS" in text or "地表位移" in name:
        return "gnss_displacement"
    if "倾角" in name or "_QJ_" in code:
        return "tilt_meter"
    if "加速度" in name or "振动" in name or "_JS_" in code or "_ZD_" in code:
        return "accelerometer"
    if "声发射" in name or "次声" in name:
        return "acoustic"
    if "宏观" in name or code.startswith("L4"):
        return "macro_observation"
    if code.startswith("L2"):
        return "physical_field"
    if code.startswith("L1"):
        return "deformation_generic"
    if code.startswith("L3"):
        return "rain_gauge"
    return "unknown"


_SENSOR_BATCH = 2000  # IN 子句每批最大名称数
_LEVEL_BATCH = 5000   # 每批最大 sensor_code 数


def _query_sensors(client: ClickHouseClient, point_names: list[str]) -> list[dict]:
    if not point_names:
        return []
    sql = (
        f"SELECT sensor_code, sensor_type, sensor_type_name, monitor_point_name "
        f"FROM {SENSOR_TABLE} "
        "WHERE monitor_point_name IN {names:Array(String)} "
        "AND (status IS NULL OR status != '1') "
        "AND (is_cancelled IS NULL OR is_cancelled != '1')"
    )
    results: list[dict] = []
    for i in range(0, len(point_names), _SENSOR_BATCH):
        batch = point_names[i : i + _SENSOR_BATCH]
        results.extend(client.query(sql, {"names": batch}))
    return results



def _build_daily_sql(level: str) -> str:
    """为指定层级构造 daily 聚合 SQL，在 CH 内完成 min/max/avg/sum。"""
    spec = TIME_SERIES_TABLES[level]
    table = spec["table"]
    metrics = spec["metrics"]
    agg_parts = []
    for m in metrics:
        agg_parts.append(f"min({m}) AS {m}_min")
        agg_parts.append(f"max({m}) AS {m}_max")
        agg_parts.append(f"avg({m}) AS {m}_avg")
        agg_parts.append(f"sum({m}) AS {m}_sum")
    agg_str = ", ".join(agg_parts)
    return (
        f"SELECT SensorCode, toDate(Time) AS day, {agg_str}, count() AS n "
        f"FROM {table} "
        f"WHERE SensorCode IN {{sensor_codes:Array(String)}} "
        f"AND Time >= {{since:DateTime64}} "
        f"GROUP BY SensorCode, day "
        f"ORDER BY SensorCode, day"
    )

def _query_level_rows(
    client: ClickHouseClient,
    level: str,
    sensor_codes: list[str],
    since: datetime,
) -> list[dict]:
    spec = TIME_SERIES_TABLES[level]
    columns = ", ".join(("SensorCode", "Time", *spec["metrics"]))
    sql = (
        f"SELECT {columns} FROM {spec['table']} "
        "WHERE SensorCode IN {sensor_codes:Array(String)} "
        "AND Time >= {since:DateTime64} "
        "ORDER BY SensorCode, Time"
    )
    results: list[dict] = []
    for i in range(0, len(sensor_codes), _LEVEL_BATCH):
        batch = sensor_codes[i : i + _LEVEL_BATCH]
        results.extend(client.query(sql, {"sensor_codes": batch, "since": since}))
    return results


def _explode_observations(
    rows: list[dict],
    level: str,
    sensor_to_points: dict[str, list[str]],
    sensor_type_by_code: dict[str, str],
    sensor_name_by_code: dict[str, str],
    device_model_by_code: dict[str, str],
) -> dict[str, list[dict]]:
    spec = TIME_SERIES_TABLES[level]
    by_point: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        sensor_code = str(row.get("SensorCode", "")).strip()
        point_codes = sensor_to_points.get(sensor_code, [])
        if not point_codes:
            continue
        for metric in spec["metrics"]:
            value = row.get(metric)
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            obs = {
                "source": level,
                "kind": spec["kind"],
                "sensor_code": sensor_code,
                "sensor_type": sensor_type_by_code.get(sensor_code, ""),
                "sensor_type_name": sensor_name_by_code.get(sensor_code, ""),
                "device_model": device_model_by_code.get(sensor_code, "unknown"),
                "time": row.get("Time"),
                "metric": metric,
                "value": numeric,
            }
            for point_code in point_codes:
                by_point[point_code].append(obs)
    return dict(by_point)


_DAILY_SQL_CACHE: dict[str, str] = {}


def _query_level_rows_daily(
    client: ClickHouseClient,
    level: str,
    sensor_codes: list[str],
    since: datetime,
) -> list[dict]:
    """按日聚合查询传感器时序数据（CH 内完成 min/max/avg/sum），避免传输海量原始行。

    返回每行含 SensorCode、day（Date）、各指标 _min/_max/_avg/_sum、n。
    """
    if level not in _DAILY_SQL_CACHE:
        _DAILY_SQL_CACHE[level] = _build_daily_sql(level)
    sql = _DAILY_SQL_CACHE[level]
    results: list[dict] = []
    for i in range(0, len(sensor_codes), _LEVEL_BATCH):
        batch = sensor_codes[i : i + _LEVEL_BATCH]
        results.extend(client.query(sql, {"sensor_codes": batch, "since": since}))
    return results


def _as_date(val) -> date | None:
    """将 CH Date/Datetime/date 值统一转为 datetime.date。"""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return None


def _explode_daily_observations(
    rows: list[dict],
    level: str,
    sensor_to_points: dict[str, list[str]],
    sensor_type_by_code: dict[str, str],
    sensor_name_by_code: dict[str, str],
    device_model_by_code: dict[str, str],
) -> dict[str, list[dict]]:
    """将 daily 聚合行展开为与 _explode_observations 兼容的 observation dict 列表。

    聚合策略：
    - totalValue（累计雨量）：每日期发两条 obs（日 min + 日 max），下游的 max-min 窗口 delta 自然正确。
    - L3 value（间隔雨量）：用日 max（单次最大读数，用于小时雨强判定）。
    - 其余指标：用日 avg。
    """
    spec = TIME_SERIES_TABLES[level]
    by_point: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        sensor_code = str(row.get("SensorCode", "")).strip()
        point_codes = sensor_to_points.get(sensor_code, [])
        if not point_codes:
            continue
        day = _as_date(row.get("day"))
        if day is None:
            continue
        day_dt = datetime(day.year, day.month, day.day)

        for metric in spec["metrics"]:
            if metric == "totalValue":
                vmin = row.get("totalValue_min")
                vmax = row.get("totalValue_max")
                if vmin is None or vmax is None:
                    continue
                try:
                    vmin_f, vmax_f = float(vmin), float(vmax)
                except (TypeError, ValueError):
                    continue
                for val in (vmin_f, vmax_f):
                    obs = _mk_daily_obs(day_dt, level, spec, sensor_code, sensor_type_by_code,
                                        sensor_name_by_code, device_model_by_code, metric, val)
                    for point_code in point_codes:
                        by_point[point_code].append(obs)
            elif metric == "value" and level == "L3":
                vmax = row.get("value_max")
                if vmax is None:
                    continue
                try:
                    numeric = float(vmax)
                except (TypeError, ValueError):
                    continue
                obs = _mk_daily_obs(day_dt, level, spec, sensor_code, sensor_type_by_code,
                                    sensor_name_by_code, device_model_by_code, metric, numeric)
                for point_code in point_codes:
                    by_point[point_code].append(obs)
            else:
                vavg = row.get(f"{metric}_avg")
                if vavg is None:
                    continue
                try:
                    numeric = float(vavg)
                except (TypeError, ValueError):
                    continue
                obs = _mk_daily_obs(day_dt, level, spec, sensor_code, sensor_type_by_code,
                                    sensor_name_by_code, device_model_by_code, metric, numeric)
                for point_code in point_codes:
                    by_point[point_code].append(obs)
    return dict(by_point)


def _mk_daily_obs(
    day_dt: datetime,
    level: str,
    spec: dict,
    sensor_code: str,
    sensor_type_by_code: dict[str, str],
    sensor_name_by_code: dict[str, str],
    device_model_by_code: dict[str, str],
    metric: str,
    value: float,
) -> dict:
    return {
        "source": level,
        "kind": spec["kind"],
        "sensor_code": sensor_code,
        "sensor_type": sensor_type_by_code.get(sensor_code, ""),
        "sensor_type_name": sensor_name_by_code.get(sensor_code, ""),
        "device_model": device_model_by_code.get(sensor_code, "unknown"),
        "time": day_dt,
        "metric": metric,
        "value": value,
    }


def fetch_time_series_for_points(
    df: pd.DataFrame,
    client: ClickHouseClient | None = None,
    lookback_days: int | None = None,
) -> dict:
    """拉取圈内点位近 N 天时序数据。

    返回结构固定为 bundle，调用方可在 CH 不通、无传感器或无数据时统一降级。
    """
    settings = get_settings()
    lookback = lookback_days or settings.trend_lookback_days
    bundle = {
        "enabled": False,
        "lookback_days": lookback,
        "series": {},
        "sensor_count": 0,
        "observation_count": 0,
        "point_count": int(len(df)),
        "source_point_count": int(len(df)),
        "limitations": [],
    }

    point_name_to_codes = _point_name_map(df)
    if not point_name_to_codes:
        bundle["limitations"].append("监测点缺少名称，无法按现有表结构关联传感器时序数据")
        return bundle

    external_client = client is not None
    try:
        client = client or ClickHouseClient()
        sensors = _query_sensors(client, sorted(point_name_to_codes))
    except Exception as exc:  # noqa: BLE001
        bundle["limitations"].append(f"传感器信息查询失败:{type(exc).__name__}")
        return bundle

    if not sensors:
        bundle["limitations"].append("圈内点位未匹配到可用传感器")
        return bundle

    sensor_to_points: dict[str, list[str]] = {}
    sensor_type_by_code: dict[str, str] = {}
    sensor_name_by_code: dict[str, str] = {}
    device_model_by_code: dict[str, str] = {}
    # 按监测点优先级排序传感器:高预警/大·特大优先
    _warn_order = {"红色": 4, "橙色": 3, "黄色": 2, "蓝色": 1}
    point_priority: dict[str, int] = {}
    for _, row in df.iterrows():
        code = str(row.get("monitor_point_code", "")).strip()
        wl = str(row.get("warning_level", "")).strip()
        sc = str(row.get("scale", "")).strip()
        point_priority[code] = _warn_order.get(wl, 0) + (3 if sc in ("特大", "大") else 1 if sc == "中" else 0)

    def _sensor_sort_key(code: str) -> int:
        pts = sensor_to_points.get(code, [])
        return max((point_priority.get(p, 0) for p in pts), default=0)

    level_to_sensors: dict[str, list[str]] = defaultdict(list)
    max_per_level = settings.timeseries_max_sensors_per_level
    for sensor in sensors:
        code = str(sensor.get("sensor_code", "")).strip()
        name = str(sensor.get("monitor_point_name", "")).strip()
        level = _sensor_level(sensor.get("sensor_type"))
        if not code or not name or not level:
            continue
        sensor_to_points[code] = point_name_to_codes.get(name, [])
        sensor_type = str(sensor.get("sensor_type") or "")
        sensor_type_name = str(sensor.get("sensor_type_name") or "")
        sensor_type_by_code[code] = sensor_type
        sensor_name_by_code[code] = sensor_type_name
        device_model_by_code[code] = classify_device_model(sensor_type, sensor_type_name)
        level_to_sensors[level].append(code)

    # 优先级截断:每层只保留高优先级关联的传感器
    truncated_levels: list[str] = []
    for level in list(level_to_sensors):
        codes = level_to_sensors[level]
        if len(codes) > max_per_level:
            codes.sort(key=_sensor_sort_key, reverse=True)
            level_to_sensors[level] = codes[:max_per_level]
            truncated_levels.append(level)
    if truncated_levels:
        bundle["limitations"].append(
            f"传感器数量过大，{','.join(truncated_levels)} 层截断至每层 {max_per_level} 个(按预警/规模优先级)"
        )
    if not level_to_sensors:
        bundle["limitations"].append("已匹配传感器，但未识别出 L1/L2/L3/L4 类型")
        return bundle

    since = datetime.now() - timedelta(days=lookback)
    series_by_level: dict[str, dict[str, list[dict]]] = {}
    query_errors: list[str] = []

    def _query_and_explode(level: str, sensor_codes: list[str]) -> tuple[str, dict[str, list[dict]]]:
        query_client = client if external_client else ClickHouseClient()
        rows = _query_level_rows_daily(query_client, level, sensor_codes, since)
        return level, _explode_daily_observations(
            rows,
            level,
            sensor_to_points,
            sensor_type_by_code,
            sensor_name_by_code,
            device_model_by_code,
        )

    max_workers = max(1, min(len(level_to_sensors), 4))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="timeseries") as executor:
        futures = {
            executor.submit(_query_and_explode, level, sensor_codes): level
            for level, sensor_codes in level_to_sensors.items()
        }
        for future in as_completed(futures):
            level = futures[future]
            try:
                _, exploded = future.result()
            except Exception as exc:  # noqa: BLE001
                query_errors.append(f"{level}查询失败:{type(exc).__name__}")
                continue
            series_by_level[level] = exploded

    series: dict[str, list[dict]] = defaultdict(list)
    for level in TIME_SERIES_TABLES:
        exploded = series_by_level.get(level) or {}
        for point_code in sorted(exploded):
            series[point_code].extend(exploded[point_code])

    bundle["enabled"] = True
    bundle["series"] = dict(series)
    bundle["sensor_count"] = sum(len(v) for v in level_to_sensors.values())
    bundle["observation_count"] = sum(len(v) for v in series.values())
    bundle["limitations"].extend(query_errors)
    if not series:
        bundle["limitations"].append("传感器已匹配，但回溯窗口内无有效时序观测")
    return bundle
