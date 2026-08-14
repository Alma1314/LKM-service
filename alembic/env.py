"""Alembic environment configuration for online/offline migrations.

Provides both ``run_migrations_offline`` (generate SQL) and
``run_migrations_online`` (direct DB execution).  Imports all app
models so ``autogenerate`` can detect schema changes.
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings

# Alembic Config object
config = context.config

# Configure logging from the ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set the database URL（已为 async 方言：postgresql+asyncpg / sqlite+aiosqlite）
config.set_main_option("sqlalchemy.url", settings.database_url)

# Import all models so metadata is fully populated for autogenerate
from app.db.models import Base  # noqa: E402
import app.modules.auth.models  # noqa: E402, F401
import app.modules.columns.models  # noqa: E402, F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' (SQL-script) mode.

    Configures the context with just a URL, not an Engine.
    Calls to ``context.execute()`` emit the given SQL to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite-compatible
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations against a live connection.

    ``connection.run_sync`` 传入的是同步 Connection；``render_as_batch``
    对 SQLite 的 ALTER 语句必要。
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite-compatible
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """用 async 引擎跑迁移（database_url 已是 async 方言）。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' (live-database) mode via an async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
