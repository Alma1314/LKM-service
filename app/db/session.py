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
from app.core.err import BizError
from app.modules.auth.errors import AuthErr

_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_async_engine() -> AsyncEngine | None:
    global _async_engine
    if _async_engine is None:
        connect_args: dict[str, object] = {}
        if settings.db_driver == "sqlite":
            connect_args["check_same_thread"] = False
        _async_engine = create_async_engine(
            settings.database_url,
            echo=False,
            connect_args=connect_args,
        )
        # 启用 SQLite 外键支持（必须按连接设置，作用于底层 sync 连接）
        if settings.db_driver == "sqlite":

            @event.listens_for(_async_engine.sync_engine, "connect")
            def _set_sqlite_pragma(
                dbapi_connection: Any, connection_record: Any
            ) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.close()

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
    except IntegrityError:
        await db.rollback()
        raise BizError(AuthErr.ALREADY_REGISTERED, "Resource already exists") from None
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
