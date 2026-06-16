# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目性质

本仓库是更大系统「**地灾预警 AI Studio**」中的**一个功能模块——「灾圈监测点地质灾害风险研判」(风险报告生成)** 的设计与渲染原型,当前为方案设计阶段。AI Studio 的其余部分(其他功能模块、整体平台代码)不在本仓库范围内,也不归本仓库维护;遇到本功能边界之外的需求,应向上层 AI Studio 项目对接,而非在此臆造。

仓库内容:中文 Markdown 设计文档(单一事实源)+ 3 个 Python 渲染示例脚本(`sample_*.py`)+ **已搭好的 FastAPI 服务骨架(`app/`,stub 阶段,各模块仅签名+docstring,实现以 `NotImplementedError` 占位)**。非 git 仓库,同时是一个 Obsidian vault(`.obsidian/`,勿改)。填实现时应遵循下述既定设计与铁律,而非另起炉灶。

## 核心数据链路

```
CH 空间筛选 → GeoPandas 空间分析 + 代码统计 →（三层装配）→ AI 研判 → 报告渲染
```

- **CH 空间筛选**:从 ClickHouse 取灾圈范围内监测点(筛选阶段即剔除 `is_hex=1` 已核销点)。
- **代码统计 + GeoPandas 空间分析**:确定性核算所有数字与几何(类型/规模/预警分布、威胁汇总、DBSCAN 连片带、KDE 热点、影响范围)。
- **三层装配**:把统计结果、空间结论、语义素材按占位符注入 prompt(后端字符串注入)。
- **AI 研判**:LLM 仅做语义研判,输出固定 JSON。
- **报告渲染**:代码侧 5 道校验后,用模板拼装最终报告 + Plotly 图。

## 贯穿全项目的铁律(改任何环节都必须遵守)

1. **数字交代码、语义交模型**:所有统计数字由代码精确核算;LLM **严禁**计算/估算/求和/求比例/改写任何数字,只能引用。最终稿数字一律以代码值覆盖校对。
2. **结论可溯源**:每条针对具体灾害点的研判/建议必须标注 `monitor_point_code`,且该编号必须在圈内点集合内。
3. **未接入 DEM**:凡涉及坡度/坡向/汇水/沟道/地形诱发的表述,一律基于填报值,须显式注明「(基于填报值,未经地形数据校验)」,不得包装成地形建模结论。
4. **缺失不臆测**:数据缺失/为空/矛盾时显式提示「需现场复核」,缺失计数最终进入 `data_limitations`。
5. **`is_hex=1` 在筛选阶段即过滤**,不进入任何统计。
6. **渲染前 5 道代码校验**(不靠模型自觉,见 `docs/灾圈监测点风险研判_配套装配与渲染说明.md` 第四节):编号溯源校验、来源标注校验、数字一致性、JSON 结构校验、空结果处理(`point_count=0` 不调模型,走简化提示报告)。

## 数据源

- ClickHouse 表 `dwd_gh_v1.dwd_monitor_point_info_view`(监测点信息表),schema 见 `docs/监测点表结构.md`。
- 连接配置(host/port/user/password/table)在 `docs/chconf.md`——**含明文凭据,勿外泄、勿提交到任何远端**;运行时由 `.env` 注入(见 `.env.example`)。
- **字段清洗陷阱**:表中大量数值类字段为 `NULLABLE(STRING)`(如 `threaten_population`、`avg_slope`、`hazard_*`),统计前必须清洗(去单位→转数值,空/非法计 0 并记缺失)。`scale`/`warning_level`/`monitor_point_type` 需归一化(空值分别归「未分级/未定级/未分类」并保留可见)。清洗规则表见 `docs/灾圈监测点风险研判_配套装配与渲染说明.md` 第一节。

## 渲染技术选型(已定,勿擅自更换)

- **全报告统一 Plotly 6.x + kaleido**(图表与地图同一套视觉语言);kaleido 静态导出自带渲染、不依赖系统浏览器。
- **地图用 `go.Scattermap`/`go.Densitymap`(MapLibre)**;旧 `go.Scattermapbox` 已弃用,不要用。底图 `style="open-street-map"` 或 carto 系——**免 token**。
- **分析层(计算几何)**:geopandas、shapely、pyproj、scikit-learn(DBSCAN 聚类)、scipy(KDE/凸包);可选 esda+libpysal(Gi\* 冷热点)、alphashape。
- **架构原则「分析归分析、渲染归 Plotly」**:GIS 计算仍由 sklearn/scipy/shapely 完成,只把算出的**几何**交给 Plotly 画。空间分析**算一次**,结果既喂 AI 研判文字,又用于出图。
- **坐标系铁律**:分析阶段(DBSCAN/缓冲/面积/距离)须在**投影坐标系**(米)下做;渲染阶段 Plotly 地图直接吃 **WGS84 经纬度**——「投影坐标算几何 → 转回经纬度交 Plotly」。
- **中文字体**:Plotly 设 `layout.font.family="Microsoft YaHei"`;kaleido 用系统字体,确保运行环境装有该字体。导出 `scale=2`,PNG(嵌报告)+ SVG(矢量备用)。
- ⚠️ 静态导出需联网拉底图瓦片;内网无外网时底图会空白(点位/几何仍在)。

## 常用命令

尚无测试/lint 体系。

```powershell
# 安装依赖(完整链路)
pip install -r requirements.txt

# 配置:复制模板填入真实 CH/LLM 凭据(取代 docs/chconf.md 明文)
copy .env.example .env

# 启动 FastAPI 服务 → http://127.0.0.1:8000/docs
uvicorn app.main:app --reload

# 导入自检(stub 阶段:导入应通过,业务调用抛 NotImplementedError/返回 501)
python -c "import app.main"
```

> 计划阶段的 Plotly/matplotlib 渲染原型脚本(`sample_*.py`)已删除;其产出图 `sample_*.png` 保留为视觉参照。渲染实现请按 `docs/统计图表内容与技术栈.md`、`docs/空间分析内容与技术栈.md` 在 `app/render/` 内重建。

## 代码结构(`app/`,按数据链路切分)

FastAPI 包 `app/`,链路环节一模块一文件,每个 stub 的 docstring 都回指对应设计文档:

- `app/main.py` / `app/api/{routes,schemas}.py` — 服务入口、`POST /api/v1/risk-report`、请求/响应模型。
- `app/config.py` — 配置(CH/LLM/聚类/渲染),读 `.env`(取代 `docs/chconf.md` 明文)。
- `app/pipeline/` — 链路:`selection`(CH 筛选剔 `is_hex=1`)→ `cleaning`(清洗+缺失计数)→ `statistics`(统计)→ `spatial`(DBSCAN/KDE/凸包)→ `assembly`(三层装配+重点点位)→ `judgement`(LLM 研判)→ `validation`(5 道校验);`orchestrator` 编排(含 `point_count==0` 短路)。
- `app/render/{charts,maps,report}.py` — Plotly 图表/地图、报告拼装。
- `app/prompts/risk_judgement.py` — System/User prompt,与 `docs/灾圈监测点风险研判提示词.md` 同步。
- `app/clients/{clickhouse,llm}.py` — CH / LLM 客户端封装。

> 设计文档现集中于 `docs/`,是单一事实源;`app/` 是其落地骨架。`app/` 内 docstring 提及的文档名(多为简写)均指 `docs/` 下对应文件。改 prompt/schema/清洗规则,先改文档再改代码。

## 文档导航(设计文档集中于 `docs/`)

- `docs/灾圈监测点风险研判提示词.md` — **核心 prompt**:System(角色+硬性护栏)、User(输入分区+任务+输出 JSON schema)、占位符清单、调用要点(低温+JSON 模式)。
- `docs/灾圈监测点风险研判_配套装配与渲染说明.md` — prompt 的配套:字段清洗规则、三层装配(占位符如何生成)、重点点位筛选规则(`key_points_detail`,≤30 条)、渲染前 5 道校验、研判 JSON→报告章节映射。
- `docs/灾圈监测点风险研判_报告成稿模板.md` — 报告成稿骨架,`{{代码占位符}}` 由统计填充、`{{研判.字段}}` 来自 AI JSON;末尾有渲染占位符索引。
- `docs/统计图表内容与技术栈.md` — 报告第三章图表(类型/规模/预警/隐患/威胁)的 Plotly trace 与配色规范。
- `docs/空间分析内容与技术栈.md` — 报告第四章空间分布图的 7 个图层、分析方法与渲染栈。
- `docs/监测点表结构.md` — 数据源表完整 schema。
- `docs/chconf.md` — ClickHouse 连接配置(敏感,运行时由 `.env` 注入)。
- `docs/everything-is-here.md` — 技术选型调研外链。
- `sample_*.png`(根目录)— 计划阶段渲染原型的产出图,留作视觉参照(对应脚本已删除)。

> 改 prompt 输出 schema 时,务必同步检查 `docs/灾圈监测点风险研判_配套装配与渲染说明.md`(JSON→章节映射)与 `docs/灾圈监测点风险研判_报告成稿模板.md`(占位符),三者强耦合。

## 项目约定

**每次改动后必须同步更新 `docs/changelog.md`，追加本次改动的文件清单与变更说明。**
**think in Chinese**
