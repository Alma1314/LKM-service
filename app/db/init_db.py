"""数据库初始化 —— Alembic 为 schema 唯一权威。

多 worker安全：每个 uvicorn worker 的 lifespan 都会调 init_db()。
首次建库时并发 upgrade 会有竞态（重复建表/版本锁冲突），故用 Redis 分布式锁串行化；
Redis 不可用（未配置/宕机，fail-open）则不设锁直接跑（dev 单 worker 本无并发）。
"""

import asyncio
from contextlib import suppress

_MIGRATION_LOCK_KEY = "lkm:migration:lock"
_MIGRATION_LOCK_TTL = 120  # 秒：迁移超时上限后锁自动过期
_MIGRATION_LOCK_WAIT = 8  # 秒：拿不到锁时最多等待的时长
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


async def _create_all() -> None:
    """create_all 降级通道：按 Base.metadata 建缺失的表（幂等，只建不 ALTER）。

    仅在 ``settings.use_alembic=False`` 时启用。多 worker 安全：create_all 对已存在的
    表是 no-op，无需 Redis 迁移锁。注意必须 import 所有模型模块，metadata 才会被填满；
    模型归位后由 ``model_registry.ensure_all_models`` 统一预注册各模块 models.py。
    """
    from app.db.base import Base
    from app.db.model_registry import ensure_all_models
    from app.db.session import get_async_engine

    ensure_all_models()
    engine = get_async_engine()
    if engine is None:
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _seed_base_data() -> None:
    """幂等写入 RBAC 默认角色→权限映射（role_permissions）。

    独立会话执行并提交；seed 用 ``ON CONFLICT DO NOTHING`` 保证并发/重复执行安全
    （见 app/modules/rbac/seed.py）。依赖 role_permissions 表已由前置 schema 初始化建出。
    """
    from app.db.session import new_session
    from app.modules.rbac.seed import seed_rbac

    db = await new_session()
    try:
        n = await seed_rbac(db)
        await db.commit()
    finally:
        await db.close()
    # n>0 仅首启/新增权限时发生；日志级即可，避免每个 worker 启动都打印噪音
    if n:
        import logging

        logging.getLogger("lkm.init_db").info("seed_rbac inserted %d rows", n)


async def init_db() -> None:
    """把数据库 schema 初始化到最新（多 worker 下用 Redis 锁串行化）。

    默认（``settings.use_alembic=False``）走 ``create_all()``：按 models metadata 建缺失表，
    开发免维护增量迁移——新增表只改 ``models.py`` 即可自动建。仅当显式设
    ``settings.use_alembic=True``（生产/历史库）才走 Alembic 增量迁移链
    （见 :func:`_create_all` 与 Alembic 各自的局限与取舍）。

    schema 就绪后恒调用 :func:`_seed_base_data` 种入 RBAC 默认权限映射，消除新部署
    需人工跑 ``python -m app.modules.rbac.seed`` 才能用后台/写端点的依赖。
    """
    from app.core.config import settings

    if not settings.use_alembic:
        await _create_all()
        await _seed_base_data()
        return
    held = await _acquire_migration_lock()
    try:
        await asyncio.to_thread(_run_upgrade)
        await _seed_base_data()
    finally:
        await _release_migration_lock(held)
