"""第 5 环:三层装配(占位符生成)。

把统计结果、空间结论、语义素材装配成 prompt 占位符 + 报告渲染所需的代码侧素材
(后端字符串注入,见 配套装配与渲染说明.md 二、三)。

重点点位:只把命中条件者放入 key_points_detail 控制上下文(≤ key_points_max),
命中任一即重点(高预警 / 大·特大规模 / 高威胁 Top-N / 落在连片带 / 隐患且趋势恶化)。
"""

from __future__ import annotations

import csv
import io
import re

import numpy as np
import pandas as pd

from app.config import get_settings
from app.pipeline.statistics import HIGH_SCALE, HIGH_WARNING

_TREND_WORDS = ("加剧", "扩大", "变形", "恶化", "增大", "发展", "活跃")
_SPLIT_RE = re.compile(r"[，,、;；/\s和及]+")


def _key_point_flags(df: pd.DataFrame, spatial: dict) -> pd.Series:
    """逐行命中标记 + 排序优先级分。"""
    n = len(df)
    labels = np.asarray(spatial.get("cluster_labels", [-1] * n))
    topn = min(5, n)
    pop_top = set(df["threaten_population"].nlargest(topn).index)
    asset_top = set(df["threaten_assets"].nlargest(topn).index)

    score = pd.Series(0.0, index=df.index)
    for pos, (i, row) in enumerate(df.iterrows()):
        s = 0.0
        if row["warning_level"] in HIGH_WARNING:
            s += 4 if row["warning_level"] == "红色" else 3
        if row["scale"] in HIGH_SCALE:
            s += 3 if row["scale"] == "特大" else 2
        if i in pop_top or i in asset_top:
            s += 2
        if pos < len(labels) and labels[pos] >= 0:
            s += 1.5
        if row["is_hidden_danger"] == 1 and any(w in row["current_status"] for w in _TREND_WORDS):
            s += 1.5
        score[i] = s
    return score


def select_key_points(df: pd.DataFrame, spatial: dict) -> list[dict]:
    """筛选重点点位明细(固定字段顺序,便于模型解析)。命中任一条件即入选。"""
    if df.empty:
        return []
    settings = get_settings()
    score = _key_point_flags(df, spatial)
    selected = df[score > 0].copy()
    selected["_score"] = score[score > 0]
    selected = selected.sort_values("_score", ascending=False)

    truncated = len(selected) > settings.key_points_max
    selected = selected.head(settings.key_points_max)

    out: list[dict] = []
    for _, row in selected.iterrows():
        out.append(
            {
                "monitor_point_code": row["monitor_point_code"],
                "monitor_point_name": row.get("monitor_point_name", ""),
                "monitor_point_type": row["monitor_point_type"],
                "scale": row["scale"],
                "warning_level": row["warning_level"],
                "threaten_population": int(row["threaten_population"]),
                "threaten_assets": float(row["threaten_assets"]),
                "lithology": row.get("lithology", ""),
                "avg_slope": None if pd.isna(row["avg_slope"]) else float(row["avg_slope"]),
                "induce_factors": row.get("induce_factors", ""),
                "current_status": row.get("current_status", ""),
            }
        )
    if truncated:
        out_meta = {"_truncated": True}
        out.append(out_meta)  # 末位放标记,assemble 取出后移除
    return out


def _format_key_points_detail(key_points: list[dict]) -> str:
    lines = []
    for idx, kp in enumerate(key_points, 1):
        slope = "缺失" if kp["avg_slope"] is None else f"{kp['avg_slope']:.1f}°"
        lines.append(
            f"{idx}. [{kp['monitor_point_code']}] {kp['monitor_point_name']} | "
            f"类型:{kp['monitor_point_type']} | 规模:{kp['scale']} | 预警:{kp['warning_level']} | "
            f"威胁人数:{kp['threaten_population']} | 威胁财产:{kp['threaten_assets']}万元 | "
            f"岩性:{kp['lithology'] or '—'} | 填报坡度:{slope} | "
            f"诱发:{kp['induce_factors'] or '—'} | 现状趋势:{kp['current_status'] or '—'}"
        )
    return "\n".join(lines) if lines else "（本圈无命中重点筛选条件的点位）"


def _top_tokens(series: pd.Series, top: int = 6) -> str:
    counter: dict[str, int] = {}
    for text in series.fillna("").astype(str):
        for tok in _SPLIT_RE.split(text):
            tok = tok.strip()
            if tok:
                counter[tok] = counter.get(tok, 0) + 1
    items = sorted(counter.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return "、".join(f"{k} {v}" for k, v in items) or "（无填报）"


def _typical_excerpts(df: pd.DataFrame, key_codes: set[str], limit_chars: int = 800) -> str:
    rows = df[df["current_status"].str.len() > 0]
    pref = rows[rows["monitor_point_code"].isin(key_codes)]
    trend = rows[rows["current_status"].str.contains("|".join(_TREND_WORDS), na=False)]
    ordered = pd.concat([trend, pref, rows]).drop_duplicates("monitor_point_code")
    parts, total = [], 0
    for _, row in ordered.iterrows():
        snippet = f"[{row['monitor_point_code']}] {row['current_status']}"
        if total + len(snippet) > limit_chars:
            break
        parts.append(snippet)
        total += len(snippet)
    return "；".join(parts) if parts else "（无现状/趋势填报）"


def _missing_summary(missing_stats: dict) -> str:
    label = {
        "threaten_population_missing": "威胁人数缺失",
        "threaten_residents_missing": "威胁户数缺失",
        "threaten_assets_missing": "威胁财产缺失",
        "avg_slope_missing": "坡度缺失",
        "avg_slope_invalid": "坡度异常(需复核)",
    }
    parts = [f"{label.get(k, k)} {v} 条" for k, v in missing_stats.items() if v]
    return "、".join(parts) if parts else "无显著字段缺失"


def _region_label(row) -> str:
    """省 市 县 组合为一列(过滤「未知」/空);全无则「未知」。"""
    parts = [
        str(row.get(c, "")).strip()
        for c in ("province_name", "city_name", "county_name")
    ]
    parts = [p for p in parts if p and p != "未知"]
    return " ".join(parts) if parts else "未知"


def _point_list_rows(df: pd.DataFrame, key_codes: set[str]) -> str:
    rows = []
    for i, (_, row) in enumerate(df.iterrows(), 1):
        star = "★" if row["monitor_point_code"] in key_codes else ""
        rows.append(
            f"| {i} | {row['monitor_point_code']} | {row.get('monitor_point_name','')} | "
            f"{_region_label(row)} | "
            f"{row['monitor_point_type']} | {row['scale']} | {row['warning_level']} | "
            f"{int(row['threaten_population'])} | {row['threaten_assets']} | {star} |"
        )
    return "\n".join(rows)


_FULL_COLS = [
    "monitor_point_code", "monitor_point_name",
    "province_name", "city_name", "county_name",
    "monitor_point_type", "scale",
    "warning_level", "longitude", "latitude", "threaten_population",
    "threaten_residents", "threaten_assets", "avg_slope", "lithology",
    "induce_factors", "current_status", "is_hidden_danger",
]


def _appendix_table(df: pd.DataFrame) -> str:
    cols = [c for c in _FULL_COLS if c in df.columns]
    header = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join(["---"] * len(cols)) + "|"
    body = []
    for _, row in df.iterrows():
        vals = ["" if pd.isna(row[c]) else str(row[c]).replace("|", "／") for c in cols]
        body.append("| " + " | ".join(vals) + " |")
    return "\n".join([header, sep, *body])


def _monitor_csv(df: pd.DataFrame) -> str:
    """全部点位的完整逐字段 CSV(供清单过长时作附件下载)。"""
    cols = [c for c in _FULL_COLS if c in df.columns]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(cols)
    for _, row in df.iterrows():
        writer.writerow(["" if pd.isna(row[c]) else row[c] for c in cols])
    return buf.getvalue()


def assemble_placeholders(
    stats: dict,
    spatial: dict,
    df: pd.DataFrame,
    missing_stats: dict,
) -> dict:
    """装配 prompt 全部占位符 + 报告渲染所需代码侧素材。"""
    key_points = select_key_points(df, spatial)
    truncated = bool(key_points and isinstance(key_points[-1], dict) and key_points[-1].get("_truncated"))
    if truncated:
        key_points = key_points[:-1]
    key_codes = {kp["monitor_point_code"] for kp in key_points}

    missing_summary = _missing_summary(missing_stats)
    if truncated:
        missing_summary += f"；重点点位明细仅列前 {len(key_points)} 个高风险点(按优先级截断)"

    return {
        # ---- 一/二层:既定事实统计 ----
        "zone_geometry_desc": spatial["zone_geometry_desc"],
        "zone_area": spatial["zone_area"],
        "point_count": stats["point_count"],
        "type_distribution": stats["type_distribution_str"],
        "scale_distribution": stats["scale_distribution_str"],
        "warning_level_distribution": stats["warning_level_distribution_str"],
        "hidden_danger_ratio": stats["hidden_danger_ratio_str"],
        "threaten_population_total": stats["threaten_population_total"],
        "threaten_residents_total": stats["threaten_residents_total"],
        "threaten_assets_total": stats["threaten_assets_total"],
        # ---- 空间层 ----
        "cluster_summary": spatial["cluster_summary"],
        "hotspot_summary": spatial["hotspot_summary"],
        "affected_extent_summary": spatial["affected_extent_summary"],
        # ---- 三层:语义素材 ----
        "common_induce_factors": _top_tokens(df["induce_factors"]),
        "common_lithology": _top_tokens(df["lithology"]),
        "typical_status_excerpts": _typical_excerpts(df, key_codes),
        # ---- 重点点位明细 ----
        "key_points_detail": _format_key_points_detail(key_points),
        # ---- 报告渲染专用(非 prompt)----
        "key_point_codes": sorted(key_codes),
        "point_list_rows": _point_list_rows(df, key_codes),
        "point_list_rows_key": _point_list_rows(df[df["monitor_point_code"].isin(key_codes)], key_codes),
        "appendix_full_table": _appendix_table(df),
        "monitor_points_csv": _monitor_csv(df),
        "missing_value_summary": missing_summary,
    }
