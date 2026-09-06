from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.err import (
    AuthErr,  # M3 peer: 并入共享 shared err
    BizError,
)

# —— 主库（monolith，realm="default"）的惰性单例。M3.B 物理拆目标：monolith 主进程
# 只触达 database_url（auth 独立库走单独的 app/db/auth_session.py，主进程不侧挂）。
_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def _set_sqlite_pragma_on_connect(engine: AsyncEngine) -> None:
    """为 sqlite 引擎开启每连接外键 pragma（外键必须按连接启用）。"""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()


def create_realm_async_engine(
    url: str,
    *,
    driver: str,
    pool_size: int | None = None,
    pool_max_overflow: int | None = None,
    pool_pre_ping: bool | None = None,
) -> AsyncEngine:
    """按驱动/池参数建立 async 引擎，并配 sqlite 的外键 pragma 钩子。

    供主库（:func:`get_async_engine`）与 auth 独立库（app/db/auth_session.py）共用的唯一
    建池逻辑，避免两处策略漂移：
    - PostgreSQL/asyncpg 走显式连接池 + pre_ping；
    - SQLite 走 NullPool（单文件多连接无益）并逐连接开启外键 pragma。
    """
    connect_args: dict[str, object] = {}
    engine_kwargs: dict[str, object] = {"echo": False, "connect_args": connect_args}
    if driver == "postgresql":
        if (
            pool_size is not None
            or pool_max_overflow is not None
            or pool_pre_ping is not None
        ):
            if pool_size is not None:
                engine_kwargs["pool_size"] = pool_size
            if pool_max_overflow is not None:
                engine_kwargs["max_overflow"] = pool_max_overflow
            if pool_pre_ping is not None:
                engine_kwargs["pool_pre_ping"] = pool_pre_ping
        return create_async_engine(url, **engine_kwargs)

    from sqlalchemy.pool import NullPool

    engine_kwargs["poolclass"] = NullPool
    connect_args["check_same_thread"] = False
    engine = create_async_engine(url, **engine_kwargs)
    _set_sqlite_pragma_on_connect(engine)
    return engine


def get_async_engine() -> AsyncEngine | None:
    global _async_engine
    if _async_engine is None:
        _async_engine = create_realm_async_engine(
            settings.database_url,
            driver=settings.db_driver,
            pool_size=settings.db_pool_size,
            pool_max_overflow=settings.db_pool_max_overflow,
            pool_pre_ping=settings.db_pool_pre_ping,
        )
    return _async_engine


def _get_async_session_local() -> async_sessionmaker[AsyncSession] | None:
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_async_engine(),
            expire_on_commit=False,
        )
    return _AsyncSessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：提供异步会话，负责 commit / rollback / close。"""
    factory = _get_async_session_local()
    assert factory is not None
    db = factory()
    try:
        yield db
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _is_unique_violation(exc):
            raise BizError(
                AuthErr.ALREADY_REGISTERED, "Resource already exists"
            ) from None
        raise
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def get_read_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：只读会话，供公开只读接口使用，避免每读请求一次空 BEGIN/COMMIT。

    不做 commit（读路径本无写入）；正常退出也显式 rollback 丢弃解析器误写/残留的
    未提交改动（防御某解析器意外 flush），异常同样回滚，最后 close。
    """
    factory = _get_async_session_local()
    assert factory is not None
    db = factory()
    try:
        yield db
        # 正常路径：只读，无提交意图；显式回滚以防解析器意外写入被残留到下一次
        await db.rollback()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def new_session() -> AsyncSession:
    """创建独立异步会话，与主会话共享同一引擎（连接池）但独立事务。"""
    factory = _get_async_session_local()
    assert factory is not None
    return factory()


async def dispose_engine() -> None:
    global _async_engine, _AsyncSessionLocal
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _AsyncSessionLocal = None


def _is_unique_violation(exc: IntegrityError) -> bool:
    """判断 IntegrityError 是否由唯一约束冲突引起（区别于外键/NOT NULL 等）。"""
    orig = exc.orig
    if orig is None:
        return False
    name = type(orig).__name__
    if "UniqueViolation" in name:
        return True
    return "UNIQUE constraint failed" in str(orig)
