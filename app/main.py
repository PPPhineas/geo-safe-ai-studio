"""FastAPI 应用入口。

启动:
    uvicorn app.main:app --reload

交互式文档:http://127.0.0.1:8000/docs
前端 UI(选灾圈→生成→预览/下载):http://127.0.0.1:8000/ui/
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as risk_router

app = FastAPI(
    title="灾圈监测点风险研判",
    description="地灾预警 AI Studio · 风险报告生成模块",
    version="0.0.1",
)

# 允许跨源调用(便于前端单独部署/调试)。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(risk_router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """存活探针。"""
    return {"status": "ok"}


# 渲染图件以静态资源对外:/static/figures/{report_id}/{key}.png
_STATIC_DIR = Path(__file__).resolve().parents[1] / "output"
_STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# 前端 UI(tests/ui/index.html),与 API 同源,避免跨域、图件直接可达。
_UI_DIR = Path(__file__).resolve().parents[1] / "tests" / "ui"
_UI_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")
