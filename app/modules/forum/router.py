from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.models import ForumPost
from app.db.session import get_read_session, get_session
from app.modules.auth.deps import CurrentUser, get_current_user
from app.modules.common import (
    ApiResp,
    ModuleStatus,
    PageData,
    PaginateDep,
    PaginateParams,
)
from app.modules.forum.schemas import (
    CommentCreate,
    CommentInfo,
    PostCreate,
    PostInfo,
)
from app.modules.forum.service import (
    create_comment,
    get_forum_plan,
    get_post,
    list_comments,
    list_posts,
)
from app.modules.forum.service import (
    create_post as create_post_service,
)
from app.modules.forum.service import (
    delete_post as delete_post_service,
)
from app.modules.forum.service import (
    like_post as like_post_service,
)
from app.modules.rbac.deps import RequirePermission
from app.modules.rbac.permissions import Permission
from app.modules.rbac.service import check_owner

router = APIRouter(prefix="/forum", tags=["forum"])


@router.get("/status", response_model=ModuleStatus)
async def forum_status() -> ModuleStatus:
    return ModuleStatus(
        module="forum",
        status="implemented_minimal",
        responsibility="Manage community forum posts and comments.",
        next_steps=get_forum_plan()["next_steps"],
    )


@router.get("/posts", response_model=ApiResp[PageData[PostInfo]])
@respond
async def get_posts(
    pag: PaginateParams = Depends(PaginateDep()),
    board_id: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_read_session),
) -> PageData[PostInfo]:
    return await list_posts(db, page=pag.page, limit=pag.limit, board_id=board_id)


@router.post("/posts", response_model=ApiResp[PostInfo])
@respond
async def create_forum_post(
    info: PostCreate,
    # 注意：RequirePermission(...) 已返回 Depends(checker)，不能再包一层 Depends()
    # （否则双重包裹会令 FastAPI 把 Depends 对象当 callable 而报错）。与
    # tests/test_rbac_deps_factory 的用法一致：工厂返回值直接作参数默认值。
    cur: CurrentUser = RequirePermission(Permission.forum_post_create),
    db: AsyncSession = Depends(get_session),
) -> PostInfo:
    return await create_post_service(db, cur.id, info)


@router.get("/posts/{post_id}", response_model=ApiResp[PostInfo])
@respond
async def get_post_detail(
    post_id: int, db: AsyncSession = Depends(get_session)
) -> PostInfo:
    return await get_post(db, post_id, bump_view=True)


@router.post("/posts/{post_id}/like", response_model=ApiResp[dict[str, Any]])
@respond
async def like_forum_post(
    post_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return {"like_count": await like_post_service(db, post_id, cur.id)}


@router.delete("/posts/{post_id}", response_model=ApiResp[dict[str, Any]])
@respond
async def delete_forum_post(
    post_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # 对象级权限：属主放行，或拥有 forum.owner_delete（admin 代管）放行。
    await check_owner(
        db, cur, post_id, ForumPost, "author_id", Permission.forum_owner_delete
    )
    await delete_post_service(db, post_id, cur.id)
    return {"ok": True}


@router.get("/posts/{post_id}/comments", response_model=ApiResp[PageData[CommentInfo]])
@respond
async def get_post_comments(
    post_id: int,
    pag: PaginateParams = Depends(PaginateDep()),
    db: AsyncSession = Depends(get_read_session),
) -> PageData[CommentInfo]:
    return await list_comments(db, post_id, page=pag.page, limit=pag.limit)


@router.post("/posts/{post_id}/comments", response_model=ApiResp[CommentInfo])
@respond
async def create_post_comment(
    post_id: int,
    info: CommentCreate,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> CommentInfo:
    return await create_comment(db, post_id, cur.id, info)
