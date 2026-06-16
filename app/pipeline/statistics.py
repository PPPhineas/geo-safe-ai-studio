"""第 3 环:代码统计(既定事实,数字以此为准)。

铁律 1:所有统计数字由本环节精确核算,LLM 严禁改动,只可引用。
产出对应报告第三章与 prompt 第二部分占位符(见 配套装配与渲染说明.md 二)。
scale、warning_level 为有序类别,展示与排序按等级序。
"""

from __future__ import annotations

import pandas as pd

SCALE_ORDER = ["小", "中", "大", "特大", "未分级"]
WARNING_ORDER = ["红色", "橙色", "黄色", "蓝色", "未定级"]
HIGH_WARNING = {"红色", "橙色"}
HIGH_SCALE = {"大", "特大"}


def _ordered_counts(series: pd.Series, order: list[str]) -> dict[str, int]:
    """按给定顺序统计计数;顺序外的取值(非标准)追加在末尾。"""
    counts = series.value_counts()
    out: dict[str, int] = {}
    for key in order:
        if key in counts.index:
            out[key] = int(counts[key])
    for key in counts.index:
        if key not in out:
            out[key] = int(counts[key])
    return out


def _fmt(counts: dict[str, int]) -> str:
    return "、".join(f"{k} {v}" for k, v in counts.items()) or "无"


def compute_statistics(df: pd.DataFrame) -> dict:
    """计算分类统计与威胁汇总。

    Returns:
        统计结果字典:各分布(计数 dict + 展示串)、各合计、point_count。
    """
    point_count = int(len(df))

    type_counts = (
        {str(k): int(v) for k, v in df["monitor_point_type"].value_counts().items()}
        if point_count
        else {}
    )
    scale_counts = _ordered_counts(df["scale"], SCALE_ORDER) if point_count else {}
    warning_counts = _ordered_counts(df["warning_level"], WARNING_ORDER) if point_count else {}

    hidden_count = int((df["is_hidden_danger"] == 1).sum()) if point_count else 0
    hidden_pct = round(hidden_count / point_count * 100, 1) if point_count else 0.0

    pop_total = int(df["threaten_population"].sum()) if point_count else 0
    res_total = int(df["threaten_residents"].sum()) if point_count else 0
    assets_total = round(float(df["threaten_assets"].sum()), 2) if point_count else 0.0

    return {
        "point_count": point_count,
        "type_distribution": type_counts,
        "type_distribution_str": _fmt(type_counts),
        "scale_distribution": scale_counts,
        "scale_distribution_str": _fmt(scale_counts),
        "warning_level_distribution": warning_counts,
        "warning_level_distribution_str": _fmt(warning_counts),
        "hidden_danger_count": hidden_count,
        "hidden_danger_ratio_str": f"{hidden_count} 个(占 {hidden_pct}%)",
        "threaten_population_total": pop_total,
        "threaten_residents_total": res_total,
        "threaten_assets_total": assets_total,
    }
