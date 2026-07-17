import sqlite3

from app.core.err import BizError, ErrCode
from app.modules.auth.schemas import UserLoginInfo, UserRegInfo
from app.modules.auth.security import hashpwd, verifypwd


def register(conn: sqlite3.Connection, info: UserRegInfo) -> int:
    cur = conn.execute(
        "SELECT id FROM users WHERE username = ? OR email = ?",
        (info.username, info.email),
    )
    if cur.fetchone():
        raise BizError(ErrCode.ALREADY_REGISTERED)

    hashed = hashpwd(info.password)
    cur = conn.execute(
        "INSERT INTO users (username, email, hpwd) VALUES (?, ?, ?)",
        (info.username, info.email, hashed),
    )
    return cur.lastrowid


def login(conn: sqlite3.Connection, info: UserLoginInfo) -> int:
    row = conn.execute(
        "SELECT id, hpwd FROM users WHERE username = ?",
        (info.username,),
    ).fetchone()

    if not row:
        raise BizError(ErrCode.USER_NOT_FOUND)

    if not verifypwd(info.password, row["hpwd"]):
        raise BizError(ErrCode.INVALID_CREDENTIALS)

    return row["id"]
