from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_engine() -> Engine | None:
    global _engine
    if _engine is None:
        connect_args: dict = {}
        if settings.db_driver == "sqlite":
            connect_args["check_same_thread"] = False
        _engine = create_engine(
            settings.database_url,
            echo=False, # 不打印SQL日志
            connect_args=connect_args,
        )
    return _engine


def _get_session_local() -> sessionmaker | None:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False, # 不自动提交事务
            autoflush=False, # 不自动刷新
            bind=get_engine(),
        )
    return _SessionLocal


def get_session():
    db = _get_session_local()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def dispose_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _SessionLocal = None
