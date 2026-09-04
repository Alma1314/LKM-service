"""内容（Content）模块：boards/columns/qa 聚合。模块公共 API——跨模块 import 的唯一合法入口。"""

from __future__ import annotations

from typing import Any

_exported_routers: list[Any] | None = None
_exported_graphql: list[Any] | None = None


def __getattr__(name: str) -> Any:
    global _exported_routers, _exported_graphql
    if name == "ROUTERS":
        if _exported_routers is None:
            from app.modules.content.router import router

            _exported_routers = [router]
        return _exported_routers
    if name == "GRAPHQL":
        if _exported_graphql is None:
            from app.modules.content.columns.graphql import ColumnsQuery
            from app.modules.content.graphql import ContentQuery

            _exported_graphql = [ContentQuery, ColumnsQuery]
        return _exported_graphql
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
