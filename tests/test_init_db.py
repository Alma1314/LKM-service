"""模块5：init_db 多 worker 迁移锁（Redis 串行化；不可用 fail-open）。"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

import app.core.redis as redis_mod
from app.core.config import settings
from app.db import init_db as init_db_mod


@pytest.fixture(autouse=True)
async def reset_redis_globals() -> AsyncIterator[None]:
    redis_mod._client = None
    redis_mod._client_pool = None
    yield
    await redis_mod.close_redis()
    redis_mod._client = None
    redis_mod._client_pool = None


@pytest.fixture(autouse=True)
async def _mock_seed(monkeypatch: Any) -> AsyncIterator[None]:
    """隔离 RBAC seed 的 DB 副作用：锁测试只验证迁移锁行为。

    init_db 现在会调 _seed_base_data（种默认权限），它内部 new_session() 连的是
    真实配置库，会污染开发库并拖慢锁测试；故这里 mock 为 no-op，seed 正确性由
    test_rbac_seed.py 与 test_invokes_rbac_seed（恢复真实实现）覆盖。
    """
    if not hasattr(init_db_mod, "_REAL_seed_base_data"):
        init_db_mod._REAL_seed_base_data = init_db_mod._seed_base_data

    async def _noop() -> None:
        return None

    monkeypatch.setattr(init_db_mod, "_seed_base_data", _noop)
    yield


async def _enable_fake_redis(monkeypatch: Any) -> Any:
    import fakeredis.aioredis

    fake = fakeredis.aioredis.FakeRedis()

    def _from_url(cls: Any, url: str, **kwargs: Any) -> Any:
        return fake

    monkeypatch.setattr(redis_mod.Redis, "from_url", classmethod(_from_url))
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    return fake


async def test_lock_acquired_when_redis_available(monkeypatch) -> None:
    """Redis 可用且无竞争者 → 抢到锁，init_db 正常跑迁移并释放。"""
    fake = await _enable_fake_redis(monkeypatch)
    monkeypatch.setattr(settings, "use_alembic", True)
    ran = 0

    def _fake_ide() -> None:
        nonlocal ran
        ran += 1

    monkeypatch.setattr(init_db_mod, "_run_upgrade", _fake_ide)
    await init_db_mod.init_db()
    assert ran == 1
    # 迁移结束锁已释放（键不存在或已被删）
    held = await fake.get(init_db_mod._MIGRATION_LOCK_KEY)
    assert held is None


async def test_lock_serializes_waiting_worker(monkeypatch) -> None:
    """已有 worker 持锁 → 当前 worker 等待；锁释放后重新抢占再迁移。"""
    fake = await _enable_fake_redis(monkeypatch)
    monkeypatch.setattr(settings, "use_alembic", True)
    # 预置一把锁，模拟另一个 worker 正在迁移
    await fake.set(init_db_mod._MIGRATION_LOCK_KEY, "1", nx=True)
    ran = 0

    def _fake_ide() -> None:
        nonlocal ran
        ran += 1

    monkeypatch.setattr(init_db_mod, "_run_upgrade", _fake_ide)
    # 持锁方中途释放，使等待者能抢占
    original_sleep = init_db_mod.asyncio.sleep

    async def _release_after_sleep(_d: float) -> None:
        await original_sleep(0)
        await fake.delete(init_db_mod._MIGRATION_LOCK_KEY)

    monkeypatch.setattr(init_db_mod.asyncio, "sleep", _release_after_sleep)
    await init_db_mod.init_db()
    assert ran == 1


async def test_invokes_rbac_seed(monkeypatch) -> None:
    """schema 就绪后 init_db 恒调用 RBAC seed（种子权限映射，取代人工 CLI）。"""
    # 恢复 autouse _mock_seed 替换掉的真实实现，验证 seed 真实落库
    monkeypatch.setattr(
        init_db_mod, "_seed_base_data", init_db_mod._REAL_seed_base_data
    )
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.pool import StaticPool

    import app.db.session as db_session
    from app.db.models import Base, RolePermission
    from app.modules.rbac.permissions import DEFAULT_GRANTS

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session: AsyncSession = SessionLocal()

    async def _fake_new_session() -> AsyncSession:
        # _seed_base_data 函数内 `from app.db.session import new_session` 在调用点解析，
        # 替换 app.db.session.new_session 即可生效。
        return session

    monkeypatch.setattr(db_session, "new_session", _fake_new_session)

    async def _noop_create_all() -> None:
        return None

    monkeypatch.setattr(init_db_mod, "_create_all", _noop_create_all)
    # use_alembic 默认 False → 走 create_all 分支 + seed
    await init_db_mod.init_db()

    total = (
        await session.execute(select(func.count()).select_from(RolePermission))
    ).scalar_one()
    expected = sum(len(v) for v in DEFAULT_GRANTS.values())
    assert total == expected
    await session.close()
    await engine.dispose()


async def test_fail_open_when_redis_disabled(monkeypatch) -> None:
    """Redis 未配置 → 不设锁直接跑（dev/sqlite 单 worker 场景）。"""
    monkeypatch.setattr(settings, "redis_url", "")
    monkeypatch.setattr(settings, "use_alembic", True)
    ran = 0

    def _fake_ide() -> None:
        nonlocal ran
        ran += 1

    monkeypatch.setattr(init_db_mod, "_run_upgrade", _fake_ide)
    await init_db_mod.init_db()
    assert ran == 1
