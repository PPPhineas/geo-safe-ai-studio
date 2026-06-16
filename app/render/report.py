"""报告拼装:按成稿模板填充占位符。

模板见 docs/灾圈监测点风险研判_报告成稿模板.md:
    {{代码占位符}} 由确定性统计填充、{{研判.字段}} 来自 AI 研判 JSON。
红线:所有数字来自代码统计、所有研判文字来自 AI;最终稿数字以代码值为准覆盖校对(铁律 1 / 校验 3)。
"""

from __future__ import annotations

from pathlib import Path

_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "灾圈监测点风险研判_报告成稿模板.md"
)
_START_MARKER = "# 灾圈地质灾害风险分析报告"
_END_MARKER = "### 渲染占位符索引"


def _load_template() -> str:
    text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    start = text.find(_START_MARKER)
    if start != -1:
        text = text[start:]
    end = text.find(_END_MARKER)
    if end != -1:
        text = text[:end].rstrip().rstrip("-").rstrip()
    return text


def _as_lines(items, prefix: str = "- ") -> str:
    if not items:
        return "（无）"
    if isinstance(items, str):
        return items
    return "\n".join(f"{prefix}{it}" for it in items)


def _inline(items) -> str:
    if not items:
        return "（无）"
    if isinstance(items, str):
        return items
    return "、".join(str(it) for it in items)


def _key_points_rows(judgement: dict) -> str:
    rows = []
    for kp in judgement.get("key_points", []) or []:
        if not isinstance(kp, dict):
            continue
        rows.append(
            f"| {kp.get('monitor_point_code', '')} | {kp.get('reason', '')} | {kp.get('suggestion', '')} |"
        )
    return "\n".join(rows) if rows else "| — | 本次研判未列出重点点位 | — |"


def _img(figures: dict[str, str], key: str) -> str:
    url = figures.get(key)
    return f"![{key}]({url})" if url else f"（图件 {key} 未生成）"


def render_report(placeholders: dict, judgement: dict, figures: dict[str, str]) -> str:
    """拼装最终报告正文(Markdown)。数字以代码值(placeholders)覆盖。"""
    text = _load_template()
    j = judgement or {}
    overall = j.get("overall_risk", {}) if isinstance(j.get("overall_risk"), dict) else {}
    dh = j.get("dominant_hazard", {}) if isinstance(j.get("dominant_hazard"), dict) else {}
    trend = j.get("trend", {}) if isinstance(j.get("trend"), dict) else {}
    recs = j.get("recommendations", {}) if isinstance(j.get("recommendations"), dict) else {}

    repl = {
        # ---- 元信息 + 代码占位符 ----
        "report_id": placeholders.get("report_id", ""),
        "generate_time": placeholders.get("generate_time", ""),
        "zone_geometry_desc": placeholders["zone_geometry_desc"],
        "zone_area": placeholders["zone_area"],
        "point_count": placeholders["point_count"],
        "type_distribution": placeholders["type_distribution"],
        "scale_distribution": placeholders["scale_distribution"],
        "warning_level_distribution": placeholders["warning_level_distribution"],
        "hidden_danger_ratio": placeholders["hidden_danger_ratio"],
        "threaten_population_total": placeholders["threaten_population_total"],
        "threaten_residents_total": placeholders["threaten_residents_total"],
        "threaten_assets_total": placeholders["threaten_assets_total"],
        "point_list_rows": placeholders["point_list_rows"],
        "cluster_summary": placeholders["cluster_summary"],
        "hotspot_summary": placeholders["hotspot_summary"],
        "affected_extent_summary": placeholders["affected_extent_summary"],
        "missing_value_summary": placeholders["missing_value_summary"],
        "appendix_full_table": placeholders["appendix_full_table"],
        # ---- 图件（Markdown `<img>`，前端 ChartInline 拦截为交互图表） ----
        "chart_type_distribution": _img(figures, "chart_type_distribution"),
        "chart_scale_distribution": _img(figures, "chart_scale_distribution"),
        "chart_warning_distribution": _img(figures, "chart_warning_distribution"),
        "chart_hidden_danger_ratio": _img(figures, "chart_hidden_danger_ratio"),
        "chart_threat_summary": _img(figures, "chart_threat_summary"),
        "map_figure": _img(figures, "map_figure"),
        # ---- A2UI 组件嵌入（`<!--a2ui:component_id-->` 前端匹配后渲染为交互组件） ----
        "a2ui_risk_card": "<!--a2ui:risk_card-->",
        "a2ui_key_points": "<!--a2ui:key_points-->",
        "a2ui_recommendations": "<!--a2ui:recommendations-->",
        "a2ui_text_limitations": "<!--a2ui:text_limitations-->",
        # ---- AI 研判 ----
        "研判.overall_risk.level": overall.get("level", "（未生成）"),
        "研判.overall_risk.basis": overall.get("basis", "（未生成）"),
        "研判.dominant_hazard.type": dh.get("type", "（未生成）"),
        "研判.dominant_hazard.cause_analysis": dh.get("cause_analysis", "（未生成）"),
        "研判.dominant_hazard.source_note": dh.get("source_note", ""),
        "研判.common_induce_factors": _as_lines(j.get("common_induce_factors")),
        "研判.trend.judgment": trend.get("judgment", "（未生成）"),
        "研判.trend.evidence_points": _inline(trend.get("evidence_points")),
        "研判.key_points → 表格行": _key_points_rows(j),
        "研判.recommendations.urgent": _as_lines(recs.get("urgent")),
        "研判.recommendations.near_term": _as_lines(recs.get("near_term")),
        "研判.recommendations.routine": _as_lines(recs.get("routine")),
        "研判.data_limitations": _as_lines(j.get("data_limitations")),
    }
    for key, val in repl.items():
        text = text.replace("{{" + key + "}}", str(val))
    return text


def render_empty_report(report_id: str, generate_time: str, zone_desc: str) -> str:
    """空结果(point_count==0)简化提示报告,不调用模型(校验 5)。"""
    return (
        f"# 灾圈地质灾害风险分析报告\n\n"
        f"**报告编号**：{report_id}　　**生成时间**：{generate_time}\n"
        f"**灾圈范围**：{zone_desc}\n\n---\n\n"
        f"## 提示\n\n本灾圈范围内**无有效监测点**（已剔除已核销 is_hex=1 的点位）。\n\n"
        f"未触发 AI 研判与图件渲染。如范围有误请调整灾圈几何后重试；"
        f"若确认范围正确，建议核查该区域监测点布设情况。\n"
    )
