from __future__ import annotations

from datetime import date

import pandas as pd

from app.pipeline.timeseries import fetch_time_series_for_points


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        params = params or {}
        self.calls.append((sql, params))
        if "dwd_monitor_sensor_info_view" in sql:
            rows = []
            for name in params.get("names", []):
                rows.append({
                    "sensor_code": f"L1_{name}",
                    "sensor_type": "L1_GNSS",
                    "sensor_type_name": "GNSS地表位移",
                    "monitor_point_name": name,
                })
                rows.append({
                    "sensor_code": f"L2_{name}",
                    "sensor_type": "L2_AE",
                    "sensor_type_name": "声发射",
                    "monitor_point_name": name,
                })
            return rows
        if "datapointsL1" in sql:
            return [
                {"SensorCode": code, "day": date(2026, 6, 28), "dispsX_avg": 1.0, "n": 1}
                for code in params.get("sensor_codes", [])
            ]
        if "datapointsL2" in sql:
            return [
                {"SensorCode": code, "day": date(2026, 6, 28), "value_avg": 2.0, "n": 1}
                for code in params.get("sensor_codes", [])
            ]
        return []


def test_timeseries_reads_all_points_and_all_levels_without_mode_switch() -> None:
    df = pd.DataFrame([
        {"monitor_point_code": "P1", "monitor_point_name": "高风险点", "warning_level": "红色", "scale": "大型"},
        {"monitor_point_code": "P2", "monitor_point_name": "低风险点", "warning_level": "蓝色", "scale": "小型"},
    ])
    client = FakeClickHouseClient()

    bundle = fetch_time_series_for_points(df, client=client, lookback_days=3)

    assert "mode" not in bundle
    assert bundle["point_count"] == 2
    assert bundle["source_point_count"] == 2
    assert bundle["sensor_count"] == 4
    assert set(bundle["series"]) == {"P1", "P2"}
    assert any("datapointsL1" in sql for sql, _ in client.calls)
    assert any("datapointsL2" in sql for sql, _ in client.calls)
