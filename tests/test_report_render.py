from __future__ import annotations

import unittest

from app.render.report import render_report


class ReportRenderTests(unittest.TestCase):
    def test_key_points_table_separator_matches_header_columns(self) -> None:
        placeholders = {
            "report_id": "rpt_test",
            "generate_time": "2026-06-17 00:00:00",
            "zone_geometry_desc": "测试多边形",
            "zone_area": "1 平方千米",
            "point_count": 1,
            "type_distribution": "滑坡 1 个",
            "scale_distribution": "大型 1 个",
            "warning_level_distribution": "红色 1 个",
            "hidden_danger_ratio": "1/1",
            "threaten_population_total": 10,
            "threaten_residents_total": 2,
            "threaten_assets_total": 100,
            "point_list_rows": "| 1 | 623023010102 | 测试点 | 测试区 | 滑坡 | 大型 | 红色 | 10 | 100 | ★ |",
            "cluster_summary": "无连片带",
            "hotspot_summary": "无热点区",
            "affected_extent_summary": "测试范围",
            "missing_value_summary": "无",
            "appendix_full_table": "无",
        }
        judgement = {
            "overall_risk": {"level": "高", "basis": "红色预警。"},
            "dominant_hazard": {"type": "滑坡", "cause_analysis": "降雨诱发。", "source_note": ""},
            "common_induce_factors": ["降雨"],
            "trend": {"judgment": "需关注。", "evidence_points": ["623023010102"]},
            "key_points": [
                {
                    "monitor_point_code": "623023010102",
                    "reason": "红色预警。",
                    "suggestion": "加密监测。",
                }
            ],
            "recommendations": {"urgent": [], "near_term": [], "routine": []},
            "data_limitations": [],
        }

        report = render_report(placeholders, judgement, {})
        lines = report.splitlines()
        header_index = lines.index("| 国家编号 | 关注原因 | 针对性建议 |")

        self.assertEqual(lines[header_index + 1], "|---|---|---|")



    def test_trend_chart_placeholders_render_as_images(self) -> None:
        placeholders = {
            "report_id": "rpt_test",
            "generate_time": "2026-06-17 00:00:00",
            "zone_geometry_desc": "测试多边形",
            "zone_area": "1 平方千米",
            "point_count": 1,
            "type_distribution": "滑坡 1 个",
            "scale_distribution": "大型 1 个",
            "warning_level_distribution": "红色 1 个",
            "hidden_danger_ratio": "1/1",
            "threaten_population_total": 10,
            "threaten_residents_total": 2,
            "threaten_assets_total": 100,
            "point_list_rows": "| 1 | 623023010102 | 测试点 | 测试区 | 滑坡 | 大型 | 红色 | 10 | 100 | ★ |",
            "cluster_summary": "无连片带",
            "hotspot_summary": "无热点区",
            "affected_extent_summary": "测试范围",
            "missing_value_summary": "无",
            "appendix_full_table": "无",
        }
        judgement = {
            "overall_risk": {"level": "高", "basis": "红色预警。"},
            "dominant_hazard": {"type": "滑坡", "cause_analysis": "降雨诱发。", "source_note": ""},
            "common_induce_factors": ["降雨"],
            "trend": {"judgment": "需关注。", "evidence_points": ["623023010102"]},
            "key_points": [],
            "recommendations": {"urgent": [], "near_term": [], "routine": []},
            "data_limitations": [],
        }
        figures = {
            "chart_trend_distribution": "/static/figures/rpt_test/chart_trend_distribution.png",
            "chart_trend_forecast_risk": "/static/figures/rpt_test/chart_trend_forecast_risk.png",
            "chart_rain_intensity_distribution": "/static/figures/rpt_test/chart_rain_intensity_distribution.png",
            "chart_key_point_trend_lines": "/static/figures/rpt_test/chart_key_point_trend_lines.png",
            "chart_rain_deformation_timeseries": "/static/figures/rpt_test/chart_rain_deformation_timeseries.png",
        }

        report = render_report(placeholders, judgement, figures)

        self.assertIn("![chart_trend_distribution](/static/figures/rpt_test/chart_trend_distribution.png)", report)
        self.assertIn("![chart_trend_forecast_risk](/static/figures/rpt_test/chart_trend_forecast_risk.png)", report)
        self.assertIn("![chart_rain_intensity_distribution](/static/figures/rpt_test/chart_rain_intensity_distribution.png)", report)
        self.assertIn("![chart_key_point_trend_lines](/static/figures/rpt_test/chart_key_point_trend_lines.png)", report)
        self.assertIn("![chart_rain_deformation_timeseries](/static/figures/rpt_test/chart_rain_deformation_timeseries.png)", report)
if __name__ == "__main__":
    unittest.main()




