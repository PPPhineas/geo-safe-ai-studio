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


def render_charts(stats: dict) -> dict[str, bytes]:
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

    return out
