"""
数据访问原语：查询、一次性消费、savepoint 隔离更新。
服务层里反复出现的三件事都归约到这里，统一用 SQLAlchemy 条件表达式：
  get_or_raise   —— 查一行，没查到就抛领域错误
  consume_once   —— 条件满足才恰好更新一行（一次性 token/事务消费）
  isolated_update—— 在 savepoint 里更新，调用方事务回滚也不影响
"""

from typing import Any, TypeVar

from sqlalchemy import Result, Select, Update, select, update as sa_update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError, ErrCode

M = TypeVar("M")


async def get_or_raise(
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


async def consume_once(
    db: AsyncSession,
    model: type[M],
    values: dict[str, object],
    *conditions: Any,
) -> bool:
    """仅当全部条件满足时更新恰好一行；否则返回 False。

    用于一次性 token / 恢复事务 / 挑战码的原子消费，防止并发重放。
    """
    result = await db.execute(sa_update(model).where(*conditions).values(**values))
    await db.flush()
    return (getattr(result, "rowcount", 0) or 0) == 1


async def isolated_update(db: AsyncSession, stmt: Update) -> None:
    """在 savepoint 中执行一条 UPDATE，失败时静默回滚。

    失败计数器等"即使调用方事务回滚也要保留"的修改用它。
    """
    sp = await db.begin_nested()
    try:
        await db.execute(stmt)
        await db.flush()
        await sp.commit()
    except (IntegrityError, OperationalError):
        await sp.rollback()
