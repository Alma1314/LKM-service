"""积分服务：balance 原子写 + ledger 幂等流水，reward/spend/transfer/排行榜。"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import (
    bump_collection_version,
    cache_invalidate,
    cached_read,
    collection_version,
    make_key,
)
from app.core.err import BizError
from app.db.models import (
    PointsLedger,
    Profile,
    User,
    UserBalance,
    now_iso,
)
from app.modules.common import PageData, paginate_offset, paginate_pages
from app.modules.points.errors import PointsErr
from app.modules.points.schemas import LeaderboardEntry, LedgerEntry


async def ensure_balance(db: AsyncSession, user_id: int) -> UserBalance:
    """惰性取/建用户 balance 行。"""
    row = await db.get(UserBalance, user_id)
    if row is not None:
        return row
    rb = UserBalance(user_id=user_id, balance=0)
    db.add(rb)
    await db.flush()
    return rb


async def _apply_delta(
    db: AsyncSession, user_id: int, delta: int, allow_negative: bool
) -> int:
    """原子增减 balance 并返回变动后的新余额。

    用 ``WHERE balance + delta >= 0`` 约束（允许负时无条件），rowcount==0 表示
    余额不足或用户无记录 → 视为不足。同一事务内该更新对并发安全。
    """
    stmt = sa_update(UserBalance).where(UserBalance.user_id == user_id)
    if allow_negative:
        stmt = stmt.values(balance=UserBalance.balance + delta, updated_at=now_iso())
    else:
        stmt = stmt.where(UserBalance.balance + delta >= 0).values(
            balance=UserBalance.balance + delta, updated_at=now_iso()
        )
    result = await db.execute(stmt)
    if (getattr(result, "rowcount", 0) or 0) == 0:
        raise BizError(PointsErr.INSUFFICIENT_BALANCE, "积分余额不足，或账户未初始化")
    row = await db.get(UserBalance, user_id)
    assert row is not None
    return int(row.balance)


async def reward(
    db: AsyncSession,
    user_id: int,
    delta: int,
    reason: str,
    ref_type: str,
    ref_id: str,
    *,
    allow_negative: bool = False,
) -> LedgerEntry:
    """发放/扣减积分（原子、幂等）。delta 为负表扣分（处罚），allow_negative 放开余额下限。

    幂等：同 (user_id, ref_type, ref_id) 已发过→delta 一致则跳过返回已有流水，
    不一致抛 DUPLICATE_REWARD。返回本次（或既有）流水。
    """
    existing = await db.scalar(
        select(PointsLedger.id).where(
            PointsLedger.user_id == user_id,
            PointsLedger.ref_type == ref_type,
            PointsLedger.ref_id == ref_id,
        )
    )
    if existing is not None:
        entry = (
            (await db.execute(select(PointsLedger).where(PointsLedger.id == existing)))
            .scalars()
            .first()
        )
        if entry is not None and entry.delta == delta:
            return LedgerEntry.model_validate(entry)
        raise BizError(PointsErr.DUPLICATE_REWARD)

    await ensure_balance(db, user_id)
    balance_after = await _apply_delta(db, user_id, delta, allow_negative)
    entry = PointsLedger(
        user_id=user_id,
        delta=delta,
        balance_after=balance_after,
        reason=reason,
        ref_type=ref_type,
        ref_id=ref_id,
    )
    db.add(entry)
    try:
        await db.flush()
    except IntegrityError:
        # 同 (user, ref_type, ref_id) 的并发 insert 被唯一约束拦截 → 视为已发放（幂等）。
        # 回滚本次插入，返回既有流水（其 delta 应与本次一致；不一致属异常，抛 DUPLICATE_REWARD）。
        await db.rollback()
        existing = await db.scalar(
            select(PointsLedger.id).where(
                PointsLedger.user_id == user_id,
                PointsLedger.ref_type == ref_type,
                PointsLedger.ref_id == ref_id,
            )
        )
        row = None
        if existing is not None:
            row = (
                (
                    await db.execute(
                        select(PointsLedger).where(PointsLedger.id == existing)
                    )
                )
                .scalars()
                .first()
            )
        if row is not None and row.delta == delta:
            return LedgerEntry.model_validate(row)
        raise BizError(PointsErr.DUPLICATE_REWARD) from None
    await bump_collection_version("points")
    await cache_invalidate(make_key("points:balance", user_id))
    return LedgerEntry.model_validate(entry)


async def spend(
    db: AsyncSession,
    user_id: int,
    amount: int,
    reason: str,
    ref_type: str,
    ref_id: str,
) -> LedgerEntry:
    """消费积分（余额不足拒）。amount>0。"""
    if amount <= 0:
        raise BizError(PointsErr.INSUFFICIENT_BALANCE, "消费金额须为正")
    return await reward(db, user_id, -amount, reason, ref_type, ref_id)


async def transfer(
    db: AsyncSession,
    from_id: int,
    to_id: int,
    amount: int,
    reason: str,
    ref_type: str,
    ref_id: str,
) -> tuple[LedgerEntry, LedgerEntry]:
    """1:1 原子转账：from 扣 + to 加，两笔流水共享 (ref_type, ref_id) 实现幂等。

    单事务内完成；任一失败（如 from 余额不足）整体回滚，不产生部分流水。
    """
    if amount <= 0:
        raise BizError(PointsErr.INSUFFICIENT_BALANCE, "转账金额须为正")
    if from_id == to_id:
        raise BizError(PointsErr.INSUFFICIENT_BALANCE, "不能转账给自己")
    await ensure_balance(db, from_id)
    await ensure_balance(db, to_id)
    from_after = await _apply_delta(db, from_id, -amount, allow_negative=False)
    to_after = await _apply_delta(db, to_id, amount, allow_negative=True)
    out_entry = PointsLedger(
        user_id=from_id,
        delta=-amount,
        balance_after=from_after,
        reason="transfer_out",
        ref_type=ref_type,
        ref_id=ref_id,
    )
    in_entry = PointsLedger(
        user_id=to_id,
        delta=amount,
        balance_after=to_after,
        reason="transfer_in",
        ref_type=ref_type,
        ref_id=ref_id,
    )
    db.add(out_entry)
    db.add(in_entry)
    await db.flush()
    await bump_collection_version("points")
    await cache_invalidate(make_key("points:balance", from_id))
    await cache_invalidate(make_key("points:balance", to_id))
    return LedgerEntry.model_validate(out_entry), LedgerEntry.model_validate(in_entry)


async def get_balance(db: AsyncSession, user_id: int) -> int:
    """取用户当前余额（读缓存；缺失按 0）。"""

    async def load() -> int:
        existing = await db.scalar(
            select(UserBalance.balance).where(UserBalance.user_id == user_id)
        )
        if existing is None:
            return 0
        return int(existing)

    return await cached_read(make_key("points:balance", user_id), 60, load)


async def list_ledger(
    db: AsyncSession, user_id: int, page: int = 1, limit: int = 20
) -> PageData[LedgerEntry]:
    """分页列出用户的积分流水（新→旧）。"""
    total = (
        await db.scalar(
            select(func.count(PointsLedger.id)).where(PointsLedger.user_id == user_id)
        )
        or 0
    )
    stmt = (
        select(PointsLedger)
        .where(PointsLedger.user_id == user_id)
        .order_by(PointsLedger.id.desc())
        .offset(paginate_offset(page, limit))
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    items = [LedgerEntry.model_validate(r) for r in rows]
    return PageData(
        items=items, total=total, page=page, pages=paginate_pages(total, limit)
    )


async def leaderboard(db: AsyncSession, limit: int = 50) -> list[LeaderboardEntry]:
    """按余额降序的积分榜（仅 balance>0 用户）。缓存。"""

    async def load() -> list[dict[str, Any]]:
        rows = (
            await db.execute(
                select(User, Profile.nickname, UserBalance.balance)
                .outerjoin(Profile, Profile.user_id == User.id)
                .join(UserBalance, UserBalance.user_id == User.id)
                .where(UserBalance.balance > 0)
                # 主序余额降序；同余额按 display_name（昵称）升序，昵称可空，
                # nullsfirst 让无昵称者（退化为 username）排在前面；User.id 作最终稳定序。
                .order_by(
                    UserBalance.balance.desc(),
                    Profile.nickname.asc().nullsfirst(),
                    User.id.asc(),
                )
                .limit(limit)
            )
        ).all()
        result: list[dict[str, Any]] = []
        for user, nickname, balance in rows:
            result.append(
                {
                    "user_id": user.id,
                    "display_name": nickname or user.username or "",
                    "balance": int(balance or 0),
                }
            )
        return result

    ver = await collection_version("points")
    payload = await cached_read(make_key("points:leaderboard", ver, limit), 60, load)
    return [LeaderboardEntry.model_validate(p) for p in payload]
