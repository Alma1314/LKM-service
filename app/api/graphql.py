"""GraphQL 聚合（§7）：把各模块经 registry 暴露的 Query 类 merge 成统一 schema。

原聚合逻辑在 main.py（merge_types 7 个 Query 类），P5 收敛到此，main 只装配。
新增模块的 GraphQL 查询：模块 __init__.py 暴露 ``GRAPHQL``，registry 自动聚合。
"""

from __future__ import annotations

from typing import Any

import strawberry
from strawberry.tools import merge_types

from app.modules import registry


def _all_graphql_types() -> list[type[Any]]:
    types: list[type[Any]] = []
    for name in registry.MODULES:
        types.extend(registry.graphql_of(name))
    return types


def build_schema() -> strawberry.Schema:
    """合并全部模块 GraphQL Query/Mutation 类，构建 schema。"""
    classes = tuple(_all_graphql_types())
    merged_query = merge_types("Query", classes)  # type: ignore[arg-type]
    return strawberry.Schema(query=merged_query)
