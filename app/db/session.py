import sqlite3
from contextlib import contextmanager

from app.core.config import settings


@contextmanager
def getdb(db_path: str | None = None):
    conn = sqlite3.connect(db_path or settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
