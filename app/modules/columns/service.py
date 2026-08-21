from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import (
    TTL_ITEM_S,
    TTL_LIST_S,
    bump_collection_version,
    cached_read,
    collection_version,
    make_key,
)
from app.core.err import BizError
from app.db.models import Column, ColumnApplication, ColumnPost, now_iso
from app.db.repo import get_or_raise
from app.modules.columns.errors import ColumnErr
from app.modules.columns.models import (
    COLUMN_TABLE_PLAN,
    ColumnApplicationStatus,
    ColumnPostStatus,
)
from app.modules.columns.schemas import (
    ColumnApplicationCreate,
    ColumnApplicationInfo,
    ColumnApplicationReview,
    ColumnInfo,
    ColumnPostCreate,
    ColumnPostInfo,
)
from app.modules.common import PageData, paginate_offset, paginate_pages


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
    db: AsyncSession, user_id: int, info: ColumnApplicationCreate
) -> ColumnApplicationInfo:
    app = ColumnApplication(
        user_id=user_id,
        title=info.title,
        description=info.description,
        reason=info.reason,
    )
    db.add(app)
    await db.flush()
    return ColumnApplicationInfo.model_validate(app)


async def list_applications(
    db: AsyncSession, page: int = 1, limit: int | None = None
) -> PageData[ColumnApplicationInfo]:
    """申请列表，统一返回 ``PageData``。不传 ``limit`` 时返回全部（page 恒为 1，pages 视总数）。"""
    total = (
        await db.scalar(select(func.count()).select_from(ColumnApplication)) or 0
    )
    stmt = select(ColumnApplication).order_by(ColumnApplication.id.desc())
    if limit is not None:
        stmt = stmt.offset(paginate_offset(page, limit)).limit(limit)
    apps = (await db.execute(stmt)).scalars().all()
    return PageData(
        items=[ColumnApplicationInfo.model_validate(a) for a in apps],
        total=total,
        page=page,
        pages=paginate_pages(total, limit) if limit else (1 if total else 0),
    )


async def get_application(
    db: AsyncSession, application_id: int
) -> ColumnApplicationInfo:
    return ColumnApplicationInfo.model_validate(
        await get_or_raise(
            db,
            ColumnApplication,
            ColumnErr.APPLICATION_NOT_FOUND,
            ColumnApplication.id == application_id,
        )
    )


async def review_application(
    db: AsyncSession,
    application_id: int,
    info: ColumnApplicationReview,
    reviewer_id: int,
) -> dict[str, Any]:
    app = await get_or_raise(
        db,
        ColumnApplication,
        ColumnErr.APPLICATION_NOT_FOUND,
        ColumnApplication.id == application_id,
    )

    # 已审幂等：非 PENDING 状态拒绝再次审批（防状态翻转/重复审批）
    if app.status != ColumnApplicationStatus.PENDING:
        raise BizError(ColumnErr.APPLICATION_ALREADY_REVIEWED)

    app.status = info.status
    app.reviewer_id = reviewer_id
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


async def list_columns(
    db: AsyncSession, page: int = 1, limit: int | None = None
) -> PageData[ColumnInfo]:
    ver = await collection_version("columns")

    async def _load() -> dict[str, Any]:
        total = await db.scalar(select(func.count()).select_from(Column)) or 0
        stmt = select(Column).order_by(Column.id.desc())
        if limit is not None:
            stmt = stmt.offset(paginate_offset(page, limit)).limit(limit)
        cols = (await db.execute(stmt)).scalars().all()
        return PageData(
            items=[ColumnInfo.model_validate(c).model_dump() for c in cols],
            total=total,
            page=page,
            pages=paginate_pages(total, limit) if limit else (1 if total else 0),
        ).model_dump(mode="json")

    payload = await cached_read(
        make_key("columns:list", ver, page, limit), TTL_LIST_S, _load
    )
    # cached_read 返回 PageData 的 dict，转回 schema
    return PageData(
        items=[ColumnInfo.model_validate(c) for c in payload["items"]],
        total=payload["total"],
        page=payload["page"],
        pages=payload["pages"],
    )


async def get_column(db: AsyncSession, column_id: int) -> ColumnInfo:
    async def _load() -> dict[str, Any]:
        return ColumnInfo.model_validate(
            await get_or_raise(
                db,
                Column,
                ColumnErr.NOT_FOUND,
                Column.id == column_id,
            )
        ).model_dump()

    payload = await cached_read(make_key("columns:by_id", column_id), TTL_ITEM_S, _load)
    return ColumnInfo.model_validate(payload)


async def get_column_by_slug(db: AsyncSession, slug: str) -> ColumnInfo:
    async def _load() -> dict[str, Any]:
        return ColumnInfo.model_validate(
            await get_or_raise(
                db,
                Column,
                ColumnErr.NOT_FOUND,
                Column.slug == slug,
            )
        ).model_dump()

    payload = await cached_read(make_key("columns:by_slug", slug), TTL_ITEM_S, _load)
    return ColumnInfo.model_validate(payload)


async def create_post(
    db: AsyncSession, column_id: int, info: ColumnPostCreate, author_id: int
) -> ColumnPostInfo:
    await get_or_raise(db, Column, ColumnErr.NOT_FOUND, Column.id == column_id)

    post = ColumnPost(
        column_id=column_id,
        author_id=author_id,
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
) -> PageData[ColumnPostInfo]:
    await get_or_raise(db, Column, ColumnErr.NOT_FOUND, Column.id == column_id)
    total = (
        await db.scalar(
            select(func.count())
            .select_from(ColumnPost)
            .where(ColumnPost.column_id == column_id)
        )
        or 0
    )
    stmt = (
        select(ColumnPost)
        .where(ColumnPost.column_id == column_id)
        .order_by(ColumnPost.id.desc())
    )
    if limit is not None:
        stmt = stmt.offset(paginate_offset(page, limit)).limit(limit)
    posts = (await db.execute(stmt)).scalars().all()
    return PageData(
        items=[ColumnPostInfo.model_validate(p) for p in posts],
        total=total,
        page=page,
        pages=paginate_pages(total, limit) if limit else (1 if total else 0),
    )


async def get_post(
    db: AsyncSession, post_id: int, column_id: int | None = None
) -> ColumnPostInfo:
    filters = [ColumnPost.id == post_id]
    if column_id is not None:
        filters.append(ColumnPost.column_id == column_id)
    return ColumnPostInfo.model_validate(
        await get_or_raise(
            db,
            ColumnPost,
            ColumnErr.POST_NOT_FOUND,
            *filters,
        )
    )


async def _ensure_column_for_application(
    db: AsyncSession, application: ColumnApplication
) -> ColumnInfo:
    col = (
        (
            await db.execute(
                select(Column).where(Column.application_id == application.id)
            )
        )
        .scalars()
        .first()
    )
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
    # 集合新增：升级列列表版本号，使旧分页缓存立即失效（写后读一致）
    await bump_collection_version("columns")
    return ColumnInfo.model_validate(col)
