import sqlite3

from app.core.err import BizError, ErrCode
from app.modules.columns.models import COLUMN_TABLE_PLAN, ColumnApplicationStatus
from app.modules.columns.schemas import (
    ColumnApplicationCreate,
    ColumnApplicationInfo,
    ColumnApplicationReview,
    ColumnInfo,
    ColumnPostCreate,
    ColumnPostInfo,
)


def get_column_plan() -> dict:
    return {
        "status": "implemented_minimal",
        "tables": COLUMN_TABLE_PLAN,
        "next_steps": [
            "Add authentication before write operations",
            "Restrict review APIs to administrators",
            "Add pagination, search, and board relation",
        ],
    }


def create_application(
    conn: sqlite3.Connection,
    info: ColumnApplicationCreate,
) -> ColumnApplicationInfo:
    cur = conn.execute(
        """
        INSERT INTO column_applications (user_id, title, description, reason)
        VALUES (?, ?, ?, ?)
        """,
        (info.user_id, info.title, info.description, info.reason),
    )
    return get_application(conn, cur.lastrowid)


def list_applications(conn: sqlite3.Connection) -> list[ColumnApplicationInfo]:
    rows = conn.execute(
        """
        SELECT id, user_id, title, description, reason, status, reviewer_id,
               review_note, created_at, reviewed_at
        FROM column_applications
        ORDER BY id DESC
        """
    ).fetchall()
    return [_application_from_row(row) for row in rows]


def get_application(conn: sqlite3.Connection, application_id: int) -> ColumnApplicationInfo:
    row = conn.execute(
        """
        SELECT id, user_id, title, description, reason, status, reviewer_id,
               review_note, created_at, reviewed_at
        FROM column_applications
        WHERE id = ?
        """,
        (application_id,),
    ).fetchone()
    if not row:
        raise BizError(ErrCode.COLUMN_APPLICATION_NOT_FOUND)
    return _application_from_row(row)


def review_application(
    conn: sqlite3.Connection,
    application_id: int,
    info: ColumnApplicationReview,
) -> dict:
    application = get_application(conn, application_id)
    conn.execute(
        """
        UPDATE column_applications
        SET status = ?, reviewer_id = ?, review_note = ?, reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (info.status, info.reviewer_id, info.review_note, application_id),
    )

    column = None
    if info.status == ColumnApplicationStatus.APPROVED:
        column = _ensure_column_for_application(conn, application)

    return {
        "application": get_application(conn, application_id).model_dump(),
        "column": column.model_dump() if column else None,
    }


def list_columns(conn: sqlite3.Connection) -> list[ColumnInfo]:
    rows = conn.execute(
        """
        SELECT id, owner_id, application_id, title, description, cover_url,
               status, created_at, updated_at
        FROM columns
        ORDER BY id DESC
        """
    ).fetchall()
    return [_column_from_row(row) for row in rows]


def get_column(conn: sqlite3.Connection, column_id: int) -> ColumnInfo:
    row = conn.execute(
        """
        SELECT id, owner_id, application_id, title, description, cover_url,
               status, created_at, updated_at
        FROM columns
        WHERE id = ?
        """,
        (column_id,),
    ).fetchone()
    if not row:
        raise BizError(ErrCode.COLUMN_NOT_FOUND)
    return _column_from_row(row)


def create_post(
    conn: sqlite3.Connection,
    column_id: int,
    info: ColumnPostCreate,
) -> ColumnPostInfo:
    get_column(conn, column_id)
    cur = conn.execute(
        """
        INSERT INTO column_posts (
            column_id, author_id, title, summary, content, status, published_at
        )
        VALUES (?, ?, ?, ?, ?, 'published', CURRENT_TIMESTAMP)
        """,
        (column_id, info.author_id, info.title, info.summary, info.content),
    )
    return get_post(conn, cur.lastrowid, column_id=column_id)


def list_posts(conn: sqlite3.Connection, column_id: int) -> list[ColumnPostInfo]:
    get_column(conn, column_id)
    rows = conn.execute(
        """
        SELECT id, column_id, author_id, title, summary, status,
               created_at, updated_at, published_at
        FROM column_posts
        WHERE column_id = ?
        ORDER BY id DESC
        """,
        (column_id,),
    ).fetchall()
    return [_post_from_row(row) for row in rows]


def get_post(
    conn: sqlite3.Connection,
    post_id: int,
    column_id: int | None = None,
) -> ColumnPostInfo:
    conditions = ["id = ?"]
    params: list[int] = [post_id]
    if column_id is not None:
        conditions.append("column_id = ?")
        params.append(column_id)

    row = conn.execute(
        f"""
        SELECT id, column_id, author_id, title, summary, status,
               created_at, updated_at, published_at
        FROM column_posts
        WHERE {' AND '.join(conditions)}
        """,
        params,
    ).fetchone()
    if not row:
        raise BizError(ErrCode.COLUMN_POST_NOT_FOUND)
    return _post_from_row(row)


def _ensure_column_for_application(
    conn: sqlite3.Connection,
    application: ColumnApplicationInfo,
) -> ColumnInfo:
    row = conn.execute(
        """
        SELECT id, owner_id, application_id, title, description, cover_url,
               status, created_at, updated_at
        FROM columns
        WHERE application_id = ?
        """,
        (application.id,),
    ).fetchone()
    if row:
        return _column_from_row(row)

    cur = conn.execute(
        """
        INSERT INTO columns (owner_id, application_id, title, description)
        VALUES (?, ?, ?, ?)
        """,
        (application.user_id, application.id, application.title, application.description),
    )
    return get_column(conn, cur.lastrowid)


def _application_from_row(row: sqlite3.Row) -> ColumnApplicationInfo:
    return ColumnApplicationInfo(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        description=row["description"],
        reason=row["reason"],
        status=row["status"],
        reviewer_id=row["reviewer_id"],
        review_note=row["review_note"],
        created_at=row["created_at"],
        reviewed_at=row["reviewed_at"],
    )


def _column_from_row(row: sqlite3.Row) -> ColumnInfo:
    return ColumnInfo(
        id=row["id"],
        owner_id=row["owner_id"],
        application_id=row["application_id"],
        title=row["title"],
        description=row["description"],
        cover_url=row["cover_url"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _post_from_row(row: sqlite3.Row) -> ColumnPostInfo:
    return ColumnPostInfo(
        id=row["id"],
        column_id=row["column_id"],
        author_id=row["author_id"],
        title=row["title"],
        summary=row["summary"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        published_at=row["published_at"],
    )
