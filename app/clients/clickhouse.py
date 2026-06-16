"""ClickHouse 客户端封装。

连接参数来自 config.Settings(取代 chconf.md 明文)。数据源表见 监测点表结构.md。
用 clickhouse-connect(HTTP 接口,与 chconf 的端口一致)。
"""

from __future__ import annotations

from typing import Any

import clickhouse_connect

from app.config import Settings, get_settings


class ClickHouseClient:
    """ClickHouse 查询封装。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = clickhouse_connect.get_client(
            host=self.settings.ch_host,
            port=self.settings.ch_port,
            username=self.settings.ch_user,
            password=self.settings.ch_password,
            connect_timeout=15,
            send_receive_timeout=120,
        )

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        """执行查询,返回行字典列表。

        Args:
            sql: SQL 语句;值用 ``{name:Type}`` 形式参数化(仅值,不含标识符)。
            params: 参数字典,服务端绑定,避免注入。

        Returns:
            每行一个 dict(列名 → 值)。
        """
        result = self._client.query(sql, parameters=params or {})
        columns = result.column_names
        return [dict(zip(columns, row)) for row in result.result_rows]
