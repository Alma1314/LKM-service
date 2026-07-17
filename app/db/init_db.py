import sqlite3


def init_db(conn: sqlite3.Connection | None = None) -> None:
    if conn is None:
        from app.db.session import getdb

        with getdb() as conn:
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            nickname TEXT,
            avatar TEXT,
            role TEXT NOT NULL DEFAULT 'member'
        )
    """)
