import sqlite3
from contextlib import contextmanager

DB_PATH = "lkm.db"


def initdb(conn: sqlite3.Connection | None = None) -> None:
    """Create tables if they don't exist."""
    if conn is None:
        with sqlite3.connect(DB_PATH) as conn:
            _init_tables(conn)
    else:
        _init_tables(conn)


def _init_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            hpwd TEXT NOT NULL
        )
    """)


@contextmanager
def getdb(db_path: str | None = None):
    """Yield a connection with row_factory set. Commits on success, rolls back on error."""
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
