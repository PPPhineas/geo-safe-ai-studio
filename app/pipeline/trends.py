"""变形趋势分析。

当前数据源尚未接入监测时序值，本环节先基于 `current_status` 填报文本做确定性
趋势识别：分类、计数、提取证据点位。后续接入位移/裂缝/雨量等时序后，可在本模块
扩展为数值趋势斜率与突变检测。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd

from app.config import get_settings
from app.pipeline.timeseries import classify_device_model

WORSENING_TERMS = (
    "不稳定",
    "加剧",
    "扩大",
    "扩展",
    "恶化",
    "增大",
    "增加",
    "发展",
    "活跃",
    "持续变形",
    "明显变形",
    "裂缝扩大",
    "裂缝增宽",
    "沉降",
    "位移",
    "滑移",
    "蠕滑",
    "下错",
    "张开",
    "掉块",
    "坍塌",
)
STABLE_TERMS = (
    "稳定",
    "基本稳定",
    "较稳定",
    "未见变化",
    "无明显变化",
    "无明显变形",
    "暂无变化",
    "趋稳",
)
IMPROVING_TERMS = ("减缓", "趋缓", "收敛", "好转", "减小", "停止发展", "基本停止")

TREND_ORDER = ("恶化/发展", "稳定/趋稳", "缓解/减弱", "未填报")

MODEL_LABELS = {
    "crack_meter": "裂缝计",
    "gnss_displacement": "GNSS/地表位移",
    "tilt_meter": "倾角计",
    "accelerometer": "加速度/振动",
    "rain_gauge": "雨量计",
    "acoustic": "声发射/次声",
    "physical_field": "物理场",
    "macro_observation": "宏观现象",
    "deformation_generic": "变形监测",
    "unknown": "未知设备",
}

MODEL_METRICS = {
    "crack_meter": {"value"},
    "gnss_displacement": {"gpsTotalX", "gpsTotalY", "gpsTotalZ", "dispsX", "dispsY"},
    "tilt_meter": {"X", "Y", "Z", "angle"},
    "accelerometer": {"gX", "gY", "gZ", "PLX", "PLY", "PLZ", "SJValue"},
    "rain_gauge": {"value", "totalValue"},
    "acoustic": {"amplitude", "energy", "ringing", "RMS", "ASL", "OSP", "VSP", "freq"},
    "physical_field": {"value", "amplitude", "energy", "ringing", "RMS", "ASL"},
    "macro_observation": {"value", "x", "y", "speed"},
    "deformation_generic": {"value", "gpsTotalX", "gpsTotalY", "gpsTotalZ", "dispsX", "dispsY", "angle", "SJValue"},
}

FORECAST_MODELS = {"crack_meter", "gnss_displacement", "deformation_generic", "macro_observation"}
RATE_MODELS = FORECAST_MODELS | {"tilt_meter"}
ACTIVITY_MODELS = {"accelerometer", "acoustic", "physical_field"}


def classify_deformation_trend(text: str | None) -> tuple[str, int, list[str]]:
    """从现状趋势文本识别变形趋势类别、风险分和命中词。"""
    content = (text or "").strip()
    if not content:
        return "未填报", 0, []

    worsening_hits = [term for term in WORSENING_TERMS if term in content]
    improving_hits = [term for term in IMPROVING_TERMS if term in content]
    stable_hits = [term for term in STABLE_TERMS if term in content]
    non_worsening_hits = improving_hits + stable_hits
    direct_worsening_hits = [
        term
        for term in worsening_hits
        if not any(term in phrase for phrase in non_worsening_hits)
    ]

    if direct_worsening_hits:
        return "恶化/发展", 3, direct_worsening_hits
    if improving_hits:
        return "缓解/减弱", 1, improving_hits
    if stable_hits:
        return "稳定/趋稳", 0, stable_hits
    return "未填报", 0, []


def _fmt_counts(counts: dict[str, int]) -> str:
    return "、".join(f"{key} {counts[key]}" for key in TREND_ORDER if counts.get(key, 0)) or "无"


def _as_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        # 剥离时区，统一为 naive datetime，避免与 datetime.now() 比较时报错
        return value.replace(tzinfo=None)
    try:
        parsed = pd.to_datetime(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().replace(tzinfo=None)


def _linear_rate_per_day(points: list[tuple[datetime, float]]) -> float | None:
    if len(points) < 2:
        return None
    start = points[0][0]
    xs = [(t - start).total_seconds() / 86400 for t, _ in points]
    ys = [v for _, v in points]
    if max(xs) == min(xs):
        return None
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denom


def _metric_summary(points: list[tuple[datetime, float]]) -> dict:
    ordered = sorted(points, key=lambda item: item[0])
    if len(ordered) < 2:
        return {"sample_count": len(ordered)}
    duration_days = max((ordered[-1][0] - ordered[0][0]).total_seconds() / 86400, 1 / 24)
    delta = ordered[-1][1] - ordered[0][1]
    rate = _linear_rate_per_day(ordered)
    split = max(2, int(len(ordered) * 0.75))
    recent_rate = _linear_rate_per_day(ordered[split - 1 :])
    early_rate = _linear_rate_per_day(ordered[:split])
    accel_ratio = None
    if recent_rate is not None and early_rate is not None and abs(early_rate) > 1e-9:
        accel_ratio = abs(recent_rate) / abs(early_rate)
    return {
        "sample_count": len(ordered),
        "start_time": ordered[0][0],
        "end_time": ordered[-1][0],
        "start_value": ordered[0][1],
        "end_value": ordered[-1][1],
        "delta": delta,
        "duration_days": duration_days,
        "rate_per_day": rate if rate is not None else delta / duration_days,
        "recent_rate_per_day": recent_rate,
        "acceleration_ratio": accel_ratio,
        "max_value": max(v for _, v in ordered),
        "min_value": min(v for _, v in ordered),
    }


def _observation_model(obs: dict) -> str:
    model = str(obs.get("device_model") or "")
    if model and model != "unknown":
        return model
    inferred = classify_device_model(obs.get("sensor_type"), obs.get("sensor_type_name"))
    if inferred != "unknown":
        return inferred
    kind = str(obs.get("kind") or "")
    source = str(obs.get("source") or "")
    if kind == "rainfall" or source == "L3":
        return "rain_gauge"
    if kind == "physical" or source == "L2":
        return "physical_field"
    if kind == "macro" or source == "L4":
        return "macro_observation"
    if kind == "deformation" or source == "L1":
        return "deformation_generic"
    return "unknown"


def _forecast_point(metrics: list[dict], rain_24h: float, rain_72h: float) -> dict:
    """基于近期变化率做短期趋势外推。

    这是工程预测框架，不替代专业预警模型：只使用已观测趋势线性外推，并用近期加速和雨量
    作为风险放大因子。
    """
    settings = get_settings()
    horizon = settings.trend_forecast_days
    candidates = []
    for item in metrics:
        model = item.get("device_model", "unknown")
        metric = item.get("metric")
        if model not in FORECAST_MODELS or metric == "speed":
            continue
        rate = item.get("recent_rate_per_day")
        if rate is None:
            rate = item.get("rate_per_day")
        if rate is None:
            continue
        projected_delta = float(rate) * horizon
        candidates.append(
            {
                "source": item.get("source"),
                "device_model": model,
                "metric": metric,
                "rate_per_day": float(rate),
                "projected_delta": projected_delta,
                "acceleration_ratio": item.get("acceleration_ratio"),
            }
        )

    if not candidates:
        return {
            "horizon_days": horizon,
            "level": "不可预测",
            "direction": "时序样本不足",
            "basis": "缺少可用于外推的位移/宏观位移累计指标",
            "items": [],
        }

    candidates.sort(key=lambda item: abs(item["projected_delta"]), reverse=True)
    main = candidates[0]
    abs_rate = abs(main["rate_per_day"])
    abs_delta = abs(main["projected_delta"])
    rain_boost = rain_24h >= settings.trend_rain_24h_warn or rain_72h >= settings.trend_rain_72h_warn
    accel = float(main.get("acceleration_ratio") or 0)

    level = "低"
    if abs_rate >= settings.trend_deformation_rate_high or accel >= settings.trend_acceleration_ratio:
        level = "高"
    elif abs_rate >= settings.trend_deformation_rate_warn:
        level = "中"
    if rain_boost and level == "中":
        level = "高"
    elif rain_boost and level == "低":
        level = "中"

    direction = "持续增大" if main["projected_delta"] > 0 else "持续减小"
    if abs_delta < settings.trend_deformation_rate_warn * horizon:
        direction = "基本平稳"

    basis = (
        f"{MODEL_LABELS.get(main['device_model'], main['device_model'])}.{main['metric']} "
        f"近期变化率 {main['rate_per_day']:.2f}/日，"
        f"预计未来{horizon}天变化 {main['projected_delta']:.2f}"
    )
    if accel:
        basis += f"，加速倍率 {accel:.1f}"
    if rain_boost:
        basis += f"，近24/72小时雨量 {rain_24h:.1f}/{rain_72h:.1f}"

    return {
        "horizon_days": horizon,
        "level": level,
        "direction": direction,
        "basis": basis,
        "items": candidates[:5],
    }


def _analyze_point_series(observations: list[dict]) -> dict:
    settings = get_settings()
    grouped: dict[tuple[str, str, str, str], list[tuple[datetime, float]]] = defaultdict(list)
    for obs in observations:
        ts = _as_datetime(obs.get("time"))
        if ts is None:
            continue
        model = _observation_model(obs)
        metric = str(obs.get("metric", ""))
        allowed = MODEL_METRICS.get(model)
        if allowed is not None and metric not in allowed:
            continue
        key = (model, str(obs.get("kind", "")), str(obs.get("source", "")), metric)
        grouped[key].append((ts, float(obs["value"])))

    metrics = []
    severity = 0
    reasons: list[str] = []
    rain_24h = 0.0
    rain_72h = 0.0
    rain_intensity = "无雨"
    max_hourly_intensity = 0.0
    daily_rainfall: list[dict] = []
    temp_stats: dict = {}
    now = datetime.now()

    # ---- 分离雨量计与变形/其他指标 ----
    rain_groups: dict[str, list[tuple[datetime, float]]] = {}
    for (model, kind, source, metric), points in grouped.items():
        if model == "rain_gauge":
            rain_groups[metric] = points
            continue
        if len(points) < settings.trend_min_samples:
            continue
        summary = _metric_summary(points)
        summary.update({"device_model": model, "kind": kind, "source": source, "metric": metric})
        metrics.append(summary)

        rate = abs(float(summary.get("rate_per_day") or 0))
        recent_rate = abs(float(summary.get("recent_rate_per_day") or 0))
        accel = float(summary.get("acceleration_ratio") or 0)
        model_label = MODEL_LABELS.get(model, model)
        if model in RATE_MODELS and metric != "speed":
            if rate >= settings.trend_deformation_rate_high or recent_rate >= settings.trend_deformation_rate_high:
                severity = max(severity, 3)
                reasons.append(f"{model_label}.{metric} 日变化率达到高风险阈值({rate:.2f})")
            elif rate >= settings.trend_deformation_rate_warn or recent_rate >= settings.trend_deformation_rate_warn:
                severity = max(severity, 2)
                reasons.append(f"{model_label}.{metric} 日变化率达到关注阈值({rate:.2f})")
            if accel >= settings.trend_acceleration_ratio:
                severity = max(severity, 3)
                reasons.append(f"{model_label}.{metric} 近期变化率较前期放大 {accel:.1f} 倍")
        if model in ACTIVITY_MODELS:
            if accel >= settings.trend_acceleration_ratio:
                severity = max(severity, 2)
                reasons.append(f"{model_label}.{metric} 活动强度近期增强 {accel:.1f} 倍")

    # ---- 雨量计专项处理 ----
    if rain_groups:
        total_points = rain_groups.get("totalValue", [])
        value_points = rain_groups.get("value", [])
        temp_points = rain_groups.get("temp", [])

        # totalValue 是持续累积值(不清零),用窗口内 max-min 即时段总雨量
        # 回退:若无 totalValue,用 value(间隔雨量)累加
        def _total_delta(pts: list[tuple[datetime, float]], window_hours: float) -> float | None:
            vals = [v for t, v in pts if now - t <= timedelta(hours=window_hours)]
            return max(vals) - min(vals) if len(vals) >= 2 else None

        def _value_sum(pts: list[tuple[datetime, float]], window_hours: float) -> float:
            return sum(v for t, v in pts if now - t <= timedelta(hours=window_hours))

        # 24h 雨量
        delta_24 = _total_delta(total_points, 24) if total_points else None
        if delta_24 is not None:
            rain_24h = delta_24
        elif value_points:
            rain_24h = _value_sum(value_points, 24)

        # 72h 雨量
        delta_72 = _total_delta(total_points, 72) if total_points else None
        if delta_72 is not None:
            rain_72h = delta_72
        elif value_points:
            rain_72h = _value_sum(value_points, 72)

        # 逐日雨量(totalValue 日差值,近 14 天)
        day_totals: dict[datetime.date, list[float]] = defaultdict(list)
        for t, v in total_points:
            day_totals[t.date()].append(v)
        daily_rainfall = []
        for day in sorted(day_totals)[-14:]:
            vals = day_totals[day]
            daily = max(vals) - min(vals) if len(vals) >= 2 else 0.0
            daily_rainfall.append({"date": day.isoformat(), "rainfall_mm": round(daily, 1)})

        # 最大小时雨强(value 单次最大值)
        recent_vals = [v for t, v in value_points if now - t <= timedelta(hours=24)]
        if recent_vals:
            max_hourly_intensity = max(recent_vals)

        # 雨强分级(基于 24h 雨量,中国气象局标准)
        if rain_24h >= settings.rain_intensity_severe_storm:
            rain_intensity = "大暴雨"
        elif rain_24h >= settings.rain_intensity_storm:
            rain_intensity = "暴雨"
        elif rain_24h >= settings.rain_intensity_heavy:
            rain_intensity = "大雨"
        elif rain_24h >= settings.rain_intensity_moderate:
            rain_intensity = "中雨"
        elif rain_24h > 0:
            rain_intensity = "小雨"

        # 雨量预警判定
        if rain_72h >= settings.trend_rain_72h_warn:
            severity = max(severity, 2)
            reasons.append(f"近72小时累计雨量 {rain_72h:.1f}mm 达关注阈值(雨强:{rain_intensity})")
        elif rain_24h >= settings.trend_rain_24h_warn:
            severity = max(severity, 1)
            reasons.append(f"近24小时累计雨量 {rain_24h:.1f}mm 达关注阈值(雨强:{rain_intensity})")
        elif rain_intensity in ("暴雨", "大暴雨"):
            severity = max(severity, 1)
            reasons.append(f"24小时雨量 {rain_24h:.1f}mm({rain_intensity}),存在降雨诱发风险")

        # 温度分析(L3 temp)
        if temp_points:
            temps = [v for _, v in temp_points]
            temp_stats = {
                "current": round(temps[-1], 1) if temps else None,
                "min": round(min(temps), 1) if temps else None,
                "max": round(max(temps), 1) if temps else None,
            }

    forecast = _forecast_point(metrics, rain_24h, rain_72h)
    if forecast["level"] == "高":
        severity = max(severity, 3)
    elif forecast["level"] == "中":
        severity = max(severity, 2)

    label = "未触发时序异常"
    if severity >= 3:
        label = "时序加速/异常"
    elif severity == 2:
        label = "时序持续发展"
    elif severity == 1:
        label = "诱发因素增强"
    return {
        "label": label,
        "severity": severity,
        "reasons": reasons[:6],
        "metrics": metrics,
        "rain_24h": rain_24h,
        "rain_72h": rain_72h,
        "rain_intensity": rain_intensity,
        "max_hourly_intensity": max_hourly_intensity,
        "daily_rainfall": daily_rainfall,
        "temp_stats": temp_stats,
        "forecast": forecast,
    }


def _analyze_time_series_bundle(bundle: dict | None) -> dict:
    if not bundle or not bundle.get("enabled"):
        limitations = (bundle or {}).get("limitations") or ["未提供时序监测数据"]
        return {
            "point_results": {},
            "summary": "未接入有效传感器时序数据；本次变形趋势以现状/趋势填报文本识别为主。",
            "detail": "（无有效时序趋势点位）",
            "forecast_summary": "未接入有效传感器时序数据，暂不生成趋势预测。",
            "forecast_detail": "（无趋势预测点位）",
            "rain_summary": "未接入有效雨量传感器时序，暂无法开展降雨-诱发分析。",
            "rain_detail": "（无有效降雨记录）",
            "limitations": limitations,
        }

    point_results = {
        str(code): _analyze_point_series(observations)
        for code, observations in (bundle.get("series") or {}).items()
        if observations
    }
    abnormal = [(code, item) for code, item in point_results.items() if item["severity"] > 0]
    abnormal.sort(key=lambda item: item[1]["severity"], reverse=True)
    lines = []
    forecast_lines = []
    for code, item in abnormal[:12]:
        reason = "；".join(item["reasons"]) if item["reasons"] else item["label"]
        lines.append(f"[{code}] {item['label']} | {reason}")
    forecasted = [
        (code, item.get("forecast", {}))
        for code, item in point_results.items()
        if item.get("forecast", {}).get("level") in {"高", "中"}
    ]
    order = {"高": 2, "中": 1}
    forecasted.sort(key=lambda item: order.get(item[1].get("level", ""), 0), reverse=True)
    for code, forecast in forecasted[:12]:
        forecast_lines.append(
            f"[{code}] 预测风险:{forecast.get('level')} | "
            f"{forecast.get('direction')} | {forecast.get('basis')}"
        )
    summary = (
        f"近 {bundle.get('lookback_days')} 天匹配传感器 {bundle.get('sensor_count', 0)} 个，"
        f"有效观测 {bundle.get('observation_count', 0)} 条；"
        f"识别时序异常/诱发增强点位 {len(abnormal)} 个。"
    )
    forecast_summary = (
        f"基于位移/宏观位移近期变化率外推，识别未来短期中高预测风险点位 {len(forecasted)} 个。"
        if point_results
        else "无有效点位时序，暂不生成趋势预测。"
    )

    # ---- 雨量专项汇总 ----
    rain_lines: list[str] = []
    rain_affected: dict[str, int] = defaultdict(int)
    for code, item in point_results.items():
        ri = item.get("rain_intensity", "无雨")
        if ri == "无雨":
            continue
        rain_affected[ri] += 1
        rain_24h = item.get("rain_24h", 0)
        max_hourly = item.get("max_hourly_intensity", 0)
        rain_lines.append(f"[{code}] {ri} 24h={rain_24h:.1f}mm"
                          + (f" 最大小时雨强={max_hourly:.1f}mm" if max_hourly > 0 else ""))
    rain_lines.sort(key=lambda line: line.count("大暴雨") * 100 + line.count("暴雨") * 10 + line.count("大雨"), reverse=True)

    rain_summary_parts = [f"{label} {cnt} 个点" for label, cnt
                          in [("大暴雨", rain_affected.get("大暴雨", 0)),
                              ("暴雨", rain_affected.get("暴雨", 0)),
                              ("大雨", rain_affected.get("大雨", 0)),
                              ("中雨", rain_affected.get("中雨", 0)),
                              ("小雨", rain_affected.get("小雨", 0))]
                          if cnt > 0]
    rain_summary = (
        f"识别到 {sum(rain_affected.values())} 个点位有有效降雨记录，"
        + ("雨情分布: " + "、".join(rain_summary_parts) if rain_summary_parts else "无明显降雨。")
    )

    return {
        "point_results": point_results,
        "summary": summary,
        "detail": "\n".join(lines) if lines else "（未识别到达到阈值的时序异常点位）",
        "forecast_summary": forecast_summary,
        "forecast_detail": "\n".join(forecast_lines) if forecast_lines else "（未识别到中高预测风险点位）",
        "rain_summary": rain_summary,
        "rain_detail": "\n".join(rain_lines[:12]) if rain_lines else "（无有效降雨记录）",
        "limitations": bundle.get("limitations") or [],
    }


def analyze_deformation_trends(
    df: pd.DataFrame,
    time_series: dict | None = None,
    max_points: int = 12,
) -> dict:
    """分析圈内点位变形趋势。

    Returns:
        `trend_labels` 与 `trend_scores` 按 DataFrame 行顺序返回，供重点点位筛选复用；
        其余字段用于 prompt 和报告渲染。
    """
    series_result = _analyze_time_series_bundle(time_series)
    if df.empty or "current_status" not in df.columns:
        return {
            "trend_labels": [],
            "trend_scores": [],
            "trend_distribution": {key: 0 for key in TREND_ORDER},
            "deformation_trend_summary": "无现状/趋势填报，暂无法开展文本趋势识别。" + series_result["summary"],
            "deformation_points_detail": "（无）",
            "trend_evidence_codes": [],
            "worsening_point_count": 0,
            "time_series_summary": series_result["summary"],
            "time_series_points_detail": series_result["detail"],
            "trend_forecast_summary": series_result["forecast_summary"],
            "trend_forecast_detail": series_result["forecast_detail"],
            "time_series_point_results": series_result["point_results"],
            "time_series_limitations": series_result["limitations"],
            "time_series_rain_summary": series_result.get("rain_summary", ""),
            "time_series_rain_detail": series_result.get("rain_detail", ""),
        }

    labels: list[str] = []
    scores: list[int] = []
    hits_by_pos: list[list[str]] = []
    for text in df["current_status"].fillna("").astype(str):
        label, score, hits = classify_deformation_trend(text)
        labels.append(label)
        scores.append(score)
        hits_by_pos.append(hits)

    counts = {key: labels.count(key) for key in TREND_ORDER}
    worsening_rows = []
    for pos, (_, row) in enumerate(df.iterrows()):
        code = str(row.get("monitor_point_code", ""))
        ts_result = series_result["point_results"].get(code, {})
        if labels[pos] != "恶化/发展" and int(ts_result.get("severity", 0)) <= 0:
            continue
        threat = float(row.get("threaten_population", 0) or 0) + float(row.get("threaten_assets", 0) or 0) / 10
        combined_score = scores[pos] + int(ts_result.get("severity", 0))
        worsening_rows.append((combined_score, threat, pos, row, hits_by_pos[pos], ts_result))
    worsening_rows.sort(key=lambda item: (item[0], item[1]), reverse=True)

    lines = []
    evidence_codes: list[str] = []
    for _, _, _, row, hits, ts_result in worsening_rows[:max_points]:
        code = str(row.get("monitor_point_code", ""))
        evidence_codes.append(code)
        status = str(row.get("current_status", "")).strip() or "—"
        hit_text = "、".join(hits[:4]) if hits else "趋势词"
        ts_reason = "；".join(ts_result.get("reasons") or [])
        suffix = f" | 时序:{ts_reason}" if ts_reason else ""
        lines.append(f"[{code}] 命中:{hit_text} | 现状趋势:{status}{suffix}")

    filled_count = len(df) - counts["未填报"]
    summary = (
        f"现状/趋势字段已填报 {filled_count}/{len(df)} 个；"
        f"趋势识别结果：{_fmt_counts(counts)}。"
    )
    if counts["恶化/发展"]:
        summary += f" 其中 {counts['恶化/发展']} 个点位存在变形发展或恶化表述，需优先复核。"
    else:
        summary += " 未识别到明确变形发展或恶化表述。"
    summary += " " + series_result["summary"]

    return {
        "trend_labels": labels,
        "trend_scores": [
            score + int(series_result["point_results"].get(str(row.get("monitor_point_code", "")), {}).get("severity", 0))
            for score, (_, row) in zip(scores, df.iterrows())
        ],
        "trend_distribution": counts,
        "deformation_trend_summary": summary,
        "deformation_points_detail": "\n".join(lines) if lines else "（未识别到明确恶化/发展点位）",
        "trend_evidence_codes": evidence_codes,
        "worsening_point_count": counts["恶化/发展"],
        "time_series_summary": series_result["summary"],
        "time_series_points_detail": series_result["detail"],
        "trend_forecast_summary": series_result["forecast_summary"],
        "trend_forecast_detail": series_result["forecast_detail"],
        "time_series_rain_summary": series_result.get("rain_summary", ""),
        "time_series_rain_detail": series_result.get("rain_detail", ""),
        "time_series_point_results": series_result["point_results"],
        "time_series_limitations": series_result["limitations"],
    }
