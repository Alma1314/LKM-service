"""Alembic environment configuration for online/offline migrations."""

import sys
from logging.config import fileConfig
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import settings

# Alembic Config object
config = context.config

# Configure logging from the ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set the database URL
config.set_main_option("sqlalchemy.url", settings.database_url)

# Import all models so metadata is fully populated for autogenerate
from app.db.base import Base
from app.db.model_registry import ensure_all_models

ensure_all_models()

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


def _sync_url(url: str) -> str:
    """Alembic runs in a sync context——把数据库驱动换成同步方言。

    settings.database_url 是 async 方言（sqlite+aiosqlite / postgresql+asyncpg），
    alembic 不能直接用。SQLite 回落标准库 sqlite3；Postgres 回落 psycopg2（装同步驱动）。
    """
    if url.startswith("sqlite+aiosqlite"):
        return "sqlite" + url[len("sqlite+aiosqlite") :]
    if url.startswith("postgresql+asyncpg"):
        return "postgresql+psycopg2" + url[len("postgresql+asyncpg") :]
    return url


def run_migrations_online() -> None:
    """Run migrations in 'online' (live-database) mode.

    Creates an Engine and associates a connection with the context.
    For SQLite the render_as_batch flag is enabled so ALTER statements work.
    """
    config.set_main_option("sqlalchemy.url", _sync_url(settings.database_url))
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite-compatible
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
