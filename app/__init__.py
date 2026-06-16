"""灾圈监测点风险研判 —— 「地灾预警 AI Studio」的一个功能模块(风险报告生成)。

FastAPI 服务骨架。数据链路:
    CH 空间筛选 → 空间分析 + 代码统计 →(三层装配)→ AI 研判 → 报告渲染

设计铁律见仓库根目录 CLAUDE.md 与 `docs/` 下各设计文档。
本包当前为 stub 阶段:各模块仅有签名 + docstring,实现以 `NotImplementedError` 占位。

约定:本包 docstring/注释中提及的设计文档名(多为简写,如「配套装配与渲染说明.md」)
与 `chconf.md` 均位于仓库 `docs/` 目录。
"""

__version__ = "0.0.1"
