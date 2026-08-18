"""db/session.py 的 IntegrityError 映射单测：唯一约束 vs 外键/NOT NULL。"""

import sqlite3
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from app.db.session import _is_unique_violation, get_async_engine


def _ie(orig: Exception | None) -> IntegrityError:
    # IntegrityError.orig 的 pyi 标非 None，但 SQLAlchemy 运行时允许 orig=None
    return IntegrityError("stmt", {}, orig)  # ty: ignore[invalid-argument-type]


class TestIsUniqueViolation:
    def should_detect_sqlite_unique_constraint(self):
        orig = sqlite3.IntegrityError("UNIQUE constraint failed: users.email")
        assert _is_unique_violation(_ie(orig)) is True

    def should_not_detect_sqlite_foreign_key(self):
        orig = sqlite3.IntegrityError("FOREIGN KEY constraint failed")
        assert _is_unique_violation(_ie(orig)) is False

    def should_not_detect_sqlite_not_null(self):
        orig = sqlite3.IntegrityError("NOT NULL constraint failed: users.username")
        assert _is_unique_violation(_ie(orig)) is False

    def should_detect_unique_violation_by_class_name(self):
        class UniqueViolationError(Exception):
            pass

        assert _is_unique_violation(_ie(UniqueViolationError("dup"))) is True

    def should_return_false_when_no_orig(self):
        assert _is_unique_violation(_ie(None)) is False


class TestEnginePoolConfig:
    """模块2：连接池配置（PostgreSQL 显式池 + pre_ping；SQLite NullPool）。"""

    async def should_configure_pool_for_sqlite(self, monkeypatch):
        """SQLite 驱动 → 引擎用 NullPool（避免池竞争）。"""
        import app.db.session as session_mod
        from app.core.config import settings

        monkeypatch.setattr(settings, "db_driver", "sqlite")
        real_create = session_mod.create_async_engine
        captured: dict[str, Any] = {}
        engine: Any = None

        def _spy_create(url: str, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return real_create(url, **kwargs)

        monkeypatch.setattr(session_mod, "create_async_engine", _spy_create)
        monkeypatch.setattr(session_mod, "_async_engine", None)
        monkeypatch.setattr(session_mod, "_AsyncSessionLocal", None)

        engine = get_async_engine()
        try:
            assert captured.get("poolclass") is NullPool
        finally:
            assert engine is not None
            await engine.dispose()

    def should_configure_pool_for_postgres(self, monkeypatch):
        """PostgreSQL 驱动 → 引擎带 pool_size/max_overflow/pool_pre_ping。"""
        import app.db.session as session_mod
        from app.core.config import settings

        monkeypatch.setattr(settings, "db_driver", "postgresql")
        captured: dict[str, Any] = {}

        def _fake_create(url: str, **kwargs: Any) -> Any:
            captured.update(kwargs)

            class _Shell:
                sync_engine: Any = None

            return _Shell()

        monkeypatch.setattr(session_mod, "create_async_engine", _fake_create)
        monkeypatch.setattr(session_mod, "_async_engine", None)
        monkeypatch.setattr(session_mod, "_AsyncSessionLocal", None)

        get_async_engine()
        assert captured.get("pool_size") == settings.db_pool_size
        assert captured.get("max_overflow") == settings.db_pool_max_overflow
        assert captured.get("pool_pre_ping") is True


class TestReadSession:
    """模块2：读会话 exit 后不自动 commit（只读请求省空事务）。"""

    async def should_not_commit_on_exit(self, monkeypatch) -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.pool import StaticPool

        import app.db.session as session_mod

        engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)

        calls: list[str] = []

        class _TrackingSession(AsyncSession):
            async def commit(self) -> None:
                calls.append("commit")
                await super().commit()

        factory = session_mod.async_sessionmaker(
            bind=engine,
            expire_on_commit=False,
            class_=_TrackingSession,
        )
        monkeypatch.setattr(session_mod, "_AsyncSessionLocal", factory)

        async for _db in session_mod.get_read_session():
            pass  # 仅走完整生命周期：进入 + 退出

        assert calls == [], "读会话退出不应触发 commit"
