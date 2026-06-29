"""预警历史分析：近 N 天预警次数、最高等级、未关闭记录、误报标记。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.clients.clickhouse import ClickHouseClient
from app.config import get_settings
from app.pipeline.trends import _as_datetime

WARNING_TABLE = "dwd_gh_v1.dwd_monitor_warning_info_view"


def fetch_warning_history_for_points(
    codes: list[str],
    client: ClickHouseClient | None = None,
    lookback_days: int | None = None,
) -> dict:
    """读取近 N 天预警历史，失败时降级返回 limitations。"""
    lookback = lookback_days or get_settings().warning_history_lookback_days
    bundle = {"enabled": False, "lookback_days": lookback, "records": [], "limitations": []}
    clean_codes = [str(code) for code in codes if str(code).strip()]
    if not clean_codes:
        bundle["limitations"].append("无有效监测点编号，无法查询预警历史")
        return bundle
    try:
        client = client or ClickHouseClient()
        since = datetime.now() - timedelta(days=lookback)
        sql = (
            f"SELECT warning_code, warning_time, warning_level, warning_status, warning_desc, "
            f"is_false_alarm, monitor_point_code, device_type, warning_value "
            f"FROM {WARNING_TABLE} "
            "WHERE monitor_point_code IN {codes:Array(String)} "
            "AND warning_time >= {since:DateTime} "
            "ORDER BY monitor_point_code, warning_time DESC"
        )
        rows = client.query(sql, {"codes": clean_codes, "since": since})
    except Exception as exc:  # noqa: BLE001
        bundle["limitations"].append(f"预警历史查询失败:{type(exc).__name__}")
        return bundle
    bundle["enabled"] = True
    bundle["records"] = rows
    return bundle


def _warning_rank(level: Any) -> int:
    text = str(level or "")
    if "4" in text or "红" in text:
        return 4
    if "3" in text or "橙" in text:
        return 3
    if "2" in text or "黄" in text:
        return 2
    if "1" in text or "蓝" in text:
        return 1
    return 0


def _warning_label(rank: int) -> str:
    return {4: "红色", 3: "橙色", 2: "黄色", 1: "蓝色"}.get(rank, "未定级")


def analyze_warning_history(bundle: dict | None) -> dict:
    """汇总预警历史、未关闭预警和误报情况。"""
    if not bundle or not bundle.get("enabled"):
        limitations = (bundle or {}).get("limitations") or ["未接入预警历史"]
        return {
            "warning_history_summary": "未接入有效预警历史，暂无法开展历史预警一致性分析。",
            "warning_history_detail": "（无）",
            "warning_history_limitations": limitations,
        }
    rows = bundle.get("records") or []
    if not rows:
        return {
            "warning_history_summary": f"近 {bundle.get('lookback_days')} 天圈内点位无预警记录。",
            "warning_history_detail": "（无预警记录）",
            "warning_history_limitations": [],
        }

    by_point: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_point[str(row.get("monitor_point_code", ""))].append(row)
    open_status = {"0", "1", "待处理", "处理中"}
    false_alarm = sum(1 for row in rows if str(row.get("is_false_alarm", "")).strip() == "1")
    open_rows = [row for row in rows if str(row.get("warning_status", "")).strip() in open_status]
    highest = max(_warning_rank(row.get("warning_level")) for row in rows)

    detail = []
    for code, items in sorted(by_point.items(), key=lambda kv: len(kv[1]), reverse=True)[:12]:
        rank = max(_warning_rank(row.get("warning_level")) for row in items)
        latest = max((_as_datetime(row.get("warning_time")) for row in items), default=None)
        latest_text = latest.strftime("%Y-%m-%d") if latest else "时间缺失"
        active = sum(1 for row in items if str(row.get("warning_status", "")).strip() in open_status)
        detail.append(f"[{code}] {len(items)}次，最高{_warning_label(rank)}，最近{latest_text}，未关闭{active}次")

    return {
        "warning_history_summary": (
            f"近 {bundle.get('lookback_days')} 天共 {len(rows)} 条预警记录，涉及 {len(by_point)} 个点位；"
            f"最高等级{_warning_label(highest)}，未关闭 {len(open_rows)} 条，误报标记 {false_alarm} 条。"
        ),
        "warning_history_detail": "\n".join(detail),
        "warning_history_limitations": [],
    }
