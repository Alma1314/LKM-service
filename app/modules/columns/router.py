from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError, CommonErr, respond
from app.db.models import Column, ColumnApplication
from app.db.session import get_read_session, get_session
from app.modules.admin.deps import require_admin_2fa
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
from app.modules.common import ApiResp, ModuleStatus, PageData
from app.modules.rbac.deps import RequirePermission
from app.modules.rbac.permissions import Permission, composible_role
from app.modules.rbac.service import check_owner, role_has_permission

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
    cur: CurrentUser = RequirePermission(Permission.columns_application_create),
    db: AsyncSession = Depends(get_session),
) -> ColumnApplicationInfo:
    return await create_application(db, cur.id, info)


@router.get("/applications", response_model=ApiResp[PageData[ColumnApplicationInfo]])
@respond
async def get_applications(
    cur: CurrentUser = RequireLevel("admin"),
    db: AsyncSession = Depends(get_read_session),
    page: int = Query(1, ge=1),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> PageData[ColumnApplicationInfo]:
    # RequireLevel("admin") 已保证 admin 会话；此处再叠加 columns_application_review
    # 权限点（super_admin 有，org_member 等普通 admin 无），与审核同权限（能看全部申请=能审核）。
    if not await role_has_permission(
        db,
        composible_role(cur.account_level, cur.role),
        Permission.columns_application_review,
    ):
        raise BizError(CommonErr.FORBIDDEN)
    return await list_applications(db, page=page, limit=limit)


@router.get(
    "/applications/{application_id}", response_model=ApiResp[ColumnApplicationInfo]
)
@respond
async def get_application_detail(
    application_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ColumnApplicationInfo:
    # 申请人本人（column.owner_publish 判属主 app.user_id==cur.id）可看；super_admin
    # 持有 owner 权限点可代看任意申请详情；他人 403。
    await check_owner(
        db,
        cur,
        application_id,
        ColumnApplication,
        "user_id",
        Permission.column_owner_publish,
    )
    return await get_application(db, application_id)


@router.post(
    "/applications/{application_id}/review", response_model=ApiResp[ReviewResultData]
)
@respond
async def review_column_application(
    application_id: int,
    info: ColumnApplicationReview,
    cur: CurrentUser = require_admin_2fa,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # require_admin_2fa 已保证 admin 会话 + 2FA 信任（危险操作 step-up，与 boards/projects 审核一致）；
    # 此处再叠加 columns_application_review 权限点（super_admin 有，普通 admin 无）。校验失败按 FORBIDDEN 返回。
    if not await role_has_permission(
        db,
        composible_role(cur.account_level, cur.role),
        Permission.columns_application_review,
    ):
        raise BizError(CommonErr.FORBIDDEN)
    return await review_application(db, application_id, info, cur.id)


@router.get("", response_model=ApiResp[PageData[ColumnInfo]])
@respond
async def get_columns(
    db: AsyncSession = Depends(get_read_session),
    page: int = Query(1, ge=1),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> PageData[ColumnInfo]:
    return await list_columns(db, page=page, limit=limit)


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
    cur: CurrentUser = RequirePermission(Permission.columns_publish),
    db: AsyncSession = Depends(get_session),
) -> ColumnPostInfo:
    # 属主判定：普通博主（无 column.owner_publish）只能在**自己**专栏发
    # （column.owner_id==cur.id）；super_admin 持有 owner 权限点可代发任意专栏。
    # 先 get_column 保留「专栏不存在→NOT_FOUND」语义，再由 check_owner 做属主/代管判定。
    await get_column(db, column_id)
    await check_owner(
        db, cur, column_id, Column, "owner_id", Permission.column_owner_publish
    )
    return await create_post(db, column_id, info, cur.id)


@router.get("/{column_id}/posts", response_model=ApiResp[PageData[ColumnPostInfo]])
@respond
async def get_column_posts(
    column_id: int,
    db: AsyncSession = Depends(get_read_session),
    page: int = Query(1, ge=1),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> PageData[ColumnPostInfo]:
    return await list_posts(db, column_id, page=page, limit=limit)


@router.get("/{column_id}/posts/{post_id}", response_model=ApiResp[ColumnPostInfo])
@respond
async def get_column_post_detail(
    column_id: int, post_id: int, db: AsyncSession = Depends(get_read_session)
) -> ColumnPostInfo:
    return await get_post(db, post_id, column_id=column_id)
