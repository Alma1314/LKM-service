"""数据库初始化 —— Alembic 为 schema 唯一权威。

多 worker（模块5）安全：每个 uvicorn worker 的 lifespan 都会调 init_db()。首次
建库时并发 upgrade 会有竞态（重复建表/版本锁冲突），故用 Redis 分布式锁串行化；
Redis 不可用（未配置/宕机，fail-open）则不设锁直接跑（dev/sqlite 单 worker 本无并发）。
"""

import asyncio
from contextlib import suppress

_MIGRATION_LOCK_KEY = "lkm:migration:lock"
_MIGRATION_LOCK_TTL = 120  # 秒：迁移超时上限后锁自动过期
_MIGRATION_LOCK_WAIT = 8  # 秒：拿不到锁时最多等待的时长，之后照常跑（幂等 no-op）
_MIGRATION_LOCK_POLL = 0.3  # 轮询间隔


def _run_upgrade() -> None:
    """在独立线程里同步执行 Alembic upgrade head。

    env.py 的在线迁移内部用 ``asyncio.run`` 创建事件循环，而 init_db 在
    FastAPI lifespan（已运行的事件循环）中被调用，直接调用 command.upgrade
    会因 "cannot be called from a running event loop" 崩溃，故放到线程池。
    """
    from pathlib import Path

    from alembic.config import Config

    from alembic import command

    # 复用后端仓库根下的 alembic.ini（含 script_location 与 env.py），
    # 迁移沿用 env.py 的 sqlalchemy.url（来自 settings），不在此覆盖。
    repo_root = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(repo_root / "alembic.ini"))
    command.upgrade(cfg, "head")


async def _acquire_migration_lock() -> bool:
    """用 Redis SET NX 抢迁移锁；未配置/失败返回 False（fail-open 不设锁）。"""
    from app.core import redis as redis_client

    client = await redis_client.get_redis()
    if client is None:
        return False
    try:
        ok = bool(
            await client.set(_MIGRATION_LOCK_KEY, "1", nx=True, ex=_MIGRATION_LOCK_TTL)
        )
        if ok:
            return True
        # 拿不到 → 有别的 worker 在迁移：轮询等待其释放
        waited = 0.0
        while waited < _MIGRATION_LOCK_WAIT:
            await asyncio.sleep(_MIGRATION_LOCK_POLL)
            waited += _MIGRATION_LOCK_POLL
            # 对方已释放并成功重新抢占（lock 已过期）→ 自己来迁
            gone = bool(await client.get(_MIGRATION_LOCK_KEY)) is False
            if gone and bool(
                await client.set(
                    _MIGRATION_LOCK_KEY, "1", nx=True, ex=_MIGRATION_LOCK_TTL
                )
            ):
                return True
        return False  # 等待超时：照常跑（幂等 no-op）
    except Exception:
        return False  # Redis 异常 → fail-open


async def _release_migration_lock(held: bool) -> None:
    if not held:
        return
    from app.core import redis as redis_client

    client = await redis_client.get_redis()
    if client is None:
        return
    with suppress(Exception):
        await client.delete(_MIGRATION_LOCK_KEY)


async def init_db() -> None:
    """把数据库 schema 升到 Alembic head（多 worker 下用 Redis 锁串行化）。

    既负责全新环境的建库（基线迁移建全部表），也负责后续的增量迁移。
    生产与开发复用同一迁移链。
    """
    held = await _acquire_migration_lock()
    try:
        await asyncio.to_thread(_run_upgrade)
    finally:
        await _release_migration_lock(held)
