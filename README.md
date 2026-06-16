# 灾圈监测点风险研判

「地灾预警 AI Studio」的一个功能模块:根据灾圈圈定范围,对圈内地质灾害监测点做综合风险研判,
生成结构化研判结果与可视化报告。本仓库当前为 **FastAPI 服务骨架(stub 阶段)**,实现待填充。

> 设计原则:**数字交代码、语义交模型、结论可溯源、来源要标注**。详见 `CLAUDE.md` 与各设计文档。

## 数据链路

```
CH 空间筛选 → 空间分析 + 代码统计 →(三层装配)→ AI 研判 → 报告渲染
```

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env   # 填入 CH / LLM 等真实配置

uvicorn app.main:app --reload
# 打开 http://127.0.0.1:8000/docs
```

> 骨架阶段:`POST /api/v1/risk-report` 返回 501(未实现),`GET /health` 正常返回。

## 代码结构

| 路径 | 职责 | 对应设计文档 |
|---|---|---|
| `app/main.py` / `app/api/` | FastAPI 入口、路由、请求/响应模型 | — |
| `app/config.py` | 配置(CH/LLM/聚类/渲染),读 `.env` | `docs/chconf.md` |
| `app/pipeline/selection.py` | CH 空间筛选,剔除 `is_hex=1` | docs/配套装配与渲染说明.md 一 |
| `app/pipeline/cleaning.py` | 字段清洗/归一化、缺失计数 | docs/配套装配与渲染说明.md 一 |
| `app/pipeline/statistics.py` | 代码统计(分布/汇总) | docs/统计图表内容与技术栈.md |
| `app/pipeline/spatial.py` | 空间分析(DBSCAN/KDE/凸包) | docs/空间分析内容与技术栈.md |
| `app/pipeline/assembly.py` | 三层装配、重点点位筛选 | docs/配套装配与渲染说明.md 二、三 |
| `app/pipeline/judgement.py` | AI 研判(prompt→LLM→JSON) | docs/灾圈监测点风险研判提示词.md |
| `app/pipeline/validation.py` | 渲染前 5 道校验 | docs/配套装配与渲染说明.md 四 |
| `app/pipeline/orchestrator.py` | 链路编排 | 全链路 |
| `app/render/` | Plotly 图表 / 地图 / 报告拼装 | docs/(统计图表·空间分析·报告成稿模板) |
| `app/prompts/` | System/User prompt 模板 | docs/灾圈监测点风险研判提示词.md |
| `app/clients/` | ClickHouse / LLM 客户端 | docs/(chconf.md · 提示词.md) |

> 设计文档集中于 `docs/`,是单一事实源,改 prompt/schema 须同步。根目录 `sample_*.png` 为计划阶段渲染原型的产出图(对应脚本已删除,留作视觉参照)。
