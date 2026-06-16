"""第 7 环:渲染前校验(代码侧,不靠模型自觉)。

5 道校验(见 配套装配与渲染说明.md 四):
    1. 编号溯源:递归提取 JSON 中所有 monitor_point_code,与圈内集合比对;有集合外编号 → 不合格;
    2. 来源标注:dominant_hazard.source_note / cause_analysis 地形相关须含
       「基于填报值，未经地形数据校验」字样;缺失 → 不合格;
    3. 数字一致性:报告正文统计数字一律以代码值填充覆盖(在 render 处理);
    4. JSON 结构:字段齐全、类型正确;缺字段 → 不合格;
    5. 空结果:point_count==0 不调模型(在 orchestrator 短路)。

不合格 → 回退重生成(或剔除该条并记警告)。
"""

from __future__ import annotations

from app.prompts.risk_judgement import OUTPUT_SCHEMA_KEYS

# 注意:与 docs 一致使用全角逗号。
SOURCE_NOTE = "基于填报值，未经地形数据校验"
_TERRAIN_WORDS = ("坡度", "坡向", "汇水", "沟道", "地形")

_REQUIRED_TYPES: dict[str, type] = {
    "overall_risk": dict,
    "dominant_hazard": dict,
    "common_induce_factors": list,
    "trend": dict,
    "key_points": list,
    "recommendations": dict,
    "data_limitations": list,
}


def _collect_codes(node) -> list[str]:
    """递归收集 JSON 中所有 monitor_point_code 值。"""
    found: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "monitor_point_code" and isinstance(v, str) and v.strip():
                found.append(v.strip())
            else:
                found.extend(_collect_codes(v))
    elif isinstance(node, list):
        for item in node:
            found.extend(_collect_codes(item))
    return found


def validate_judgement(judgement: dict, valid_codes: set[str]) -> dict:
    """校验研判 JSON。返回 {"ok", "errors", "warnings"}。"""
    errors: list[str] = []
    warnings: list[str] = []

    # ---- 校验 4:结构 ----
    for key in OUTPUT_SCHEMA_KEYS:
        if key not in judgement:
            errors.append(f"缺少字段:{key}")
        elif not isinstance(judgement[key], _REQUIRED_TYPES[key]):
            errors.append(
                f"字段类型错误:{key} 应为 {_REQUIRED_TYPES[key].__name__}，实为 {type(judgement[key]).__name__}"
            )

    # ---- 校验 1:编号溯源 ----
    codes = _collect_codes(judgement)
    outside = sorted({c for c in codes if c not in valid_codes})
    if outside:
        errors.append(f"出现圈外/未知编号:{outside}")

    # ---- 校验 2:地形来源标注 ----
    dh = judgement.get("dominant_hazard", {})
    if isinstance(dh, dict):
        terrain_text = f"{dh.get('cause_analysis', '')}{dh.get('source_note', '')}"
        if any(w in terrain_text for w in _TERRAIN_WORDS) and SOURCE_NOTE not in terrain_text:
            errors.append("dominant_hazard 含地形相关表述但缺少来源标注「基于填报值，未经地形数据校验」")

    # ---- 软性提醒 ----
    kps = judgement.get("key_points", [])
    if isinstance(kps, list):
        for i, kp in enumerate(kps):
            if isinstance(kp, dict) and not kp.get("monitor_point_code"):
                warnings.append(f"key_points[{i}] 缺 monitor_point_code")

    return {"ok": not errors, "errors": errors, "warnings": warnings}
