"""信息流(feed)域：社交图(关注) + read-time 时间线(read 合流)。

M2.3 物理合一 follow（用户/版块关注，时间线过滤数据源）与 timeline（read-time 合流 +
关注过滤 + 审校降权）：社交图 + 信息流语义归为单一 feed 域。模块公共 API——跨模块 import
的唯一合法入口。

``ROUTERS`` = user_follow_router(/users…) + board_follow_router(/content/boards…) +
timeline_router(/timeline…)；``GRAPHQL`` = FollowQuery + TimelineQuery 两 Query 类
（api 层 merge_types 合并进单一 GraphQL Query）。REST URL 前缀与 GraphQL 字段名在聚合中
保持不破。
"""

from __future__ import annotations

from typing import Any

_exported_routers: list[Any] | None = None
_exported_graphql: list[Any] | None = None


def __getattr__(name: str) -> Any:
    global _exported_routers, _exported_graphql
    if name == "ROUTERS":
        if _exported_routers is None:
            from app.modules.feed.router import (
                board_follow_router,
                timeline_router,
                user_follow_router,
            )

            _exported_routers = [
                user_follow_router,
                board_follow_router,
                timeline_router,
            ]
        return _exported_routers
    if name == "GRAPHQL":
        if _exported_graphql is None:
            from app.modules.feed.graphql import FollowQuery, TimelineQuery

            _exported_graphql = [FollowQuery, TimelineQuery]
        return _exported_graphql
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
