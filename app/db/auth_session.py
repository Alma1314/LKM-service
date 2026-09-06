"""AUTH 独立库会话/引擎工厂（M3.B S1 基建，惰性、monolith 侧不实例化）。

物理拆后 auth 自持库由 auth 进程自己持有专属 engine/sessionmaker。本模块提供该 realm
的惰性单例工厂，装配规则（贯穿 M3.B 设计原则 2「进程=库边界」）：
- **monolith 主进程永不实例化/使用本模块**——主进程只有 ``settings.database_url``，
  不凑 ``settings.auth_database_url``；对 auth 真值的一切读都经 HTTP seam（S3+）。
- **auth 进程（main_auth）与迁移/tool 在需要自连 auth 库时才** lazy 建引擎。
- 建池策略复用于 app/db/session.py 的 :func:`create_realm_async_engine`，避免两库漂移。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.core.config import settings
from app.db.session import create_realm_async_engine

_auth_async_engine: AsyncEngine | None = None
_auth_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_auth_engine() -> AsyncEngine:
    """惰性建立 auth 专属 async 引擎（池参数取 config 的 auth_db_*）。"""
    global _auth_async_engine
    if _auth_async_engine is None:
        _auth_async_engine = create_realm_async_engine(
            settings.auth_database_url,
            pool_size=settings.auth_db_pool_size,
            pool_max_overflow=settings.auth_db_pool_max_overflow,
            pool_pre_ping=settings.auth_db_pool_pre_ping,
        )
    return _auth_async_engine


def _get_auth_session_local() -> async_sessionmaker[AsyncSession]:
    global _auth_AsyncSessionLocal
    if _auth_AsyncSessionLocal is None:
        _auth_AsyncSessionLocal = async_sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_auth_engine(),
            expire_on_commit=False,
        )
    return _auth_AsyncSessionLocal


async def get_auth_session() -> AsyncSession:
    """创建 auth 独立库会话（供 auth 进程/迁移工具内部使用）。

    S1–S4 无调用方（monolith 不用它）；S5 迁表后 auth 进程的读写经此。调用方负责
    commit/rollback/close（本模块不持有请求级生命周期）。
    """
    return _get_auth_session_local()()


async def dispose_auth_engine() -> None:
    """收尾释放 auth 引擎（auth 进程 lifespan 退出清理）。幂等。"""
    global _auth_async_engine, _auth_AsyncSessionLocal
    if _auth_async_engine is not None:
        await _auth_async_engine.dispose()
        _auth_async_engine = None
        _auth_AsyncSessionLocal = None
