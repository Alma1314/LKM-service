"""全局 pytest fixtures 与配置。

- db：内存 aiosqlite 异步会话（每测试隔离），供直连 service / 生成测试数据。
- client：官方推荐的 httpx.AsyncClient + ASGITransport 异步客户端。
    ASGITransport 默认不触发 app.lifespan，因此不会对真实 lkm.db 执行
    init_db()，彻底避免测试污染运行环境；会话通过依赖覆盖注入内存库。
"""

import os
from collections.abc import AsyncGenerator
from typing import Annotated

# 确保测试始终以 test 标志运行，允许弱 JWT 密钥
os.environ["PYTEST_RUNNING"] = "1"

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_read_session, get_session
from app.main import app

# 复用类型的别名，供各测试文件 import 使用
DB = Annotated[AsyncSession, pytest.fixture]
Client = Annotated[AsyncClient, pytest.fixture]


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession]:
    """提供隔离的内存 aiosqlite 异步会话（StaticPool 保证同一连接池）。"""
    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session: AsyncSession = SessionLocal()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


@pytest.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient]:
    """官方异步 HTTP 客户端：httpx.AsyncClient + ASGITransport。

    不触发 lifespan（避免 init_db 触碰真实 lkm.db），并把 get_session 依赖
    覆盖为内存会话，最后只撤销本测试注入的覆盖键。
    """

    async def override_get_session() -> AsyncGenerator[AsyncSession]:
        yield db

    # 读写两种依赖都指向同一内存库，避免测试里只覆盖了写会话而读会话漏网
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_read_session] = override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_read_session, None)
