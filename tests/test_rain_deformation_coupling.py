from __future__ import annotations

from datetime import datetime, timedelta

from app.pipeline.rain_deformation_coupling import analyze_rain_deformation_coupling


def test_analyze_rain_deformation_coupling_detects_lag_response() -> None:
    now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    observations = []
    rain_values = [0, 10, 20, 30]
    deformation_values = [0, 1, 11, 31]
    for i, rain in enumerate(rain_values):
        observations.append(
            {
                "device_model": "rain_gauge",
                "metric": "value",
                "time": now + timedelta(days=i),
                "value": rain,
            }
        )
    for i, deformation in enumerate(deformation_values):
        observations.append(
            {
                "device_model": "gnss_displacement",
                "metric": "dispsX",
                "time": now + timedelta(days=i + 1),
                "value": deformation,
            }
        )

    result = analyze_rain_deformation_coupling({"enabled": True, "series": {"PT001": observations}})

    assert "识别到" in result["rain_deformation_summary"]
    assert "PT001" in result["rain_deformation_detail"]
