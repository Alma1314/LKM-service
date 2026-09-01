"""积分模块测试：并发 / 幂等 / 转账 / 流水一致性。

覆盖 reward/spend/transfer 的原子、幂等与余额界，排行榜排序、分页与路由鉴权。
"""

import asyncio
import os

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.core.err import BizError
from app.db.base import Base
from app.modules.auth.models import Profile, User
from app.modules.auth.security import hashpwd
from app.modules.points.errors import PointsErr
from app.modules.points.service import (
    get_balance,
    leaderboard,
    list_ledger,
    reward,
    spend,
    transfer,
)


async def _spend_in_session(
    factory: async_sessionmaker[AsyncSession],
    uid: int,
    amount: int,
    ref_type: str,
    ref_id: str,
) -> None:
    """在独立会话中扣款并提交，用于构造真正的数据库级并发。"""
    async with factory() as s:
        await spend(s, uid, amount, "consume", ref_type, ref_id)
        await s.commit()


async def _user(
    db: AsyncSession, username: str = "alice", nickname: str | None = None
) -> int:
    u = User(
        username=username,
        email=f"{username}@e.com",
        hashed_password=await hashpwd("secret123"),
        account_level="normal",
    )
    db.add(u)
    await db.flush()
    db.add(Profile(user_id=u.id, nickname=nickname))
    await db.flush()
    return u.id


class TestReward:
    async def test_reward_credits(self, db: AsyncSession):
        uid = await _user(db)
        entry = await reward(db, uid, 100, "test", "ref_t", "1")
        assert entry.delta == 100
        assert entry.balance_after == 100
        assert await get_balance(db, uid) == 100

    async def test_reward_idempotent(self, db: AsyncSession):
        uid = await _user(db)
        await reward(db, uid, 50, "test", "ref_t", "1")
        second = await reward(db, uid, 50, "test", "ref_t", "1")
        assert second.delta == 50
        assert await get_balance(db, uid) == 50  # 未重复加分

    async def test_reward_duplicate_delta_mismatch(self, db: AsyncSession):
        uid = await _user(db)
        await reward(db, uid, 50, "test", "ref_t", "1")
        with pytest.raises(BizError) as e:
            await reward(db, uid, 80, "test", "ref_t", "1")
        assert e.value.errcode == PointsErr.DUPLICATE_REWARD

    async def test_reward_negative_insufficient(self, db: AsyncSession):
        uid = await _user(db)
        await reward(db, uid, 30, "test", "a", "1")
        with pytest.raises(BizError) as e:
            await reward(db, uid, -50, "test", "b", "1")  # 30-50<0
        assert e.value.errcode == PointsErr.INSUFFICIENT_BALANCE

    async def test_reward_negative_allowed(self, db: AsyncSession):
        uid = await _user(db)
        await reward(db, uid, -10, "penalty", "c", "1", allow_negative=True)
        assert await get_balance(db, uid) == -10


class TestSpend:
    async def test_spend_ok(self, db: AsyncSession):
        uid = await _user(db)
        await reward(db, uid, 100, "test", "x", "1")
        await spend(db, uid, 40, "consume", "x", "2")
        assert await get_balance(db, uid) == 60

    async def test_spend_insufficient(self, db: AsyncSession):
        uid = await _user(db)
        await reward(db, uid, 10, "test", "x", "1")
        with pytest.raises(BizError) as e:
            await spend(db, uid, 20, "consume", "x", "2")
        assert e.value.errcode == PointsErr.INSUFFICIENT_BALANCE


class TestTransfer:
    async def test_transfer_moves_balances(self, db: AsyncSession):
        a = await _user(db, "a")
        b = await _user(db, "b")
        await reward(db, a, 100, "test", "z", "1")
        out_e, in_e = await transfer(db, a, b, 40, "pay", "trx", "1")
        assert out_e.delta == -40
        assert in_e.delta == 40
        assert await get_balance(db, a) == 60
        assert await get_balance(db, b) == 40

    async def test_transfer_idempotent(self, db: AsyncSession):
        a = await _user(db, "a")
        b = await _user(db, "b")
        await reward(db, a, 100, "test", "z", "1")
        await transfer(db, a, b, 40, "pay", "trx", "1")
        # 重复同 ref → from 侧 transfer_out 行触发 (user, ref_type, ref_id) 唯一约束。
        # transfer 无 service 级幂等捕获，flush 直接抛 IntegrityError（非 BizError）。
        with pytest.raises(IntegrityError):
            await transfer(db, a, b, 40, "pay", "trx", "1")

    async def test_transfer_insufficient(self, db: AsyncSession):
        a = await _user(db, "a")
        b = await _user(db, "b")
        with pytest.raises(BizError) as e:
            await transfer(db, a, b, 40, "pay", "trx", "2")
        assert e.value.errcode == PointsErr.INSUFFICIENT_BALANCE


class TestConcurrency:
    async def test_concurrent_spend_no_overdraw(self, db: AsyncSession):
        """两个独立会话（各自事务）在该文件库上并发扣款 → 只有余额足够的那笔成功。

        目的：每个 spend 都跑在独立的 AsyncSession 上，让其在本进程的真实并发
        下竞争，而不是复用同一个 session 串行执行，从而覆盖 atomic 防透支守卫。

        注：db 夹具是 StaticPool（单连接内存 sqlite），两个独立会话共享同一连接
        会互相践踏事务，无法获得真并发。因此这里自建一个文件型 sqlite 引擎并配
        NullPool，使每个并发会话独占一条连接、指向同一数据库文件——这才是数据库
        级别并发。sqlite 的写锁仍会把真实写串行化，但 WHERE balance + delta >= 0
        原子守卫决定哪一笔成功，正是本测试要证明的行为。
        """
        import tempfile

        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        fd, dbfile = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            engine: AsyncEngine = create_async_engine(
                f"sqlite+aiosqlite:///{dbfile}",
                poolclass=NullPool,
            )
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            # 种子与本线程同库同表
            async with factory() as seed:
                uid = await _user(seed, "alice", "n")
                await reward(seed, uid, 100, "test", "cc", "0")
                await seed.commit()
            results = await asyncio.gather(
                _spend_in_session(factory, uid, 70, "cc", "1"),
                _spend_in_session(factory, uid, 70, "cc", "2"),
                return_exceptions=True,
            )
            succ = [x for x in results if not isinstance(x, Exception)]
            fail = [x for x in results if isinstance(x, Exception)]
            assert len(succ) == 1
            assert len(fail) == 1
            # 用一个新会话查余额 = 100 - 70 = 30（只有一个 70 成功）
            async with factory() as s:
                assert await get_balance(s, uid) == 30
            await engine.dispose()
        finally:
            await asyncio.to_thread(
                lambda: os.remove(dbfile) if os.path.exists(dbfile) else None
            )


class TestLeaderboard:
    async def test_leaderboard_orders(self, db: AsyncSession):
        a = await _user(db, "a", "甲")
        b = await _user(db, "b", "乙")
        await reward(db, a, 50, "test", "l", "1")
        await reward(db, b, 100, "test", "l", "2")
        items, total = await leaderboard(db)
        assert total == 2
        assert items[0].user_id == b  # 乙 100 最高
        assert items[0].display_name == "乙"
        assert items[1].user_id == a

    async def test_leaderboard_tiebreak_by_display_name(self, db: AsyncSession):
        """余额相等时按 display_name（昵称）字典序升序排。"""
        a = await _user(db, "aaa", "Zebra")
        b = await _user(db, "bbb", "Apple")
        await reward(db, a, 50, "test", "tb", "1")
        await reward(db, b, 50, "test", "tb", "2")
        items, _total = await leaderboard(db)
        assert (
            items[0].user_id == b and items[0].display_name == "Apple"
        )  # Apple < Zebra
        assert items[1].user_id == a and items[1].display_name == "Zebra"

    async def test_ledger_pagination(self, db: AsyncSession):
        uid = await _user(db)
        await reward(db, uid, 1, "test", "pg", "1")
        await reward(db, uid, 2, "test", "pg", "2")
        udata = await list_ledger(db, uid, page=1, limit=1)
        assert udata.total == 2
        assert len(udata.items) == 1
        assert udata.pages == 2


class TestRouter:
    async def test_me_requires_auth(self, client, db):
        resp = await client.get("/api/v1/points/me")
        assert resp.status_code == 403

    async def test_leaderboard_public(self, client, db):
        resp = await client.get("/api/v1/points/leaderboard")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        # 已统一为 PageData（含 items/total/page/pages）并带 X-Total 头
        assert "items" in data and "total" in data
        assert resp.headers.get("X-Total") == str(data["total"])
