"""关注关系模块：用户/版块关注，时间线过滤数据源。模块公共 API——跨模块 import 的唯一合法入口。"""

from __future__ import annotations

from typing import Any

_exported_routers: list[Any] | None = None
_exported_graphql: list[Any] | None = None


def __getattr__(name: str) -> Any:
    global _exported_routers, _exported_graphql
    if name == "ROUTERS":
        if _exported_routers is None:
            from app.modules.follow.router import (
                board_follow_router,
                user_follow_router,
            )

            _exported_routers = [user_follow_router, board_follow_router]
        return _exported_routers
    if name == "GRAPHQL":
        if _exported_graphql is None:
            from app.modules.follow.graphql import FollowQuery

            _exported_graphql = [FollowQuery]
        return _exported_graphql
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
