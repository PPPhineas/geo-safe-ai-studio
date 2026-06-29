from __future__ import annotations

from datetime import datetime, timedelta

from app.pipeline.warning_history import analyze_warning_history


def test_analyze_warning_history_summarizes_records() -> None:
    result = analyze_warning_history(
        {
            "enabled": True,
            "lookback_days": 90,
            "records": [
                {
                    "warning_time": datetime.now(),
                    "warning_level": "4",
                    "warning_status": "1",
                    "is_false_alarm": "2",
                    "monitor_point_code": "PT001",
                },
                {
                    "warning_time": datetime.now() - timedelta(days=2),
                    "warning_level": "2",
                    "warning_status": "2",
                    "is_false_alarm": "1",
                    "monitor_point_code": "PT001",
                },
            ],
        }
    )

    assert "2 条预警记录" in result["warning_history_summary"]
    assert "最高红色" in result["warning_history_detail"]
