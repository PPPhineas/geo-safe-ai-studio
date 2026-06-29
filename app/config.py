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

    # ---- 时序趋势分析(见 mschema: L1/L2/L3/L4 监测数据)----
    trend_enable_timeseries: bool = False
    trend_lookback_days: int = 30
    trend_forecast_days: int = 3
    trend_min_samples: int = 4
    trend_deformation_rate_warn: float = 1.0  # mm/day 或同源累计位移单位/day
    trend_deformation_rate_high: float = 5.0
    trend_acceleration_ratio: float = 2.0
    trend_rain_24h_warn: float = 25.0
    trend_rain_72h_warn: float = 50.0

    # ---- 雨强分级阈值(mm/24h,中国气象局标准)----
    rain_intensity_moderate: float = 10.0   # >=10mm 中雨
    rain_intensity_heavy: float = 25.0      # >=25mm 大雨
    rain_intensity_storm: float = 50.0      # >=50mm 暴雨
    rain_intensity_severe_storm: float = 100.0  # >=100mm 大暴雨
    timeseries_max_sensors_per_level: int = 30000  # 单层最大传感器数(超量截断,防 OOM/超时)

    # ---- 专业增强分析 ----
    warning_history_lookback_days: int = 90


@lru_cache
def get_settings() -> Settings:
    """单例配置访问入口。"""
    return Settings()
