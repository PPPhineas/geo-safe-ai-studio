"""路由:风险报告生成端点。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from app.api.schemas import A2uiActionRequest, RiskReportRequest, RiskReportResponse
from app.pipeline.orchestrator import (
    build_bundle,
    generate_risk_report,
    generate_risk_report_stream,
)

router = APIRouter(tags=["risk-report"])


@router.post("/risk-report", response_model=RiskReportResponse)
def create_risk_report(req: RiskReportRequest) -> RiskReportResponse:
    """根据灾圈几何生成地质灾害风险研判报告。

    链路见 app.pipeline.orchestrator.generate_risk_report。
    """
    try:
        return generate_risk_report(req)
    except NotImplementedError as exc:  # 仍未实现的环节
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc) or "未实现"
        ) from exc
    except Exception as exc:  # CH / LLM / 渲染等运行期错误,回传明细便于排查
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc


@router.post("/risk-report/stream")
def create_risk_report_stream(req: RiskReportRequest) -> StreamingResponse:
    """流式生成报告(SSE)。逐阶段推进 + 实时转发 AI 研判思考/输出,末尾发完整报告。

    事件:stage / reasoning / content / validation / a2ui / warn / done / error。
    """
    return StreamingResponse(
        generate_risk_report_stream(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用反代缓冲,确保逐块下发
        },
    )


@router.post("/a2ui/action", tags=["a2ui"])
def handle_a2ui_action(req: A2uiActionRequest) -> dict:
    """接收前端 A2UI 交互操作回传。

    当前阶段：记录并返回确认。后续可接 agent 二次研判、报告更新等。
    """
    return {"status": "acknowledged", "report_id": req.report_id, "action": req.action}


@router.get("/risk-report/{report_id}/bundle")
def download_bundle(report_id: str) -> Response:
    """下载报告压缩包(zip):report.md(链接改为相对 figures/)+ 图件 + 附件 CSV + 研判 JSON。

    解压后离线打开 report.md 即可显示图片/附件,无需再依赖在线 /static 资源。
    """
    try:
        data = build_bundle(report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{report_id}.zip"'},
    )
