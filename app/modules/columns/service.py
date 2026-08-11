from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from app.modules.columns.errors import ColumnErr
from app.db.models import Column, ColumnApplication, ColumnPost, now_iso
from app.db.repo import get_or_raise
from app.modules.columns.models import COLUMN_TABLE_PLAN, ColumnApplicationStatus, ColumnPostStatus
from app.modules.columns.schemas import (
    ColumnApplicationCreate,
    ColumnApplicationInfo,
    ColumnApplicationReview,
    ColumnInfo,
    ColumnPostCreate,
    ColumnPostInfo,
)


def get_column_plan() -> dict[str, Any]:
    return {
        "status": "implemented_minimal",
        "tables": COLUMN_TABLE_PLAN,
        "next_steps": [
            "Add authentication before write operations",
            "Restrict review APIs to administrators",
            "Add pagination, search, and board relation",
        ],
    }


async def create_application(
    db: AsyncSession, info: ColumnApplicationCreate
) -> ColumnApplicationInfo:
    app = ColumnApplication(
        user_id=info.user_id,
        title=info.title,
        description=info.description,
        reason=info.reason,
    )
    db.add(app)
    await db.flush()
    return ColumnApplicationInfo.model_validate(app)


async def list_applications(
    db: AsyncSession, page: int = 1, limit: int | None = None
) -> list[ColumnApplicationInfo]:
    """申请列表。不传 ``limit`` 时返回全部（保旧契约），传了则 SQL 层分页。"""
    stmt = select(ColumnApplication).order_by(ColumnApplication.id.desc())
    if limit is not None:
        stmt = stmt.offset((page - 1) * limit).limit(limit)
    apps = (await db.execute(stmt)).scalars().all()
    return [ColumnApplicationInfo.model_validate(a) for a in apps]


async def get_application(db: AsyncSession, application_id: int) -> ColumnApplicationInfo:
    return ColumnApplicationInfo.model_validate(await get_or_raise(
        db, ColumnApplication, ColumnErr.APPLICATION_NOT_FOUND,
        ColumnApplication.id == application_id,
    ))


async def review_application(
    db: AsyncSession, application_id: int, info: ColumnApplicationReview
) -> dict[str, Any]:
    app = await get_or_raise(
        db, ColumnApplication, ColumnErr.APPLICATION_NOT_FOUND,
        ColumnApplication.id == application_id,
    )

    app.status = info.status
    app.reviewer_id = info.reviewer_id
    app.review_note = info.review_note
    app.reviewed_at = now_iso()
    await db.flush()

    column = None
    if info.status == ColumnApplicationStatus.APPROVED:
        column = await _ensure_column_for_application(db, app)

    return {
        "application": ColumnApplicationInfo.model_validate(app).model_dump(),
        "column": column.model_dump() if column else None,
    }


async def list_columns(db: AsyncSession, page: int = 1, limit: int | None = None) -> list[ColumnInfo]:
    stmt = select(Column).order_by(Column.id.desc())
    if limit is not None:
        stmt = stmt.offset((page - 1) * limit).limit(limit)
    cols = (await db.execute(stmt)).scalars().all()
    return [ColumnInfo.model_validate(c) for c in cols]


async def get_column(db: AsyncSession, column_id: int) -> ColumnInfo:
    return ColumnInfo.model_validate(await get_or_raise(
        db, Column, ColumnErr.NOT_FOUND, Column.id == column_id,
    ))


async def create_post(
    db: AsyncSession, column_id: int, info: ColumnPostCreate
) -> ColumnPostInfo:
    await get_or_raise(db, Column, ColumnErr.NOT_FOUND, Column.id == column_id)

    post = ColumnPost(
        column_id=column_id,
        author_id=info.author_id,
        title=info.title,
        summary=info.summary,
        content=info.content,
        status=ColumnPostStatus.PUBLISHED,
        published_at=now_iso(),
    )
    db.add(post)
    await db.flush()
    return ColumnPostInfo.model_validate(post)


async def list_posts(
    db: AsyncSession, column_id: int, page: int = 1, limit: int | None = None
) -> list[ColumnPostInfo]:
    await get_or_raise(db, Column, ColumnErr.NOT_FOUND, Column.id == column_id)
    stmt = (
        select(ColumnPost)
        .where(ColumnPost.column_id == column_id)
        .order_by(ColumnPost.id.desc())
    )
    if limit is not None:
        stmt = stmt.offset((page - 1) * limit).limit(limit)
    posts = (await db.execute(stmt)).scalars().all()
    return [ColumnPostInfo.model_validate(p) for p in posts]


async def get_post(
    db: AsyncSession, post_id: int, column_id: int | None = None
) -> ColumnPostInfo:
    filters = [ColumnPost.id == post_id]
    if column_id is not None:
        filters.append(ColumnPost.column_id == column_id)
    return ColumnPostInfo.model_validate(await get_or_raise(
        db, ColumnPost, ColumnErr.POST_NOT_FOUND, *filters,
    ))


async def _ensure_column_for_application(
    db: AsyncSession, application: ColumnApplication
) -> ColumnInfo:
    col = (
        await db.execute(select(Column).where(Column.application_id == application.id))
    ).scalars().first()
    if col:
        return ColumnInfo.model_validate(col)

    col = Column(
        owner_id=application.user_id,
        application_id=application.id,
        title=application.title,
        description=application.description,
    )
    db.add(col)
    await db.flush()
    return ColumnInfo.model_validate(col)
