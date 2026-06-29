"""降雨-变形耦合分析：同步/滞后响应相关性。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from math import sqrt

from app.pipeline.trends import _as_datetime, _observation_model


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    cov = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    x_var = sum((x - x_mean) ** 2 for x in xs)
    y_var = sum((y - y_mean) ** 2 for y in ys)
    if x_var <= 0 or y_var <= 0:
        return None
    return cov / sqrt(x_var * y_var)


def _daily_series(observations: list[dict]) -> tuple[dict[datetime.date, float], dict[datetime.date, float]]:
    # totalValue 是持续累积值(不清零),按天取 max-min = 日雨量
    # value(间隔雨量)作为回退,按天累加
    rain_raw: dict[datetime.date, list[float]] = defaultdict(list)
    rain_value: dict[datetime.date, list[float]] = defaultdict(list)
    deform_values: dict[datetime.date, list[float]] = defaultdict(list)
    for obs in observations:
        ts = _as_datetime(obs.get("time"))
        if ts is None:
            continue
        model = _observation_model(obs)
        metric = str(obs.get("metric", ""))
        value = float(obs.get("value", 0))
        day = ts.date()
        if model == "rain_gauge" and metric == "totalValue":
            rain_raw[day].append(value)
        elif model == "rain_gauge" and metric == "value":
            rain_value[day].append(value)
        elif model in {"crack_meter", "gnss_displacement", "deformation_generic", "macro_observation"} and metric != "speed":
            deform_values[day].append(value)

    rain: dict[datetime.date, float] = {}
    # 优先用 totalValue 日差值(max-min)
    for day, vals in rain_raw.items():
        rain[day] = max(vals) - min(vals) if len(vals) >= 2 else 0.0
    # 回退:无 totalValue 的日期用 value 累加
    for day, vals in rain_value.items():
        if day not in rain:
            rain[day] = sum(vals)

    daily_last = {day: vals[-1] for day, vals in deform_values.items() if vals}
    deformation: dict[datetime.date, float] = {}
    prev_value = None
    for day in sorted(daily_last):
        if prev_value is None:
            deformation[day] = 0.0
        else:
            deformation[day] = daily_last[day] - prev_value
        prev_value = daily_last[day]
    return dict(rain), deformation


def analyze_rain_deformation_coupling(time_series: dict | None) -> dict:
    """分析雨量与变形响应关系。"""
    if not time_series or not time_series.get("enabled") or not time_series.get("series"):
        return {
            "rain_deformation_summary": "未接入有效雨量/变形时序，暂无法开展降雨-变形耦合分析。",
            "rain_deformation_detail": "（无）",
        }

    lines = []
    coupled_count = 0
    for point_code, observations in time_series.get("series", {}).items():
        rain, deformation = _daily_series(observations)
        common_days = sorted(set(rain) & set(deformation))
        if len(common_days) < 3:
            continue
        same = _pearson([rain[d] for d in common_days], [abs(deformation[d]) for d in common_days])
        lag_pairs = [(d, d + timedelta(days=1)) for d in sorted(rain) if d + timedelta(days=1) in deformation]
        lag = _pearson([rain[d] for d, _ in lag_pairs], [abs(deformation[n]) for _, n in lag_pairs]) if len(lag_pairs) >= 3 else None
        best_name, best_value = ("同步", same)
        if lag is not None and (best_value is None or abs(lag) > abs(best_value)):
            best_name, best_value = ("滞后1天", lag)
        if best_value is None:
            continue
        if abs(best_value) >= 0.6:
            coupled_count += 1
            level = "强相关"
        elif abs(best_value) >= 0.35:
            level = "中等相关"
        else:
            level = "弱相关"
        if level != "弱相关":
            lines.append(f"[{point_code}] {best_name}{level} r={best_value:.2f}，样本日数 {len(common_days)}")

    summary = (
        f"识别到 {coupled_count} 个点位存在中等及以上降雨-变形响应关系。"
        if coupled_count
        else "未识别到中等及以上降雨-变形响应关系，可能受样本不足或时序缺测影响。"
    )
    return {
        "rain_deformation_summary": summary,
        "rain_deformation_detail": "\n".join(lines[:12]) if lines else "（无中高相关点位）",
    }
