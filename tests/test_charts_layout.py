from __future__ import annotations

from app.render import charts


def _trend_payload() -> dict:
    return {
        "time_series_point_results": {
            "PT001": {
                "severity": 3,
                "display_name": "后缘裂缝监测点",
                "daily_rainfall": [{"date": "2026-06-27", "rainfall_mm": 10.0}],
                "preview_series": {
                    "label": "GNSS/地表位移.dispsX",
                    "display_name": "后缘裂缝监测点",
                    "points": [
                        {"time": "2026-06-27T00:00:00", "value": 1.0},
                        {"time": "2026-06-28T00:00:00", "value": 5.0},
                    ],
                },
            }
        }
    }


def test_trend_line_chart_uses_bottom_horizontal_legend(monkeypatch) -> None:
    captured = {}

    def fake_export(fig):
        captured["fig"] = fig
        return b"png"

    monkeypatch.setattr(charts, "_export", fake_export)

    assert charts._render_key_point_trend_lines(_trend_payload()) == b"png"

    layout = captured["fig"].layout
    assert layout.legend.orientation == "h"
    assert layout.legend.y < 0
    assert layout.margin.b >= 140


def test_rain_deformation_chart_uses_bottom_horizontal_legend(monkeypatch) -> None:
    captured = {}

    def fake_export(fig):
        captured["fig"] = fig
        return b"png"

    monkeypatch.setattr(charts, "_export", fake_export)

    assert charts._render_rain_deformation_timeseries(_trend_payload()) == b"png"

    layout = captured["fig"].layout
    assert layout.legend.orientation == "h"
    assert layout.legend.y < 0
    assert layout.margin.b >= 140
