from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError, CommonErr, respond
from app.db.session import get_session
from app.modules.auth.deps import CurrentUser, get_current_user
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
async def column_plan():
    return get_column_plan()


@router.post("/applications", response_model=ApiResp[ColumnApplicationInfo])
@respond
async def apply_column(
    info: ColumnApplicationCreate,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if cur.id != info.user_id:
        raise BizError(CommonErr.FORBIDDEN)
    return await create_application(db, info)


@router.get("/applications", response_model=ApiResp[ListData[ColumnApplicationInfo]])
@respond
async def get_applications(
    db: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
    limit: int | None = Query(default=None, ge=1, le=200),
):
    return {"items": await list_applications(db, page=page, limit=limit)}


@router.get("/applications/{application_id}", response_model=ApiResp[ColumnApplicationInfo])
@respond
async def get_application_detail(application_id: int, db: AsyncSession = Depends(get_session)):
    return await get_application(db, application_id)


@router.post("/applications/{application_id}/review", response_model=ApiResp[ReviewResultData])
@respond
async def review_column_application(
    application_id: int,
    info: ColumnApplicationReview,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if cur.id != info.reviewer_id:
        raise BizError(CommonErr.FORBIDDEN)
    return await review_application(db, application_id, info)


@router.get("", response_model=ApiResp[ListData[ColumnInfo]])
@respond
async def get_columns(
    db: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
    limit: int | None = Query(default=None, ge=1, le=200),
):
    return {"items": await list_columns(db, page=page, limit=limit)}


@router.get("/{column_id}", response_model=ApiResp[ColumnInfo])
@respond
async def get_column_detail(column_id: int, db: AsyncSession = Depends(get_session)):
    return await get_column(db, column_id)


@router.post("/{column_id}/posts", response_model=ApiResp[ColumnPostInfo])
@respond
async def publish_column_post(
    column_id: int,
    info: ColumnPostCreate,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if cur.id != info.author_id:
        raise BizError(CommonErr.FORBIDDEN)
    return await create_post(db, column_id, info)


@router.get("/{column_id}/posts", response_model=ApiResp[ListData[ColumnPostInfo]])
@respond
async def get_column_posts(
    column_id: int,
    db: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
    limit: int | None = Query(default=None, ge=1, le=200),
):
    return {"items": await list_posts(db, column_id, page=page, limit=limit)}


@router.get("/{column_id}/posts/{post_id}", response_model=ApiResp[ColumnPostInfo])
@respond
async def get_column_post_detail(column_id: int, post_id: int, db: AsyncSession = Depends(get_session)):
    return await get_post(db, post_id, column_id=column_id)
