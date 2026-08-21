import json
from collections.abc import Sequence
from typing import cast

from pydantic import BaseModel


class ApiResp[T](BaseModel):
    code: int
    msg: str
    data: T | None = None


class ListData[T](BaseModel):
    items: list[T]


class ModuleStatus(BaseModel):
    module: str
    status: str = "planned"
    responsibility: str
    next_steps: list[str]


class PageData[T](BaseModel):
    """分页响应：items + 元信息。跨模块（forum/files）共用，收敛重复定义。"""

    items: list[T]
    total: int
    page: int
    pages: int


def parse_tags(value: object) -> list[str]:
    """把 ``list`` 或 JSON 字符串形式的标签解析为 ``list[str]``。

    forum/files 的 ``tags`` 字段在 DB 里以 JSON 文本存储（跨驱动），统一入口：
    非法 JSON / 非列表均回退为空列表，避免下游拿到 dict/str 的类型漂移。
    """
    if isinstance(value, list):
        return cast("list[str]", value)
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(parsed, list):
        return cast("list[str]", parsed)
    return []


def paginate_offset(page: int, page_size: int) -> int:
    """分页偏移：(page-1)*page_size。收敛 forum/files 里重复的 offset 计算。"""
    return (page - 1) * page_size


def paginate_pages(total: int, page_size: int) -> int:
    """分页总页数：向上取整。收敛 forum/files 里重复的 pages 计算。"""
    return (total + page_size - 1) // page_size


def tag_names_sequence(names: Sequence[str]) -> list[str]:
    """去空 + 保首现顺序去重，供标签序列规范化（勿用 set，避免顺序随机）。"""
    seen: set[str] = set()
    result: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            result.append(n)
    return result
