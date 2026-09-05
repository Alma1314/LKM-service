"""全局 pytest fixtures 与配置。

提供隔离数据库异步会话，两条后端：
- driver=sqlite（默认）：每测试独立内存 aiosqlite 库（StaticPool 单连接、零外部依赖）。
- driver=postgresql（monolith 迁 asyncpg / 真拆库专项）：**schema-per-test**——为每个
  测试独占一个 PostgreSQL schema，并把该测试唯一引擎所有连接的 search_path 指到它，
  ``create_all`` 落在该 schema，测末 drop cascade。每测试“单长活会话 override”保住了
  “POST 后再 GET/直查同见未提交数据”的既有语义（同一连接同一事务），跨测试靠 schema
  隔离，无残留。

  引用的配方推理见 conftest 评审（Explore）：
  - SQLAlchemy Async 不具备 join-external-transaction → 唯一可靠 PG 等价是 schema-per-test。
  - search_path 经连接级 URL options ``-csearch_path=<schema>`` 强制，比逐会话 SET 可靠
    （连接池回取的每根连接都带同一 schema）。
  - 建 schema 必须先于指向它的连接（否则 search_path 连不存在的 schema 会失败）。

- client：httpx.AsyncClient + ASGITransport。ASGITransport 默认不触发 app.lifespan，
  避免对真实控制面 init_db() 的副作用；``get_session``/``get_read_session`` 依赖覆盖到
  ``db`` 会话。
- auth_db：auth 独立库第二 metadata/schema（AuthBase 空骨架；真拆库后 auth 表迁入）。
"""

import os
from collections.abc import AsyncGenerator
from typing import Annotated, Any

# 确保测试始终以 test 标志运行，允许弱 JWT 密钥
os.environ["PYTEST_RUNNING"] = "1"

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from app.core.config import settings
from app.db.auth_base import auth_metadata
from app.db.base import Base
from app.db.session import get_read_session, get_session
from app.main import app

# 复用类型的别名，供各测试文件 import 使用
DB = Annotated[AsyncSession, pytest.fixture]
Client = Annotated[AsyncClient, pytest.fixture]

# —— 测试库引擎选择。单一来源 = app.core.config.settings（其值来自 .env/环境，
# 默认 sqlite）；P-mig/真拆库专项把对应 driver 设成 postgresql 即走真实 PG。
_PG_BIZ = settings.db_driver == "postgresql"
_PG_AUTH = settings.auth_db_driver == "postgresql"


# ───────────────────────────────────────────────────────────────────────
# schema-per-test 工具（PG 分支用）：建/命名/drop 一个测试专属 schema
# ───────────────────────────────────────────────────────────────────────
_schema_counter = iter(range(10**9))


async def _pg_schema_engine(
    url: str, schema: str, *, metadata: Any
) -> AsyncEngine:
    """建立指向测试专属 PG schema 的 StaticPool 单连接引擎，并已建好 DDL。

    asyncpg 不接受 URL query ``options``；改用 StaticPool 保持单物理连接，在引擎那唯一
    连接的会话上 ``SET search_path``（对连接级永久生效，无需逐回连重设），随后的
    ``create_all`` 与所有测试会话都落在这个 schema——实现与 sqlite 单连接一致
    （整测试共享同一连接、同见未 commit 数据），跨测试靠 schema 隔离。
    """
    eng: AsyncEngine = create_async_engine(url, poolclass=StaticPool)
    async with eng.begin() as conn:
        # DROP IF EXISTS + CREATE：保证残留/重复 run 也干净（schema 名 t<n> 独立不冲突）。
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "t{schema}" CASCADE'))
        await conn.execute(text(f'CREATE SCHEMA "t{schema}"'))
        await conn.execute(text(f'SET search_path TO "t{schema}"'))
        await conn.run_sync(metadata.create_all)
    return eng


async def _drop_schema(url: str, schema: str) -> None:
    """用完清理测试 schema（隔离到别的测试不泄漏）。"""
    eng = create_async_engine(url, poolclass=NullPool)
    try:
        async with eng.connect() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "t{schema}" CASCADE'))
            await conn.commit()
    finally:
        await eng.dispose()


# ───────────────────────────────────────────────────────────────────────
# db / auth_db / client
# ───────────────────────────────────────────────────────────────────────
@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession]:
    """隔离数据库异步会话。

    sqlite：独立内存库（每测试 create_all + dispose，StaticPool 单连接）。
    postgresql：独立测试 schema + 引擎（search_path 已指该 schema，create_all 在其上）。
    各分支都给 override client 一个长活会话，保证“POST 后再测内 GET/直查同见”。
    """
    if _PG_BIZ:
        schema = str(next(_schema_counter))
        url = settings.database_url
        engine: AsyncEngine = await _pg_schema_engine(
            url, schema, metadata=Base.metadata
        )
        session_factory = async_sessionmaker(
            autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
        )
        session: AsyncSession = session_factory()
        try:
            yield session
        finally:
            await session.close()
            await engine.dispose()
            await _drop_schema(url, schema)
    else:
        engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(
            autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
        )
        session = session_factory()
        try:
            yield session
        finally:
            await session.close()
            await engine.dispose()


@pytest.fixture
async def auth_db() -> AsyncGenerator[AsyncSession]:
    """auth 独立库第二 metadata/schema。

    sqlite：`auth_metadata` 内存库（S1–S4 auth.models 挂 monolith，此处为空骨架）。
    postgresql：auth 真实 PG（auth_database_url）上独立测试 schema，auth_metadata
    （AuthBase）create_all 落于此——真拆库后 auth 表建这里。
    """
    if _PG_AUTH:
        schema = str(next(_schema_counter))
        url = settings.auth_database_url
        engine: AsyncEngine = await _pg_schema_engine(
            url, schema, metadata=auth_metadata
        )
        session_factory = async_sessionmaker(
            autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
        )
        session: AsyncSession = session_factory()
        try:
            yield session
        finally:
            await session.close()
            await engine.dispose()
            await _drop_schema(url, schema)
    else:
        engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with engine.begin() as conn:
            await conn.run_sync(auth_metadata.create_all)
        session_factory = async_sessionmaker(
            autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
        )
        session = session_factory()
        try:
            yield session
        finally:
            await session.close()
            await engine.dispose()


@pytest.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient]:
    """官方异步 HTTP 客户端：httpx.AsyncClient + ASGITransport。

    不触发 lifespan（避免 init_db 触碰真实控制面/lkm.db），并把 get_session/get_read_session
    覆盖到 ``db`` 会话（使同一测试内 HTTP 请求与测试体的 service 直呼共享同一长活事务，
    得以 flush 未 commit 即 POST→GET 同见）。只撤销本测试注入的覆盖键。
    """

    async def override_get_session() -> AsyncGenerator[AsyncSession]:
        yield db

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_read_session] = override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_read_session, None)
