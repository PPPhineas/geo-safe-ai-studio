from __future__ import annotations

from app.pipeline.a2ui_builder import build_risk_a2ui


def test_build_risk_a2ui_includes_trend_chart_components() -> None:
    stats = {
        "point_count": 3,
        "type_distribution": {"滑坡": 3},
        "scale_distribution": {"小型": 3},
        "warning_level_distribution": {"蓝色": 3},
        "hidden_danger_count": 1,
        "threaten_population_total": 10,
        "threaten_residents_total": 2,
        "threaten_assets_total": 30,
    }
    trend = {
        "trend_distribution": {"恶化/发展": 1, "稳定/趋稳": 1, "缓解/减弱": 0, "未填报": 1},
        "time_series_point_results": {
            "PT001": {
                "severity": 3,
                "display_name": "后缘裂缝监测点",
                "monitor_point_name": "后缘裂缝监测点",
                "monitor_point_code": "PT001",
                "forecast": {"level": "高"},
                "rain_intensity": "暴雨",
                "daily_rainfall": [{"date": "2026-06-27", "rainfall_mm": 10.0}],
                "preview_series": {
                    "label": "GNSS/地表位移.dispsX",
                    "display_name": "后缘裂缝监测点",
                    "monitor_point_name": "后缘裂缝监测点",
                    "monitor_point_code": "PT001",
                    "points": [
                        {"time": "2026-06-27T00:00:00", "value": 1.0},
                        {"time": "2026-06-28T00:00:00", "value": 5.0},
                    ],
                },
            },
            "PT002": {"severity": 1, "forecast": {"level": "中"}, "rain_intensity": "中雨"},
        },
    }

    surface = build_risk_a2ui("rpt", {}, stats, trend=trend)

    assert surface is not None
    components = {item.id: item for item in surface.components}
    assert components["chart_trend_distribution"].props["categories"] == ["恶化/发展", "稳定/趋稳", "未填报"]
    assert components["chart_trend_forecast_risk"].props["categories"] == ["高", "中"]
    assert components["chart_rain_intensity_distribution"].props["data"] == [
        {"name": "暴雨", "value": 1},
        {"name": "中雨", "value": 1},
    ]
    assert components["chart_key_point_trend_lines"].props["chartType"] == "line"
    line_series = components["chart_key_point_trend_lines"].props["series"][0]
    assert line_series["name"].startswith("后缘裂缝监测点")
    assert line_series["monitorPointCode"] == "PT001"
    assert components["chart_rain_deformation_timeseries"].props["chartType"] == "barLine"
    rain_chart = components["chart_rain_deformation_timeseries"].props
    assert rain_chart["bars"][0]["name"].startswith("后缘裂缝监测点")
    assert rain_chart["lines"][0]["monitorPointName"] == "后缘裂缝监测点"





