"""
数据访问原语：查询、一次性消费、savepoint 隔离更新。
服务层里反复出现的三件事都归约到这里，统一用 SQLAlchemy 条件表达式：
  get_or_raise   —— 查一行，没查到就抛领域错误
  consume_once   —— 条件满足才恰好更新一行（一次性 token/事务消费）
  isolated_update—— 在 savepoint 里更新，调用方事务回滚也不影响
"""

from typing import Any

from sqlalchemy import Result, Select, Update, select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError, ErrCode
from app.modules.auth.schemas import ProfileInfo


async def get_or_raise[M](
    db: AsyncSession,
    model: type[M],
    errcode: ErrCode,
    *conditions: Any,
    detail: str | None = None,
    options: tuple[Any, ...] = (),
) -> M:
    """按条件查一行，未命中则抛出 ``BizError(errcode)``。"""
    stmt: Select[Any] = select(model).where(*conditions)
    if options:
        stmt = stmt.options(*options)
    result: Result[Any] = await db.execute(stmt)
    obj: M | None = result.scalars().first()
    if obj is None:
        raise BizError(errcode, detail)
    return obj


async def consume_once[M](
    db: AsyncSession,
    model: type[M],
    values: dict[str, object],
    *conditions: Any,
) -> bool:
    """
    用于一次性 token / 恢复事务 / 挑战码的原子消费，防止并发重放。
    """
    result = await db.execute(sa_update(model).where(*conditions).values(**values))
    await db.flush()
    return (getattr(result, "rowcount", 0) or 0) == 1


async def isolated_update(db: AsyncSession, stmt: Update) -> None:
    """
    失败计数器等"即使调用方事务回滚也要保留"的修改用它。
    """
    sp = await db.begin_nested()
    try:
        await db.execute(stmt)
        await db.flush()
        await sp.commit()
    except (IntegrityError, OperationalError):
        await sp.rollback()


async def get_profiles_by_user_ids(
    db: AsyncSession, user_ids: set[int]
) -> dict[int, ProfileInfo | None]:
    """批量查询多个用户的 Profile（避免 N+1），映射 user_id -> ProfileInfo | None。

    blog 与 articles 两处重复的批量 Profile 查询收敛于此；未命中的 id 显式落 None，
    使返回 dict 类型稳定（含 None 值）。
    """
    ids = set(user_ids)
    result: dict[int, ProfileInfo | None] = {uid: None for uid in ids}
    if not ids:
        return {}
    from sqlalchemy import select

    from app.db.models import Profile

    rows = (
        (await db.execute(select(Profile).where(Profile.user_id.in_(ids))))
        .scalars()
        .all()
    )
    for p in rows:
        result[p.user_id] = ProfileInfo.model_validate(p)
    return result
