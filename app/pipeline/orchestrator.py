"""链路编排:串起整条数据链路。

    selection → cleaning → statistics → spatial → assembly → judgement → validation → render

短路:point_count==0 时不调模型,直接渲染「灾圈内无有效监测点」简化报告(铁律 / 校验 5)。
失败回退:研判校验不合格时重生成(上限若干次),仍不过则降级处理并记入 data_limitations。

提供两种入口:
    - generate_risk_report(req):一次性返回完整报告。
    - generate_risk_report_stream(req):SSE 生成器,逐阶段推进 + 流式转发 AI 研判思考/输出,末尾发完整报告。
"""

from __future__ import annotations

import csv
import io
import json
import uuid
import zipfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from app.api.schemas import (
    PolygonGeometry,
    RiskReportDetailResponse,
    RiskReportRequest,
    RiskReportResponse,
    RiskReportReviseRequest,
    RiskReportReviseResponse,
    RiskReportVersionContent,
    ReportVersion,
)
from app.pipeline.a2ui_builder import build_risk_a2ui
from app.clients.llm import LLMClient
from app.pipeline.assembly import assemble_placeholders
from app.pipeline.cleaning import clean_records
from app.pipeline.judgement import _parse_json, run_judgement
from app.pipeline.rain_deformation_coupling import analyze_rain_deformation_coupling
from app.pipeline.regions import enrich_regions, get_region_maps
from app.pipeline.selection import select_points_in_zone
from app.pipeline.spatial import analyze_spatial
from app.pipeline.statistics import compute_statistics
from app.pipeline.timeseries import fetch_time_series_for_points
from app.pipeline.trends import analyze_deformation_trends
from app.pipeline.validation import validate_judgement
from app.pipeline.warning_history import analyze_warning_history, fetch_warning_history_for_points
from app.config import get_settings
from app.prompts.risk_judgement import SYSTEM_PROMPT, build_user_prompt
from app.render.charts import render_charts
from app.render.maps import render_map
from app.render.report import render_empty_report, render_report

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "figures"
MAX_JUDGE_RETRIES = 2
# 点位超过此阈值时,监测点清单/附录改为 CSV 附件,正文只内联重点点位,避免报告过长。
LIST_ATTACH_THRESHOLD = 100
VERSION_INDEX = "versions.json"
VERSION_DIR = "versions"


class ReportRevisionError(RuntimeError):
    """报告修订失败。"""


def _zone_desc(geometry: PolygonGeometry) -> str:
    return f"{len(geometry.coordinates)} 顶点多边形"


def _safe_report_dir(report_id: str) -> Path:
    """返回经路径穿越校验后的报告目录。"""
    base = OUTPUT_DIR.resolve()
    target = (OUTPUT_DIR / report_id).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise FileNotFoundError("非法 report_id") from exc
    return target


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _version_id(report_id: str, version: int) -> str:
    return f"{report_id}_v{version}"


def _infer_assets(report_id: str, target: Path) -> tuple[dict[str, str], dict[str, str]]:
    """从旧版报告目录推断图件和附件资源 URL。"""
    figures: dict[str, str] = {}
    attachments: dict[str, str] = {}
    if not target.is_dir():
        return figures, attachments
    skip = {"report.md", "judgement.json", VERSION_INDEX}
    for path in sorted(target.iterdir()):
        if not path.is_file() or path.name in skip:
            continue
        url = f"/static/figures/{report_id}/{path.name}"
        if path.suffix.lower() == ".png":
            figures[path.stem] = url
        else:
            attachments[path.name] = url
    return figures, attachments


def _index_path(target: Path) -> Path:
    return target / VERSION_INDEX


def _read_index(target: Path) -> dict:
    return json.loads(_index_path(target).read_text(encoding="utf-8"))


def _write_index(target: Path, index: dict) -> None:
    _index_path(target).write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _ensure_version_index(report_id: str) -> dict:
    """确保报告有版本索引；旧报告目录自动视为 v1。"""
    target = _safe_report_dir(report_id)
    if not target.is_dir():
        raise FileNotFoundError(f"报告 {report_id} 不存在或尚未生成")
    index_file = _index_path(target)
    if index_file.exists():
        return _read_index(target)

    md_path = target / "report.md"
    if not md_path.exists():
        raise FileNotFoundError(f"报告 {report_id} 缺少 report.md")
    figures, attachments = _infer_assets(report_id, target)
    index = {
        "report_id": report_id,
        "current_version": 1,
        "versions": [
            {
                "version_id": _version_id(report_id, 1),
                "version": 1,
                "created_at": _now_iso(),
                "source": "initial",
                "figures": figures,
                "attachments": attachments,
                "change_summary": [],
            }
        ],
    }
    _write_index(target, index)
    return index


def _register_initial_version(report_id: str) -> None:
    """生成报告后注册 v1；已有版本索引时保持不变。"""
    target = _safe_report_dir(report_id)
    if _index_path(target).exists():
        return
    _ensure_version_index(report_id)


def _find_version(index: dict, version_id: str) -> dict:
    for version in index.get("versions", []):
        if version.get("version_id") == version_id:
            return version
    raise FileNotFoundError(f"报告版本 {version_id} 不存在")


def _latest_version(index: dict) -> dict:
    versions = index.get("versions") or []
    if not versions:
        raise FileNotFoundError("报告版本索引为空")
    current = index.get("current_version")
    for version in versions:
        if version.get("version") == current:
            return version
    return versions[-1]


def _version_report_path(target: Path, version: dict) -> Path:
    if version.get("version") == 1:
        return target / "report.md"
    return target / VERSION_DIR / str(version["version_id"]) / "report.md"


def _read_version_markdown(target: Path, version: dict) -> str:
    md_path = _version_report_path(target, version)
    if not md_path.exists():
        raise FileNotFoundError(f"报告版本 {version.get('version_id')} 缺少 report.md")
    return md_path.read_text(encoding="utf-8")


def get_risk_report(report_id: str) -> RiskReportDetailResponse:
    """读取报告版本列表和当前版本正文。"""
    target = _safe_report_dir(report_id)
    index = _ensure_version_index(report_id)
    current = _latest_version(index)
    markdown = _read_version_markdown(target, current)
    versions = [ReportVersion(**item) for item in index.get("versions", [])]
    return RiskReportDetailResponse(
        report_id=report_id,
        current_version=int(index.get("current_version", current["version"])),
        versions=versions,
        current=RiskReportVersionContent(
            version_id=current["version_id"],
            version=current["version"],
            report_markdown=markdown,
            figures=current.get("figures") or {},
            attachments=current.get("attachments") or {},
        ),
    )


def _build_revision_prompt(base_markdown: str, req: RiskReportReviseRequest) -> str:
    annotations = [
        {
            "block_id": item.block_id,
            "block_text": item.block_text,
            "comment": item.comment,
        }
        for item in req.annotations
    ]
    return (
        "请根据用户对报告段落的批注，对整篇 Markdown 报告进行二次修订。\n"
        "要求：\n"
        "1. 只输出 JSON，不要输出解释文字。\n"
        "2. JSON 结构必须为 {\"report_markdown\": string, \"change_summary\": string[]}。\n"
        "3. report_markdown 必须是修订后的完整 Markdown，不要返回 patch 或片段。\n"
        "4. 保留原报告编号、章节结构、Markdown 表格、图片链接和附件链接。\n"
        "5. 仅根据批注意见修订，不要虚构新增图件、附件、监测点或未给出的数据。\n\n"
        "批注列表 JSON：\n"
        f"{json.dumps(annotations, ensure_ascii=False, indent=2)}\n\n"
        "原始完整 Markdown：\n"
        f"{base_markdown}"
    )


def _parse_revision_result(raw: str) -> tuple[str, list[str]]:
    try:
        data = json.loads(raw)
    except ValueError:
        data = _parse_json(raw)
    markdown = data.get("report_markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        raise ReportRevisionError("LLM 修订结果缺少有效 report_markdown")
    summary = data.get("change_summary") or []
    if not isinstance(summary, list):
        summary = [str(summary)]
    return markdown, [str(item) for item in summary if str(item).strip()]


def revise_risk_report(
    report_id: str,
    req: RiskReportReviseRequest,
    client: LLMClient | None = None,
) -> RiskReportReviseResponse:
    """基于指定版本和批注生成完整新版 Markdown。"""
    if req.mode != "full_markdown":
        raise ValueError("仅支持 full_markdown 修订模式")

    target = _safe_report_dir(report_id)
    index = _ensure_version_index(report_id)
    base_version = _find_version(index, req.base_version_id)
    base_markdown = _read_version_markdown(target, base_version)

    prompt = _build_revision_prompt(base_markdown, req)
    raw = (client or LLMClient()).judge(
        "你是地质灾害风险研判报告编辑。你必须只输出 JSON，且保留报告事实依据。",
        prompt,
    )
    report_markdown, change_summary = _parse_revision_result(raw)

    next_version = max(int(item["version"]) for item in index["versions"]) + 1
    next_version_id = _version_id(report_id, next_version)
    version_dir = target / VERSION_DIR / next_version_id
    version_dir.mkdir(parents=True, exist_ok=False)
    (version_dir / "report.md").write_text(report_markdown, encoding="utf-8")
    (version_dir / "metadata.json").write_text(
        json.dumps(
            {
                "base_version_id": req.base_version_id,
                "annotations": [item.model_dump() for item in req.annotations],
                "change_summary": change_summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    item = {
        "version_id": next_version_id,
        "version": next_version,
        "created_at": _now_iso(),
        "source": "revision",
        "figures": base_version.get("figures") or {},
        "attachments": base_version.get("attachments") or {},
        "change_summary": change_summary,
    }
    index["versions"].append(item)
    index["current_version"] = next_version
    _write_index(target, index)

    return RiskReportReviseResponse(
        report_id=report_id,
        version_id=next_version_id,
        version=next_version,
        report_markdown=report_markdown,
        figures=item["figures"],
        attachments=item["attachments"],
        change_summary=change_summary,
    )


def _persist_figures(report_id: str, images: dict[str, bytes]) -> dict[str, str]:
    """把图件字节落盘到 output/figures/{report_id}/,返回 {key: /static URL}。"""
    target = _safe_report_dir(report_id)
    target.mkdir(parents=True, exist_ok=True)
    figures: dict[str, str] = {}
    for key, data in images.items():
        (target / f"{key}.png").write_bytes(data)
        figures[key] = f"/static/figures/{report_id}/{key}.png"
    return figures


def _persist_attachment(report_id: str, filename: str, text: str) -> str:
    """把附件文本落盘到 output/figures/{report_id}/,返回 /static URL。CSV 用 utf-8-sig 便于 Excel 识别中文。

    newline="" 关闭换行翻译:csv 已写 \\r\\n,避免 Windows 再把 \\n 翻成 \\r\\n 造成 \\r\\r\\n 空行。
    """
    target = _safe_report_dir(report_id)
    target.mkdir(parents=True, exist_ok=True)
    (target / filename).write_text(text, encoding="utf-8-sig", newline="")
    return f"/static/figures/{report_id}/{filename}"


def _maybe_attach_list(report_id: str, stats: dict, placeholders: dict) -> dict[str, str]:
    """点位过多时,把完整监测点清单转为 CSV 附件,正文清单/附录只留重点点位 + 下载链接。"""
    if stats["point_count"] <= LIST_ATTACH_THRESHOLD:
        return {}
    url = _persist_attachment(report_id, "monitor_points.csv", placeholders.get("monitor_points_csv", ""))
    n = stats["point_count"]
    placeholders["point_list_rows"] = (
        placeholders.get("point_list_rows_key", "")
        + f"\n\n> 注：圈内共 **{n}** 个监测点，清单过长，完整逐字段清单已作为附件："
        + f"[monitor_points.csv]({url})；上表仅列重点关注点位。"
    )
    placeholders["appendix_full_table"] = (
        f"完整逐字段监测点数据表(共 {n} 行)较长，已作为附件提供：[monitor_points.csv]({url})。"
    )
    return {"monitor_points.csv": url}


def _persist_report(report_id: str, report_md: str, judgement: dict | None = None) -> None:
    """把成稿 report.md(原始 /static 链接)与研判 JSON 落盘,供打包下载。"""
    target = _safe_report_dir(report_id)
    target.mkdir(parents=True, exist_ok=True)
    (target / "report.md").write_text(report_md, encoding="utf-8")
    if judgement is not None:
        (target / "judgement.json").write_text(
            json.dumps(judgement, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    _register_initial_version(report_id)


def build_bundle(report_id: str, version_id: str | None = None) -> bytes:
    """把某次报告打包成 zip(report.md 链接改为相对 figures/,含全部图件 + 附件 + 研判 JSON)。

    解压后离线打开 report.md 即可正常显示图片与附件。report_id 经路径校验防穿越。
    version_id 为空时导出最新版本。
    """
    target = _safe_report_dir(report_id)
    index = _ensure_version_index(report_id)
    version = _find_version(index, version_id) if version_id else _latest_version(index)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        md = _read_version_markdown(target, version)
        md = md.replace(f"/static/figures/{report_id}/", "figures/")
        zf.writestr("report.md", md)
        for path in sorted(target.iterdir()):
            if not path.is_file() or path.name == "report.md":
                continue
            if path.name == VERSION_INDEX:
                continue
            if path.name == "judgement.json":
                zf.write(path, "judgement.json")  # 放根目录
            else:  # 图件 png / 附件 csv → figures/
                zf.write(path, f"figures/{path.name}")
    return buf.getvalue()


def _maybe_attach_clusters(report_id: str, spatial: dict, placeholders: dict) -> dict[str, str]:
    """连片带过多/单带成员过多(摘要无法完整呈现)时,完整「带→成员」明细转 CSV 附件,
    章四只保留有界摘要 + 下载链接。"""
    if not spatial.get("cluster_summary_truncated"):
        return {}
    clusters = spatial.get("clusters_detail") or []
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["cluster_id", "member_count", "monitor_point_codes"])
    for c in clusters:
        writer.writerow([c["cluster_id"], c["member_count"], ";".join(c["codes"])])
    url = _persist_attachment(report_id, "clusters.csv", buf.getvalue())
    placeholders["cluster_summary"] = (
        placeholders.get("cluster_summary", "")
        + f"\n\n> 完整连片带-成员明细(共 {spatial.get('cluster_count', 0)} 个带)已作为附件："
        + f"[clusters.csv]({url})。"
    )
    return {"clusters.csv": url}


def _apply_degrade(judgement: dict, errors: list[str]) -> None:
    """研判多次仍未过校验:降级,把校验错误并入 data_limitations。"""
    if not errors:
        return
    judgement.setdefault("data_limitations", [])
    if isinstance(judgement["data_limitations"], list):
        judgement["data_limitations"].append(
            "（系统提示）研判经多次重生成仍未完全通过校验：" + "；".join(errors)
        )


def _render_response(
    report_id: str,
    req: RiskReportRequest,
    stats: dict,
    spatial: dict,
    df,
    placeholders: dict,
    judgement: dict,
) -> RiskReportResponse:
    """渲染图件 + 成稿 + 组装响应(数字以代码值覆盖)。图件失败降级,不影响返回。"""
    # 点位/连片带过多 → 转 CSV 附件(在成稿前改写占位符)
    attachments = _maybe_attach_list(report_id, stats, placeholders)
    attachments.update(_maybe_attach_clusters(report_id, spatial, placeholders))

    images: dict[str, bytes] = {}
    try:
        images.update(render_charts(stats))
    except Exception as exc:  # noqa: BLE001
        placeholders["missing_value_summary"] += f"；统计图渲染失败({type(exc).__name__})"
    try:
        images["map_figure"] = render_map(spatial, df, req.geometry)
    except Exception as exc:  # noqa: BLE001
        placeholders["missing_value_summary"] += f"；空间分布图渲染失败({type(exc).__name__}，可能内网无法拉取底图瓦片)"

    figures = _persist_figures(report_id, images)
    report_md = render_report(placeholders, judgement, figures)
    _persist_report(report_id, report_md, judgement)
    return RiskReportResponse(
        report_id=report_id,
        point_count=stats["point_count"],
        report_markdown=report_md,
        judgement=judgement,
        figures=figures,
        attachments=attachments,
    )


def generate_risk_report(req: RiskReportRequest) -> RiskReportResponse:
    """生成风险报告(完整链路,一次性返回)。"""
    report_id = req.report_id or uuid.uuid4().hex[:12]
    generate_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    points = select_points_in_zone(req.geometry)
    if not points:
        md = render_empty_report(report_id, generate_time, _zone_desc(req.geometry))
        _persist_report(report_id, md)
        return RiskReportResponse(report_id=report_id, point_count=0, report_markdown=md)

    df, missing = clean_records(points)
    # df = enrich_regions(df, get_region_maps())  # 省市县:库字段优先 + code 反推补缺(CH 不通时注释)
    try:
        maps = get_region_maps()
    except Exception:
        maps = None
    df = enrich_regions(df, maps)
    stats = compute_statistics(df)
    spatial = analyze_spatial(df, req.geometry)
    time_series = fetch_time_series_for_points(df) if get_settings().trend_enable_timeseries else None
    trend = analyze_deformation_trends(df, time_series)
    warning_history = fetch_warning_history_for_points(df["monitor_point_code"].astype(str).tolist())
    professional = {}
    professional.update(analyze_rain_deformation_coupling(time_series))
    professional.update(analyze_warning_history(warning_history))

    placeholders = assemble_placeholders(stats, spatial, df, missing, trend, professional)
    placeholders["report_id"] = report_id
    placeholders["generate_time"] = generate_time
    valid_codes = set(df["monitor_point_code"].astype(str))

    judgement: dict = {}
    last_errors: list[str] = []
    for _ in range(MAX_JUDGE_RETRIES + 1):
        judgement = run_judgement(placeholders)
        verdict = validate_judgement(judgement, valid_codes)
        last_errors = verdict["errors"]
        if verdict["ok"]:
            break
    _apply_degrade(judgement, last_errors)

    return _render_response(report_id, req, stats, spatial, df, placeholders, judgement)


def _sse(event: str, data: dict) -> str:
    """组装一条 SSE 消息(data 为单行 JSON,内部换行已被转义)。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def generate_risk_report_stream(req: RiskReportRequest) -> Iterator[str]:
    """SSE 流式生成:逐阶段推进事件 + 流式转发 AI 研判思考/输出,末尾 done 发完整报告。

    事件类型:
        stage      链路阶段推进({stage, msg, ...})
        reasoning  AI 研判思考增量({text})
        content    AI 研判输出(JSON)增量({text})
        validation 单次校验结果({ok, errors})
        a2ui       A2UI 声明式界面意图(A2uiSurface)
        warn       非致命提示({msg})
        error      致命错误({msg})
    """
    try:
        report_id = req.report_id or uuid.uuid4().hex[:12]
        generate_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        yield _sse("stage", {"stage": "selection", "msg": "初筛:从 ClickHouse 取灾圈内监测点…"})
        points = select_points_in_zone(req.geometry)
        if not points:
            md = render_empty_report(report_id, generate_time, _zone_desc(req.geometry))
            _persist_report(report_id, md)
            resp = RiskReportResponse(report_id=report_id, point_count=0, report_markdown=md)
            yield _sse("done", resp.model_dump())
            return
        yield _sse("stage", {"stage": "selection", "msg": f"圈内有效监测点 {len(points)} 个", "point_count": len(points)})

        yield _sse("stage", {"stage": "cleaning", "msg": "字段清洗 / 缺失计数 / 省市县反推…"})
        df, missing = clean_records(points)
        # df = enrich_regions(df, get_region_maps())  # 省市县:库字段优先 + code 反推补缺(CH 不通时注释)
        try:
            maps = get_region_maps()
        except Exception:
            maps = None
        df = enrich_regions(df, maps)
        yield _sse("stage", {"stage": "statistics", "msg": "分类统计 / 威胁汇总…"})
        stats = compute_statistics(df)
        yield _sse("stage", {"stage": "spatial", "msg": "空间分析:DBSCAN 连片带 / KDE 热点 / 影响范围…"})
        spatial = analyze_spatial(df, req.geometry)
        time_series = None
        if get_settings().trend_enable_timeseries:
            yield _sse("stage", {"stage": "timeseries", "msg": "时序接入:匹配传感器并读取 L1/L2/L3/L4 观测…"})
            time_series = fetch_time_series_for_points(df)
        yield _sse("stage", {"stage": "trend", "msg": "变形趋势分析:识别文本趋势 / 时序异常 / 雨量诱发…"})
        trend = analyze_deformation_trends(df, time_series)
        yield _sse("stage", {"stage": "professional", "msg": "专业增强:雨量-变形耦合 / 预警历史…"})
        warning_history = fetch_warning_history_for_points(df["monitor_point_code"].astype(str).tolist())
        professional = {}
        professional.update(analyze_rain_deformation_coupling(time_series))
        professional.update(analyze_warning_history(warning_history))

        yield _sse("stage", {"stage": "assembly", "msg": "三层装配:占位符 / 重点点位…"})
        placeholders = assemble_placeholders(stats, spatial, df, missing, trend, professional)
        placeholders["report_id"] = report_id
        placeholders["generate_time"] = generate_time
        valid_codes = set(df["monitor_point_code"].astype(str))

        # AI 研判:流式转发,带校验重试
        user_prompt = build_user_prompt(placeholders)
        judgement: dict = {}
        last_errors: list[str] = ["未获得有效研判"]
        for attempt in range(MAX_JUDGE_RETRIES + 1):
            tag = "" if attempt == 0 else f"(第 {attempt + 1} 次)"
            yield _sse("stage", {"stage": "judgement", "msg": f"AI 研判中…{tag}", "attempt": attempt})
            chunks: list[str] = []
            try:
                for kind, text in LLMClient().judge_stream(SYSTEM_PROMPT, user_prompt):
                    if kind == "content":
                        chunks.append(text)
                    yield _sse(kind, {"text": text})
            except Exception as exc:  # noqa: BLE001
                yield _sse("warn", {"msg": f"研判流式中断:{exc}"})
            try:
                judgement = _parse_json("".join(chunks))
            except Exception as exc:  # noqa: BLE001
                last_errors = [f"研判 JSON 解析失败:{exc}"]
                yield _sse("validation", {"ok": False, "errors": last_errors})
                continue
            verdict = validate_judgement(judgement, valid_codes)
            last_errors = verdict["errors"]
            yield _sse("validation", {"ok": verdict["ok"], "errors": verdict["errors"]})
            if verdict["ok"]:
                break
        _apply_degrade(judgement, last_errors)

        # A2UI 交互界面：研判完成、渲染前，将结构化结果转为声明式 UI 组件
        a2ui = build_risk_a2ui(report_id, judgement, stats, spatial)
        if a2ui is not None:
            yield _sse("a2ui", a2ui.model_dump())

        yield _sse("stage", {"stage": "render", "msg": "渲染统计图 / 空间分布图 + 成稿…"})
        resp = _render_response(report_id, req, stats, spatial, df, placeholders, judgement)
        yield _sse("done", resp.model_dump())
    except Exception as exc:  # noqa: BLE001
        yield _sse("error", {"msg": f"{type(exc).__name__}: {exc}"})
