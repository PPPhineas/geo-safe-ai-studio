"""报告第三章「分类统计」图表(Plotly + kaleido)。

要点(见 docs/统计图表内容与技术栈.md):
    - 3.1 类型分布(环形/水平柱)、3.2 规模(按 小<中<大<特大 序数排序)、
      3.3 预警(红橙黄蓝语义配色,与地图一致)、3.4 隐患占比、3.5 威胁汇总(量纲不同,双轴);
    - 数值标签来自代码统计,不二次计算;空值类别保留可见;
    - layout.font.family="Microsoft YaHei";导出 scale=2,PNG。
"""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.config import get_settings

# 预警等级语义配色——charts 与 maps 共用,保证图/地图视觉一致。
WARNING_COLORS: dict[str, str] = {
    "红色": "#d62728",
    "橙色": "#ff7f0e",
    "黄色": "#ffd11a",
    "蓝色": "#1f77b4",
    "未定级": "#9aa0a6",
}


def _export(fig: go.Figure) -> bytes:
    settings = get_settings()
    fig.update_layout(
        font=dict(family=settings.chart_font_family, size=14),
        template="plotly_white",
        margin=dict(l=60, r=40, t=60, b=50),
    )
    return fig.to_image(format="png", scale=settings.export_scale, width=720, height=480)


def _nonzero_items(values: dict | None, order: tuple[str, ...] = ()) -> list[tuple[str, int]]:
    if not values:
        return []
    keys = list(order) if order else list(values)
    for key in values:
        if key not in keys:
            keys.append(key)
    items = []
    for key in keys:
        count = int(values.get(key, 0) or 0)
        if count > 0:
            items.append((key, count))
    return items


def _forecast_risk_counts(trend: dict | None) -> dict[str, int]:
    counts = {"高": 0, "中": 0, "低": 0, "不可预测": 0}
    for item in (trend or {}).get("time_series_point_results", {}).values():
        forecast = item.get("forecast") if isinstance(item, dict) else None
        level = forecast.get("level") if isinstance(forecast, dict) else None
        if level in counts:
            counts[level] += 1
    return counts


def _rain_intensity_counts(trend: dict | None) -> dict[str, int]:
    counts = {"大暴雨": 0, "暴雨": 0, "大雨": 0, "中雨": 0, "小雨": 0}
    for item in (trend or {}).get("time_series_point_results", {}).values():
        if not isinstance(item, dict):
            continue
        label = item.get("rain_intensity")
        if label in counts:
            counts[label] += 1
    return counts




def _line_candidates(trend: dict | None, limit: int = 5) -> list[tuple[str, dict, dict]]:
    items = []
    for code, result in (trend or {}).get("time_series_point_results", {}).items():
        if not isinstance(result, dict):
            continue
        series = result.get("preview_series")
        if not series or not series.get("points"):
            continue
        items.append((str(code), result, series))
    items.sort(key=lambda item: int(item[1].get("severity", 0)), reverse=True)
    if items:
        return items[:limit]
    fallback = []
    for item in (trend or {}).get("trend_index_series", [])[:limit]:
        if item.get("points"):
            fallback.append((str(item.get("code", "")), {"severity": 0}, item))
    return fallback


def _series_display_name(code: str, result: dict | None, series: dict | None) -> str:
    for source in (series, result):
        if not isinstance(source, dict):
            continue
        value = str(source.get("display_name") or source.get("monitor_point_name") or "").strip()
        if value:
            return value
    return str(code or "").strip()

def _apply_bottom_legend(fig: go.Figure) -> None:
    fig.update_layout(
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.24,
            xanchor="left",
            x=0,
            font=dict(size=11),
            itemwidth=70,
        ),
        margin=dict(l=70, r=40, t=80, b=150),
    )


def _render_key_point_trend_lines(trend: dict | None) -> bytes | None:
    candidates = _line_candidates(trend)
    if not candidates:
        return None
    fig = go.Figure()
    for code, result, series in candidates:
        points = series.get("points") or []
        fig.add_trace(go.Scatter(
            x=[p["time"] for p in points],
            y=[p["value"] for p in points],
            mode="lines+markers",
            name=f"{_series_display_name(code, result, series)} {series.get('label', '')}",
        ))
    y_title = "趋势关注指数" if candidates and candidates[0][2].get("label") == "趋势关注指数" else "监测值"
    title = "5.4 重点点位趋势关注指数折线" if y_title == "趋势关注指数" else "5.4 重点点位变形趋势折线"
    fig.update_layout(title=title, xaxis_title="时间", yaxis_title=y_title)
    _apply_bottom_legend(fig)
    return _export(fig)


def _render_rain_deformation_timeseries(trend: dict | None) -> bytes | None:
    candidates = [item for item in _line_candidates(trend, limit=12) if item[1].get("daily_rainfall")]
    if not candidates:
        return None
    code, result, series = candidates[0]
    rain = result.get("daily_rainfall") or []
    points = series.get("points") or []
    if not rain or not points:
        return None
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=[p["date"] for p in rain],
        y=[p["rainfall_mm"] for p in rain],
        name=f"{_series_display_name(code, result, series)} 日雨量(mm)",
        marker_color="#4c78a8",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=[p["time"] for p in points],
        y=[p["value"] for p in points],
        mode="lines+markers",
        name=f"{_series_display_name(code, result, series)} {series.get('label', '变形指标')}",
        line=dict(color="#d62728", width=2),
    ), secondary_y=True)
    fig.update_yaxes(title_text="日雨量(mm)", secondary_y=False)
    fig.update_yaxes(title_text="变形监测值", secondary_y=True)
    fig.update_layout(title="5.4 雨量-变形时序对照", xaxis_title="时间")
    _apply_bottom_legend(fig)
    return _export(fig)

def _render_trend_charts(trend: dict | None) -> dict[str, bytes]:
    out: dict[str, bytes] = {}

    trend_items = _nonzero_items(
        (trend or {}).get("trend_distribution"),
        ("恶化/发展", "稳定/趋稳", "缓解/减弱", "未填报"),
    )
    if trend_items:
        colors = {
            "恶化/发展": "#d62728",
            "稳定/趋稳": "#2ca02c",
            "缓解/减弱": "#1f77b4",
            "未填报": "#9aa0a6",
        }
        fig = go.Figure(go.Bar(
            x=[name for name, _ in trend_items],
            y=[value for _, value in trend_items],
            marker_color=[colors.get(name, "#4c78a8") for name, _ in trend_items],
            text=[value for _, value in trend_items],
            textposition="outside",
        ))
        fig.update_layout(title="5.4 发展趋势状态分布", xaxis_title="趋势状态", yaxis_title="点位数")
        out["chart_trend_distribution"] = _export(fig)

    forecast_items = _nonzero_items(_forecast_risk_counts(trend), ("高", "中", "低", "不可预测"))
    if forecast_items:
        colors = {"高": "#d62728", "中": "#f58518", "低": "#2ca02c", "不可预测": "#9aa0a6"}
        fig = go.Figure(go.Bar(
            x=[name for name, _ in forecast_items],
            y=[value for _, value in forecast_items],
            marker_color=[colors.get(name, "#4c78a8") for name, _ in forecast_items],
            text=[value for _, value in forecast_items],
            textposition="outside",
        ))
        fig.update_layout(title="5.4 短期预测风险分布", xaxis_title="预测风险", yaxis_title="点位数")
        out["chart_trend_forecast_risk"] = _export(fig)

    rain_items = _nonzero_items(_rain_intensity_counts(trend), ("大暴雨", "暴雨", "大雨", "中雨", "小雨"))
    if rain_items:
        colors = {
            "大暴雨": "#7f0000",
            "暴雨": "#d62728",
            "大雨": "#f58518",
            "中雨": "#1f77b4",
            "小雨": "#9ecae1",
        }
        fig = go.Figure(go.Pie(
            labels=[name for name, _ in rain_items],
            values=[value for _, value in rain_items],
            hole=0.45,
            marker_colors=[colors.get(name, "#4c78a8") for name, _ in rain_items],
        ))
        fig.update_layout(title="5.4 雨情强度分布")
        out["chart_rain_intensity_distribution"] = _export(fig)

    line_chart = _render_key_point_trend_lines(trend)
    if line_chart is not None:
        out["chart_key_point_trend_lines"] = line_chart

    rain_deformation = _render_rain_deformation_timeseries(trend)
    if rain_deformation is not None:
        out["chart_rain_deformation_timeseries"] = rain_deformation

    return out


def render_charts(stats: dict, trend: dict | None = None) -> dict[str, bytes]:
    """渲染统计图表,返回 {占位符名: PNG 字节}。"""
    out: dict[str, bytes] = {}

    # 3.1 灾害类型分布
    types = stats["type_distribution"]
    if len(types) <= 5:
        fig = go.Figure(go.Pie(labels=list(types), values=list(types.values()), hole=0.4))
    else:
        items = sorted(types.items(), key=lambda kv: kv[1])
        fig = go.Figure(go.Bar(x=[v for _, v in items], y=[k for k, _ in items], orientation="h"))
    fig.update_layout(title="3.1 灾害类型分布")
    out["chart_type_distribution"] = _export(fig)

    # 3.2 规模等级分布(固定序)
    scale = stats["scale_distribution"]
    fig = go.Figure(go.Bar(x=list(scale), y=list(scale.values()), marker_color="#4c78a8",
                           text=list(scale.values()), textposition="outside"))
    fig.update_layout(title="3.2 规模等级分布", xaxis_title="规模", yaxis_title="点位数")
    out["chart_scale_distribution"] = _export(fig)

    # 3.3 预警等级分布(语义配色)
    warn = stats["warning_level_distribution"]
    fig = go.Figure(go.Bar(
        x=list(warn), y=list(warn.values()),
        marker_color=[WARNING_COLORS.get(k, "#9aa0a6") for k in warn],
        text=list(warn.values()), textposition="outside",
    ))
    fig.update_layout(title="3.3 预警等级分布", xaxis_title="预警等级", yaxis_title="点位数")
    out["chart_warning_distribution"] = _export(fig)

    # 3.4 隐患识别情况
    hidden = stats["hidden_danger_count"]
    non_hidden = stats["point_count"] - hidden
    fig = go.Figure(go.Pie(labels=["隐患识别", "非隐患"], values=[hidden, non_hidden], hole=0.5,
                           marker_colors=["#d62728", "#bcc5d4"]))
    fig.update_layout(title="3.4 隐患识别占比")
    out["chart_hidden_danger_ratio"] = _export(fig)

    # 3.5 威胁要素汇总(双轴:人数/户数 vs 财产)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=["威胁人数", "威胁户数"],
                         y=[stats["threaten_population_total"], stats["threaten_residents_total"]],
                         name="人数/户数", marker_color="#4c78a8"), secondary_y=False)
    fig.add_trace(go.Bar(x=["威胁财产(万元)"], y=[stats["threaten_assets_total"]],
                         name="财产(万元)", marker_color="#f58518"), secondary_y=True)
    fig.update_yaxes(title_text="人数 / 户数", secondary_y=False)
    fig.update_yaxes(title_text="财产(万元)", secondary_y=True)
    fig.update_layout(title="3.5 威胁要素汇总")
    out["chart_threat_summary"] = _export(fig)

    out.update(_render_trend_charts(trend))
    return out






