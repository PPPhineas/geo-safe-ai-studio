"""第 2 环:字段清洗 / 归一化。

表中大量数值字段为 NULLABLE(STRING),统计前必须清洗(见 配套装配与渲染说明.md 一):
    - threaten_population/residents、avg_slope 等:去单位 → 转数值;空/非法计 0 并**记缺失**;
    - avg_slope 异常(<0 或 >90)标记需复核,不参与统计;
    - scale / warning_level / monitor_point_type 归一化,空值分别归「未分级/未定级/未分类」并保留可见。

铁律 4:所有「空值/非法值如何处理」必须可追溯,缺失计数最终进入 data_limitations。
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _to_number(value: Any) -> float | None:
    """从原始值(可能含单位/逗号的字符串)提取第一个数值;无法解析返回 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).replace(",", "").replace("，", "").strip()
    if not text:
        return None
    m = _NUM_RE.search(text)
    return float(m.group()) if m else None


def _norm_scale(value: Any) -> str:
    text = (str(value).strip() if value is not None else "")
    if "特大" in text:
        return "特大"
    if "大" in text:
        return "大"
    if "中" in text:
        return "中"
    if "小" in text:
        return "小"
    return "未分级"


def _norm_warning(value: Any) -> str:
    text = (str(value).strip() if value is not None else "")
    if not text:
        return "未定级"
    for key, label in (("红", "红色"), ("橙", "橙色"), ("黄", "黄色"), ("蓝", "蓝色")):
        if key in text:
            return label
    return text  # 非标准取值保留可见


def _norm_type(value: Any) -> str:
    text = (str(value).strip() if value is not None else "")
    return text or "未分类"


def clean_records(records: list[dict]) -> tuple[pd.DataFrame, dict]:
    """清洗原始记录。

    Returns:
        (df, missing_stats):清洗后的 DataFrame;缺失/异常计数字典
        (如 {"threaten_population_missing": N, "avg_slope_invalid": M})。
    """
    df = pd.DataFrame(records)
    missing: dict[str, int] = {}

    if df.empty:
        return df, missing

    # ---- 经纬度 → float(供空间分析复用)----
    df["longitude"] = df["longitude"].map(_to_number)
    df["latitude"] = df["latitude"].map(_to_number)

    # ---- 威胁要素:去单位 → 数值;空/非法计 0 并记缺失 ----
    for col, miss_key in (
        ("threaten_population", "threaten_population_missing"),
        ("threaten_residents", "threaten_residents_missing"),
        ("threaten_assets", "threaten_assets_missing"),
    ):
        raw = df[col] if col in df.columns else pd.Series([None] * len(df))
        nums = raw.map(_to_number)
        missing[miss_key] = int(nums.isna().sum())
        df[col] = nums.fillna(0.0)

    # ---- 平均坡度:提取数值,异常(<0 或 >90)标记需复核,不参与统计 ----
    slope_raw = df["avg_slope"] if "avg_slope" in df.columns else pd.Series([None] * len(df))
    slope = slope_raw.map(_to_number)
    invalid_mask = slope.notna() & ((slope < 0) | (slope > 90))
    slope = slope.mask(invalid_mask, other=np.nan)
    missing["avg_slope_invalid"] = int(invalid_mask.sum())
    missing["avg_slope_missing"] = int(slope.isna().sum() - invalid_mask.sum())
    df["avg_slope"] = slope

    # ---- 类别归一化(保留可见)----
    df["scale"] = df["scale"].map(_norm_scale) if "scale" in df.columns else "未分级"
    df["warning_level"] = (
        df["warning_level"].map(_norm_warning) if "warning_level" in df.columns else "未定级"
    )
    df["monitor_point_type"] = (
        df["monitor_point_type"].map(_norm_type) if "monitor_point_type" in df.columns else "未分类"
    )

    # ---- 隐患识别:空按 0 ----
    if "is_hidden_danger" in df.columns:
        df["is_hidden_danger"] = (
            pd.to_numeric(df["is_hidden_danger"], errors="coerce").fillna(0).astype(int)
        )
    else:
        df["is_hidden_danger"] = 0

    # ---- 文本字段:统一为字符串,空→"" ----
    for col in ("monitor_point_name", "lithology", "induce_factors", "current_status"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
        else:
            df[col] = ""

    df["monitor_point_code"] = df["monitor_point_code"].astype(str)

    return df, missing
