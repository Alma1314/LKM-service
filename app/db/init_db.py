from sqlalchemy import Engine, inspect
from sqlalchemy import text as sql_text

from app.db.models import Base
from app.db.session import get_engine
import app.modules.auth.models  # pyright: ignore[reportUnusedImport]


def _ensure_auth_columns(engine: Engine) -> None:
    """create_all 不会更新已存在的表；此处幂等补齐开发期新加的列。"""
    insp = inspect(engine)
    if insp.has_table("oauth_states"):
        cols = {col["name"] for col in insp.get_columns("oauth_states")}
        if "user_id" not in cols:
            with engine.begin() as conn:
                conn.execute(sql_text("ALTER TABLE oauth_states ADD COLUMN user_id INTEGER NULL"))


def init_db() -> None:
    # 开发环境自动建表。生产环境使用 Alembic。
    engine = get_engine()
    assert engine is not None
    Base.metadata.create_all(bind=engine)
    _ensure_auth_columns(engine)
