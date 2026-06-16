"""运行配置:从环境变量(.env)读取,取代 chconf.md 中的明文凭据。

对应:`chconf.md`(CH 连接)、`空间分析内容与技术栈.md`(聚类/坐标系参数)、
`统计图表内容与技术栈.md`(配色与字体)。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。字段从环境变量或 .env 读取(见 .env.example)。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- ClickHouse(数据源,见 监测点表结构.md)----
    ch_host: str = "127.0.0.1"
    ch_port: int = 8123
    ch_user: str = ""
    ch_password: str = ""
    ch_table: str = "dwd_gh_v1.dwd_monitor_point_info_view"
    # CH 模拟数据 CSV 路径（非空时跳过 CH 查询，改为从 CSV 加载 + 空间筛选）
    ch_mock_csv: str = ""

    # ---- LLM(AI 研判,低温 + JSON 模式,见 风险研判提示词.md「调用与落地要点」)----
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_temperature: float = 0.2  # 低温保稳定

    # ---- 空间分析参数(投影坐标系下,单位米;见 配套装配与渲染说明.md 二)----
    dbscan_eps_m: float = 500.0
    dbscan_min_samples: int = 3
    projected_crs: str = "EPSG:4544"  # CGCS2000 3-degree Gauss-Kruger(按业务区域调整)

    # ---- 重点点位与渲染(见 配套装配与渲染说明.md 三 / 渲染技术栈)----
    key_points_max: int = 30
    chart_font_family: str = "Microsoft YaHei"
    export_scale: int = 2


@lru_cache
def get_settings() -> Settings:
    """单例配置访问入口。"""
    return Settings()
