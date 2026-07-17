import sqlite3

from app.core.err import BizError, ErrCode
from app.modules.auth.schemas import ProfileInfo, ProfileUpdate, UserLoginInfo, UserRegInfo
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
    user_id = cur.lastrowid
    conn.execute("INSERT INTO profiles (user_id) VALUES (?)", (user_id,))
    return user_id


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


def get_profile(conn: sqlite3.Connection, user_id: int) -> ProfileInfo:
    row = conn.execute(
        "SELECT p.nickname, p.avatar, p.role, u.username "
        "FROM profiles p JOIN users u ON u.id = p.user_id "
        "WHERE p.user_id = ?",
        (user_id,),
    ).fetchone()

    if not row:
        raise BizError(ErrCode.USER_NOT_FOUND)

    return ProfileInfo(nickname=row["nickname"], avatar=row["avatar"], role=row["role"])


def update_profile(conn: sqlite3.Connection, user_id: int, info: ProfileUpdate) -> None:
    row = conn.execute(
        "SELECT user_id FROM profiles WHERE user_id = ?", (user_id,)
    ).fetchone()

    if not row:
        raise BizError(ErrCode.USER_NOT_FOUND)

    fields = []
    vals = []
    for key in ("nickname", "avatar"):
        val = getattr(info, key)
        if val is not None:
            fields.append(f"{key} = ?")
            vals.append(val)

    if fields:
        vals.append(user_id)
        conn.execute(
            f"UPDATE profiles SET {', '.join(fields)} WHERE user_id = ?",
            vals,
        )
