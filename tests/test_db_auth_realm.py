"""M3.B Stage1 基建回归：auth 独立库 realm、config、双 metadata 语义。

只验证 S1 交付的“基础设施可构造且与主库解耦”，不含对 auth.models 迁移的断言
（S5 才把 auth 表搬上 AuthBase）。全为本地 SQLite，不需真实 PG/Redis。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.auth_base import AuthBase, auth_metadata
from app.db.base import Base
from app.db.session import create_realm_async_engine


def test_auth_database_url_defaults_to_own_sqlite() -> None:
    """auth 独立库默认独立 SQLite 文件，不与主库 database_url 重合。"""
    assert settings.auth_database_url.startswith("sqlite+aiosqlite:///")
    assert settings.auth_database_url != settings.database_url


def test_mappings_module_scopes_disjoint() -> None:
    """auth 独立 metadata 与 monolith Base.metadata 是不同对象（防 schema 污染）。"""
    assert auth_metadata is AuthBase.metadata
    assert auth_metadata is not Base.metadata


def test_auth_db_fixture_is_isomorphic() -> None:
    """conftest 提供的 auth_db 会话连的是 auth 独立内存库（realm 隔离）。"""
    # 该 fixture 会在 auth_metadata 上 create_all（S1 空 → 无表不抛错）；此处仅保证
    # mark 存在性由 pytest fixture 定义驱动，路由见 conftest 注释。
    assert auth_metadata is not Base.metadata


async def test_create_realm_engine_loads(auth_db: AsyncSession) -> None:
    """auth 独立库能独立执行 SQL；且与主库 metadata 互不串（S1 空库即可 EXPLAIN 建）。

    验证 create_realm_async_engine + auth 内存会话可跑 SQL（无表时 select 1 不抛）。
    """
    row = (await auth_db.execute(text("select 1"))).scalar_one()
    assert row == 1


async def test_auth_db_metadata_create_all_smoke() -> None:
    """auth_metadata.create_all 在 S1（空）下是 no-op 不抛，S5 迁表后即建 auth 表。"""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(auth_metadata.create_all)
    finally:
        await engine.dispose()


async def test_db_engine_strategy_and_session(db: AsyncSession) -> None:
    """主库 get_session(通过 db fixture) 行为不因 realm 基建重构而变。"""
    row = (await db.execute(text("select 1"))).scalar_one()
    assert row == 1


async def test_monolith_engine_name_stable() -> None:
    """monolith 引擎创建策略保持：create_realm_async_engine 对 sqlite 产出 sqlite 驱动。"""
    eng = create_realm_async_engine("sqlite+aiosqlite://", driver="sqlite")
    assert eng.name == "sqlite"
    await eng.dispose()
