"""后端 RBAC 权限统一框架：权限点、角色映射、依赖工厂。

仅供依赖注入框架使用，不挂载任何路由/GraphQL，故不暴露 ROUTERS/GRAPHQL。
"""
from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
