"""积分系统：balance + ledger 账本，reward/spend/transfer 原子原语，排行榜。模块公共 API——跨模块 import 的唯一合法入口。"""
from __future__ import annotations

from typing import Any

_exported_routers: list[Any] | None = None
_exported_graphql: list[Any] | None = None


def __getattr__(name: str) -> Any:
    global _exported_routers, _exported_graphql
    if name == "ROUTERS":
        if _exported_routers is None:
            from app.modules.points.router import router

            _exported_routers = [router]
        return _exported_routers
    if name == "GRAPHQL":
        if _exported_graphql is None:
            _exported_graphql = []
        return _exported_graphql
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
