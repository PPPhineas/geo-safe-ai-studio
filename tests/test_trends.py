from __future__ import annotations

import pandas as pd
from datetime import datetime, timedelta

from app.pipeline.timeseries import classify_device_model
from app.pipeline.trends import analyze_deformation_trends, classify_deformation_trend


def test_classify_deformation_trend_handles_negation_and_worsening() -> None:
    assert classify_deformation_trend("近期变形加剧，裂缝扩大")[0] == "恶化/发展"
    assert classify_deformation_trend("无明显变形，基本稳定")[0] == "稳定/趋稳"
    assert classify_deformation_trend("变形减缓，趋于收敛")[0] == "缓解/减弱"
    assert classify_deformation_trend("停止发展")[0] == "缓解/减弱"
    assert classify_deformation_trend("")[0] == "未填报"


def test_classify_device_model_from_sensor_type_and_name() -> None:
    assert classify_device_model("L3_YL_1", "雨量计") == "rain_gauge"
    assert classify_device_model("L1_LF_1", "裂缝计") == "crack_meter"
    assert classify_device_model("L1_GNSS_1", "GNSS地表位移") == "gnss_displacement"
    assert classify_device_model("L2_AE_1", "声发射") == "acoustic"


def test_analyze_deformation_trends_outputs_summary_and_evidence() -> None:
    df = pd.DataFrame(
        [
            {
                "monitor_point_code": "PT001",
                "monitor_point_name": "后缘裂缝监测点",
                "current_status": "持续变形，趋势恶化",
                "threaten_population": 100,
                "threaten_assets": 500,
            },
            {
                "monitor_point_code": "PT002",
                "monitor_point_name": "前缘稳定监测点",
                "current_status": "基本稳定",
                "threaten_population": 10,
                "threaten_assets": 20,
            },
            {
                "monitor_point_code": "PT003",
                "monitor_point_name": "未填报监测点",
                "current_status": "",
                "threaten_population": 0,
                "threaten_assets": 0,
            },
        ]
    )

    trend = analyze_deformation_trends(df)

    assert trend["trend_distribution"]["恶化/发展"] == 1
    assert trend["trend_distribution"]["稳定/趋稳"] == 1
    assert trend["trend_distribution"]["未填报"] == 1
    assert trend["trend_evidence_codes"] == ["PT001"]
    assert "[PT001]" in trend["deformation_points_detail"]
    assert trend["trend_index_series"][0]["code"] == "PT001"
    assert trend["trend_index_series"][0]["display_name"] == "后缘裂缝监测点"
    assert trend["trend_index_series"][0]["label"] == "趋势关注指数"


def test_analyze_deformation_trends_uses_time_series_evidence() -> None:
    now = datetime.now()
    df = pd.DataFrame(
        [
            {
                "monitor_point_code": "PT001",
                "monitor_point_name": "后缘裂缝监测点",
                "current_status": "基本稳定",
                "threaten_population": 100,
                "threaten_assets": 500,
            }
        ]
    )
    time_series = {
        "enabled": True,
        "lookback_days": 30,
        "sensor_count": 2,
        "observation_count": 8,
        "limitations": [],
        "series": {
            "PT001": [
                {
                    "kind": "deformation",
                    "source": "L1",
                    "device_model": "gnss_displacement",
                    "metric": "dispsX",
                    "time": now - timedelta(days=3),
                    "value": 0.0,
                },
                {
                    "kind": "deformation",
                    "source": "L1",
                    "device_model": "gnss_displacement",
                    "metric": "dispsX",
                    "time": now - timedelta(days=2),
                    "value": 1.0,
                },
                {
                    "kind": "deformation",
                    "source": "L1",
                    "device_model": "gnss_displacement",
                    "metric": "dispsX",
                    "time": now - timedelta(days=1),
                    "value": 7.0,
                },
                {
                    "kind": "deformation",
                    "source": "L1",
                    "device_model": "gnss_displacement",
                    "metric": "dispsX",
                    "time": now,
                    "value": 15.0,
                },
                {
                    "kind": "rainfall",
                    "source": "L3",
                    "device_model": "rain_gauge",
                    "metric": "value",
                    "time": now - timedelta(hours=20),
                    "value": 18.0,
                },
                {
                    "kind": "rainfall",
                    "source": "L3",
                    "device_model": "rain_gauge",
                    "metric": "value",
                    "time": now - timedelta(hours=10),
                    "value": 12.0,
                },
                {
                    "kind": "rainfall",
                    "source": "L3",
                    "device_model": "rain_gauge",
                    "metric": "value",
                    "time": now - timedelta(hours=5),
                    "value": 8.0,
                },
                {
                    "kind": "rainfall",
                    "source": "L3",
                    "device_model": "rain_gauge",
                    "metric": "value",
                    "time": now,
                    "value": 3.0,
                },
            ]
        },
    }

    trend = analyze_deformation_trends(df, time_series)

    assert trend["time_series_point_results"]["PT001"]["severity"] >= 3
    assert "PT001" in trend["trend_evidence_codes"]
    assert "GNSS/地表位移.dispsX" in trend["deformation_points_detail"]
    assert trend["time_series_point_results"]["PT001"]["forecast"]["level"] == "高"
    assert trend["time_series_point_results"]["PT001"]["display_name"] == "后缘裂缝监测点"
    assert trend["time_series_point_results"]["PT001"]["preview_series"]["display_name"] == "后缘裂缝监测点"
    assert trend["time_series_point_results"]["PT001"]["preview_series"]["points"]
    assert trend["time_series_point_results"]["PT001"]["preview_series"]["metric"] == "dispsX"
    assert "PT001" in trend["trend_forecast_detail"]
    assert "预计未来" in trend["trend_forecast_detail"]





