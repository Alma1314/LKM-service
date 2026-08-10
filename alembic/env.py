"""Alembic environment configuration for online/offline migrations.

Provides both ``run_migrations_offline`` (generate SQL) and
``run_migrations_online`` (direct DB execution).  Imports all app
models so ``autogenerate`` can detect schema changes.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings

# Alembic Config object
config = context.config

# Configure logging from the ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set the database URL
config.set_main_option("sqlalchemy.url", settings.database_url)

# Import all models so metadata is fully populated for autogenerate
from app.db.models import Base  # noqa: E402
import app.modules.auth.models  # pyright: ignore[reportUnusedImport]
import app.modules.columns.models  # pyright: ignore[reportUnusedImport]

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


def run_migrations_online() -> None:
    """Run migrations in 'online' (live-database) mode.

    Creates an Engine and associates a connection with the context.
    For SQLite the render_as_batch flag is enabled so ALTER statements work.
    """
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
