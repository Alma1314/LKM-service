"""全局 pytest fixtures 与配置。

- db：内存 sqlite 会话（每测试隔离），供直连 service / 生成测试数据。
- client：官方推荐的 httpx.AsyncClient + ASGITransport 异步客户端。
    ASGITransport 默认不触发 app.lifespan，因此不会对真实 lkm.db 执行
    init_db()，彻底避免测试污染运行环境；会话通过依赖覆盖注入内存库。
"""
import os

# 确保测试始终以 test 标志运行，允许弱 JWT 密钥
os.environ["PYTEST_RUNNING"] = "1"

import asyncio  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.models import Base  # noqa: E402
from app.db.session import get_session  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def db():
    """提供隔离的内存 sqlite 会话（StaticPool 保证同一连接池，跨线程可用）。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal: sessionmaker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
async def client(db):
    """官方异步 HTTP 客户端：httpx.AsyncClient + ASGITransport。

    不触发 lifespan（避免 init_db 触碰真实 lkm.db），并把 get_session 依赖
    覆盖为内存会话，最后只撤销本测试注入的覆盖键。
    """

    async def override_get_session():
        yield db

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)
