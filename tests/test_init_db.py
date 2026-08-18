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


async def test_fail_open_when_redis_disabled(monkeypatch) -> None:
    """Redis 未配置 → 不设锁直接跑（dev/sqlite 单 worker 场景）。"""
    monkeypatch.setattr(settings, "redis_url", "")
    ran = 0

    def _fake_ide() -> None:
        nonlocal ran
        ran += 1

    monkeypatch.setattr(init_db_mod, "_run_upgrade", _fake_ide)
    await init_db_mod.init_db()
    assert ran == 1
