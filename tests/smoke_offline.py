"""离线冒烟:不连 CH / LLM,验证 清洗→统计→空间→装配→提示词→校验→渲染 全链路逻辑。

运行:python -m tests.smoke_offline
"""

from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.api.schemas import PolygonGeometry
from app.pipeline.assembly import assemble_placeholders
from app.pipeline.cleaning import clean_records
from app.pipeline.regions import RegionMaps, enrich_regions, region_from_code
from app.pipeline.spatial import analyze_spatial
from app.pipeline.statistics import compute_statistics
from app.pipeline.validation import validate_judgement
from app.prompts.risk_judgement import build_user_prompt
from app.render.charts import render_charts
from app.render.maps import render_map
from app.render.report import render_report

# 合成 8 条记录:含单位字符串、空值、连片簇(120.10E/30.20N 附近)。
RECORDS = [
    {"monitor_point_code": "PT001", "monitor_point_name": "西坡滑坡", "monitor_point_type": "滑坡",
     "province_name": "浙江省", "city_name": "杭州市", "county_name": "西湖区",
     "longitude": "120.1000", "latitude": "30.2000", "scale": "大", "warning_level": "红色预警",
     "threaten_population": "120人", "threaten_residents": "30", "threaten_assets": 850.5,
     "avg_slope": "35度", "lithology": "砂岩", "induce_factors": "降雨、人类工程活动",
     "current_status": "近期变形加剧，裂缝扩大", "is_hidden_danger": 1, "is_hex": 0},
    {"monitor_point_code": "PT002", "monitor_point_name": "东沟泥石流", "monitor_point_type": "泥石流",
     "longitude": "120.1010", "latitude": "30.2008", "scale": "中", "warning_level": "橙色",
     "threaten_population": "60", "threaten_residents": "15", "threaten_assets": 300,
     "avg_slope": "28", "lithology": "砂岩", "induce_factors": "降雨",
     "current_status": "稳定", "is_hidden_danger": 0, "is_hex": 0},
    {"monitor_point_code": "PT003", "monitor_point_name": "北崖崩塌", "monitor_point_type": "崩塌",
     "longitude": "120.1005", "latitude": "30.2012", "scale": "特大", "warning_level": "红色",
     "threaten_population": "200", "threaten_residents": "50", "threaten_assets": 1500,
     "avg_slope": "55", "lithology": "灰岩", "induce_factors": "降雨、风化",
     "current_status": "持续变形，趋势恶化", "is_hidden_danger": 1, "is_hex": 0},
    {"monitor_point_code": "PT004", "monitor_point_name": "", "monitor_point_type": "滑坡",
     "longitude": "120.1015", "latitude": "30.2003", "scale": "", "warning_level": "",
     "threaten_population": "", "threaten_residents": None, "threaten_assets": None,
     "avg_slope": "120", "lithology": "", "induce_factors": "",
     "current_status": "", "is_hidden_danger": None, "is_hex": 0},
    {"monitor_point_code": "PT005", "monitor_point_name": "南村滑坡", "monitor_point_type": "滑坡",
     "longitude": "120.1500", "latitude": "30.2500", "scale": "小", "warning_level": "黄色",
     "threaten_population": "10", "threaten_residents": "3", "threaten_assets": 50,
     "avg_slope": "22", "lithology": "页岩", "induce_factors": "人类工程活动",
     "current_status": "基本稳定", "is_hidden_danger": 0, "is_hex": 0},
    {"monitor_point_code": "PT006", "monitor_point_name": "孤立点", "monitor_point_type": "地面塌陷",
     "longitude": "120.2000", "latitude": "30.1500", "scale": "中", "warning_level": "蓝色",
     "threaten_population": "5", "threaten_residents": "2", "threaten_assets": 20,
     "avg_slope": "15", "lithology": "黏土", "induce_factors": "地下水开采",
     "current_status": "缓慢沉降", "is_hidden_danger": 0, "is_hex": 0},
    {"monitor_point_code": "PT007", "monitor_point_name": "簇内点A", "monitor_point_type": "滑坡",
     "longitude": "120.1008", "latitude": "30.2005", "scale": "大", "warning_level": "橙色",
     "threaten_population": "80", "threaten_residents": "20", "threaten_assets": 600,
     "avg_slope": "40", "lithology": "砂岩", "induce_factors": "降雨",
     "current_status": "变形发展中", "is_hidden_danger": 1, "is_hex": 0},
    {"monitor_point_code": "PT008", "monitor_point_name": "簇内点B", "monitor_point_type": "崩塌",
     "longitude": "120.1012", "latitude": "30.2010", "scale": "中", "warning_level": "黄色",
     "threaten_population": "40", "threaten_residents": "10", "threaten_assets": 200,
     "avg_slope": "48", "lithology": "灰岩", "induce_factors": "风化、降雨",
     "current_status": "稳定", "is_hidden_danger": 0, "is_hex": 0},
]

GEOMETRY = PolygonGeometry(
    kind="polygon",
    coordinates=[(120.08, 30.14), (120.22, 30.14), (120.22, 30.27), (120.08, 30.27)],
)


def _stub_judgement(valid_codes) -> dict:
    codes = sorted(valid_codes)
    return {
        "overall_risk": {"level": "高", "basis": "区域内红色预警点位集中，存在连片隐患带。"},
        "dominant_hazard": {
            "type": "滑坡",
            "cause_analysis": "以砂岩岩性为主，结合填报坡度较陡及降雨诱发，滑坡风险突出。",
            "source_note": "（基于填报值，未经地形数据校验）",
        },
        "common_induce_factors": ["降雨", "人类工程活动", "风化"],
        "trend": {"judgment": "总体呈变形加剧趋势。", "evidence_points": codes[:2]},
        "key_points": [
            {"monitor_point_code": codes[0], "reason": "红色预警且规模大", "suggestion": "立即加密监测并预置撤离方案。"},
        ],
        "recommendations": {
            "urgent": ["对红色预警点位立即排查"],
            "near_term": ["雨季前完成隐患治理设计"],
            "routine": ["常态化巡查与监测"],
        },
        "data_limitations": ["未接入 DEM，地形为填报值。"],
    }


def main() -> None:
    df, missing = clean_records(RECORDS)
    print(f"[clean] rows={len(df)} missing={missing}")
    assert len(df) == 8

    # 省市县反推 / 富集(maps=None:仅用库字段,缺失回落「未知」)
    df = enrich_regions(df, maps=None)
    assert {"province_name", "city_name", "county_name"} <= set(df.columns)
    pt001 = df[df["monitor_point_code"] == "PT001"].iloc[0]
    assert pt001["province_name"] == "浙江省" and pt001["county_name"] == "西湖区", "库字段优先失败"
    pt002 = df[df["monitor_point_code"] == "PT002"].iloc[0]
    assert pt002["province_name"] == "未知", "无库字段应回落未知"
    # code 反推(自带小对照表):前6位行政区划码,脏 __ 前缀先剥离
    fake = RegionMaps({"610000": "陕西省"}, {"610700": "宝鸡市"}, {"610727": "麟游县"})
    assert region_from_code("610727010572", fake) == ("陕西省", "宝鸡市", "麟游县")
    assert region_from_code("__610727010572", fake) == ("陕西省", "宝鸡市", "麟游县")
    assert region_from_code("PT001", fake) == (None, None, None)
    print(f"[regions] 三列就位;PT001={pt001['province_name']}/{pt001['city_name']}/{pt001['county_name']};code反推 OK")

    stats = compute_statistics(df)
    print(f"[stats] {stats['type_distribution_str']} | 威胁人数={stats['threaten_population_total']}")
    assert stats["threaten_population_total"] == 120 + 60 + 200 + 0 + 10 + 5 + 80 + 40

    spatial = analyze_spatial(df, GEOMETRY)
    print(f"[spatial] {spatial['cluster_summary'][:60]}...")
    print(f"[spatial] extent={spatial['affected_extent_summary']}")

    placeholders = assemble_placeholders(stats, spatial, df, missing)
    placeholders["report_id"] = "smoke-offline"
    placeholders["generate_time"] = "2026-06-08 00:00:00"
    print(f"[assembly] 重点点位={placeholders['key_point_codes']}")

    user_prompt = build_user_prompt(placeholders)
    assert "{{" not in user_prompt, "占位符未完全注入"
    print(f"[prompt] user 长度={len(user_prompt)} 字符,无残留占位符 OK")

    valid_codes = set(df["monitor_point_code"])
    judgement = _stub_judgement(valid_codes)
    verdict = validate_judgement(judgement, valid_codes)
    print(f"[validate] ok={verdict['ok']} errors={verdict['errors']}")
    assert verdict["ok"], verdict["errors"]

    # 反例:圈外编号 + 缺来源标注 应判不合格
    bad = _stub_judgement(valid_codes)
    bad["key_points"][0]["monitor_point_code"] = "PT999"
    bad["dominant_hazard"]["source_note"] = ""
    bad_verdict = validate_judgement(bad, valid_codes)
    assert not bad_verdict["ok"], "反例应判不合格"
    print(f"[validate-neg] 反例正确判不合格:{bad_verdict['errors']}")

    charts = render_charts(stats)
    for k, v in charts.items():
        assert v and len(v) > 1000, k
    print(f"[charts] {list(charts)} 全部非空 PNG OK")

    figures = {k: f"/static/figures/smoke/{k}.png" for k in charts}
    try:
        m = render_map(spatial, df, GEOMETRY)
        figures["map_figure"] = "/static/figures/smoke/map_figure.png"
        print(f"[map] PNG bytes={len(m)} OK")
    except Exception as exc:  # 内网无瓦片时可能失败
        print(f"[map] 渲染失败(内网无外网?): {type(exc).__name__}: {exc}")

    report = render_report(placeholders, judgement, figures)
    assert "{{" not in report, "报告占位符未完全替换"
    assert "120" in report  # 代码数字
    assert sorted(valid_codes)[0] in report
    print(f"[report] 长度={len(report)} 字符,占位符全替换,含代码数字与编号 OK")

    out = "output/smoke_report.md"
    import pathlib
    pathlib.Path("output").mkdir(exist_ok=True)
    pathlib.Path(out).write_text(report, encoding="utf-8")
    print(f"\n冒烟通过。报告已写入 {out}")


if __name__ == "__main__":
    main()
