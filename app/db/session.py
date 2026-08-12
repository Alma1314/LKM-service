from collections.abc import AsyncIterator, Generator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.err import BizError
from app.modules.auth.errors import AuthErr

_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None

# 兼容层：仍可由测试/旧代码用 create_engine 构造同步引擎
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _db_url() -> str:
    """返回 database_url，并把同步驱动改写为异步驱动（aiosqlite / asyncpg 等）。"""
    url = settings.database_url
    url = url.replace("postgresql+psycopg2", "postgresql+asyncpg")
    url = url.replace("sqlite:///", "sqlite+aiosqlite:///")
    return url


def get_async_engine() -> AsyncEngine | None:
    global _async_engine
    if _async_engine is None:
        connect_args: dict[str, object] = {}
        if settings.db_driver == "sqlite":
            connect_args["check_same_thread"] = False
        _async_engine = create_async_engine(
            _db_url(),
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
    global _async_engine, _AsyncSessionLocal, _engine, _SessionLocal
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _AsyncSessionLocal = None
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _SessionLocal = None


# ── 兼容层：暴露同步 get_engine / get_session，供纯同步路径（如 Alembic env）复用 ──


def get_engine() -> Engine | None:
    global _engine
    if _engine is None:
        connect_args: dict[str, object] = {}
        if settings.db_driver == "sqlite":
            connect_args["check_same_thread"] = False
        _engine = create_engine(
            settings.database_url,
            echo=False,
            connect_args=connect_args,
        )
        if settings.db_driver == "sqlite":

            @event.listens_for(_engine, "connect")
            def _set_sync_sqlite_pragma(
                dbapi_connection: Any, connection_record: Any
            ) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.close()

    return _engine


def _get_session_local() -> sessionmaker[Session] | None:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


def get_session_sync() -> Generator[Session]:
    """同步依赖（若未来仍有同步端点使用）。"""
    factory = _get_session_local()
    assert factory is not None
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
