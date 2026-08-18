from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError, CommonErr, respond
from app.db.session import get_read_session, get_session
from app.modules.auth.deps import CurrentUser, RequireLevel, get_current_user
from app.modules.columns.schemas import (
    ColumnApplicationCreate,
    ColumnApplicationInfo,
    ColumnApplicationReview,
    ColumnInfo,
    ColumnPlanData,
    ColumnPostCreate,
    ColumnPostInfo,
    ReviewResultData,
)
from app.modules.columns.service import (
    create_application,
    create_post,
    get_application,
    get_column,
    get_column_by_slug,
    get_column_plan,
    get_post,
    list_applications,
    list_columns,
    list_posts,
    review_application,
)
from app.modules.common import ApiResp, ListData, ModuleStatus

router = APIRouter(prefix="/columns", tags=["columns"])


@router.get("/status", response_model=ModuleStatus)
async def columns_status() -> ModuleStatus:
    return ModuleStatus(
        module="columns",
        status="implemented_minimal",
        responsibility="Handle column applications, approved columns, and column posts.",
        next_steps=[
            "Add authentication before write operations",
            "Restrict review APIs to administrators",
            "Add pagination, search, and board relation",
        ],
    )


@router.get("/plan", response_model=ApiResp[ColumnPlanData])
@respond
async def column_plan() -> dict[str, Any]:
    return get_column_plan()


@router.post("/applications", response_model=ApiResp[ColumnApplicationInfo])
@respond
async def apply_column(
    info: ColumnApplicationCreate,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ColumnApplicationInfo:
    return await create_application(db, cur.id, info)


@router.get("/applications", response_model=ApiResp[ListData[ColumnApplicationInfo]])
@respond
async def get_applications(
    cur: CurrentUser = RequireLevel("admin"),
    db: AsyncSession = Depends(get_read_session),
    page: int = Query(1, ge=1),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> dict[str, Any]:
    return {"items": await list_applications(db, page=page, limit=limit)}


@router.get(
    "/applications/{application_id}", response_model=ApiResp[ColumnApplicationInfo]
)
@respond
async def get_application_detail(
    application_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_read_session),
) -> ColumnApplicationInfo:
    app = await get_application(db, application_id)
    if cur.account_level != "admin" and cur.id != app.user_id:
        raise BizError(CommonErr.FORBIDDEN)
    return app


@router.post(
    "/applications/{application_id}/review", response_model=ApiResp[ReviewResultData]
)
@respond
async def review_column_application(
    application_id: int,
    info: ColumnApplicationReview,
    cur: CurrentUser = RequireLevel("admin"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await review_application(db, application_id, info, cur.id)


@router.get("", response_model=ApiResp[ListData[ColumnInfo]])
@respond
async def get_columns(
    db: AsyncSession = Depends(get_read_session),
    page: int = Query(1, ge=1),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> dict[str, Any]:
    return {"items": await list_columns(db, page=page, limit=limit)}


@router.get("/by-slug/{slug}", response_model=ApiResp[ColumnInfo])
@respond
async def get_column_detail_by_slug(
    slug: str, db: AsyncSession = Depends(get_read_session)
) -> ColumnInfo:
    return await get_column_by_slug(db, slug)


@router.get("/{column_id}", response_model=ApiResp[ColumnInfo])
@respond
async def get_column_detail(
    column_id: int, db: AsyncSession = Depends(get_read_session)
) -> ColumnInfo:
    return await get_column(db, column_id)


@router.post("/{column_id}/posts", response_model=ApiResp[ColumnPostInfo])
@respond
async def publish_column_post(
    column_id: int,
    info: ColumnPostCreate,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ColumnPostInfo:
    column = await get_column(db, column_id)
    if cur.account_level != "admin" and cur.id != column.owner_id:
        raise BizError(CommonErr.FORBIDDEN)
    return await create_post(db, column_id, info, cur.id)


@router.get("/{column_id}/posts", response_model=ApiResp[ListData[ColumnPostInfo]])
@respond
async def get_column_posts(
    column_id: int,
    db: AsyncSession = Depends(get_read_session),
    page: int = Query(1, ge=1),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> dict[str, Any]:
    return {"items": await list_posts(db, column_id, page=page, limit=limit)}


@router.get("/{column_id}/posts/{post_id}", response_model=ApiResp[ColumnPostInfo])
@respond
async def get_column_post_detail(
    column_id: int, post_id: int, db: AsyncSession = Depends(get_read_session)
) -> ColumnPostInfo:
    return await get_post(db, post_id, column_id=column_id)
