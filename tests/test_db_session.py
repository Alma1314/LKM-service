"""db/session.py 的 IntegrityError 映射单测：唯一约束 vs 其他，及引擎池策略。"""

from typing import Any

from sqlalchemy.exc import IntegrityError

from app.db.session import _is_unique_violation, get_async_engine


def _ie(orig: Exception | None) -> IntegrityError:
    # IntegrityError.orig 的 pyi 标非 None，但 SQLAlchemy 运行时允许 orig=None
    return IntegrityError("stmt", {}, orig)  # ty: ignore[invalid-argument-type]


class TestIsUniqueViolation:
    """纯 PostgreSQL 语义：只靠 asyncpg 错误类名（UniqueViolation）判定。"""

    def should_detect_unique_violation_by_class_name(self):
        class UniqueViolation(Exception):
            pass

        assert _is_unique_violation(_ie(UniqueViolation("dup"))) is True

    def should_not_detect_other_violation_by_class_name(self):
        # 真 PG 下的外键违例类名是 ForeignKeyViolation（非 UniqueViolation）
        class ForeignKeyViolation(Exception):
            pass

        class NotNullViolation(Exception):
            pass

        assert _is_unique_violation(_ie(ForeignKeyViolation("fk"))) is False
        assert _is_unique_violation(_ie(NotNullViolation("nn"))) is False

    def should_return_false_when_no_orig(self):
        assert _is_unique_violation(_ie(None)) is False


class TestEnginePoolConfig:
    """PostgreSQL(asyncpg) 建池：显式 pool_size/max_overflow/pool_pre_ping。"""

    def should_configure_pool_for_postgres(self, monkeypatch):
        import app.db.session as session_mod
        from app.core.config import settings

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
    """读会话 exit 后不自动 commit（只读请求省空事务）。"""

    async def should_not_commit_on_exit(self, monkeypatch) -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.pool import StaticPool

        import app.db.session as session_mod
        from app.core.config import settings

        engine = create_async_engine(settings.database_url, poolclass=StaticPool)

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
