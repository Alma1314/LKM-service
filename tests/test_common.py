"""模块6 去重收敛：common 共享 helper（parse_tags / 分页 / 标签序列 / 批量 Profile）。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.common import (
    PageData,
    paginate_offset,
    paginate_pages,
    parse_tags,
    tag_names_sequence,
)


def test_parse_tags_list_passthrough() -> None:
    assert parse_tags(["a", "b"]) == ["a", "b"]


def test_parse_tags_json_string() -> None:
    assert parse_tags('["x", "y"]') == ["x", "y"]


def test_parse_tags_invalid_falls_back_empty() -> None:
    assert parse_tags(123) == []
    assert parse_tags("not-json") == []
    assert parse_tags('{"a":1}') == []  # 非列表回退


def test_paginate_math() -> None:
    assert paginate_offset(1, 20) == 0
    assert paginate_offset(3, 10) == 20
    assert paginate_pages(0, 20) == 0
    assert paginate_pages(20, 20) == 1
    assert paginate_pages(21, 20) == 2


def test_tag_names_sequence_dedups_preserving_order() -> None:
    assert tag_names_sequence(["a", "", "b", "a", "c"]) == ["a", "b", "c"]
    assert tag_names_sequence([]) == []
    assert tag_names_sequence(["", ""]) == []


async def test_get_profiles_by_user_ids_fills_none_for_missing(
    db: AsyncSession,
) -> None:
    """批量查询：已存在的 id 映射回 ProfileInfo，缺失 id 显式 None。"""
    from app.db.models import Profile, User
    from app.db.repo import get_profiles_by_user_ids

    u1 = User(
        username="prof1",
        email="prof1@example.com",
        hashed_password="x",
        account_level="normal",
    )
    db.add(u1)
    await db.flush()
    db.add(Profile(user_id=u1.id, nickname="Prof One"))
    await db.flush()

    result = await get_profiles_by_user_ids(db, {u1.id, 999_999})
    assert result[u1.id] is not None
    assert result[999_999] is None
    assert await get_profiles_by_user_ids(db, set()) == {}


def test_PageData_shape() -> None:
    data = PageData[int](items=[1, 2], total=2, page=1, pages=1)
    assert data.model_dump()["pages"] == 1
