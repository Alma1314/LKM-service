from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.models import ContentItem
from app.db.session import get_read_session, get_session
from app.modules.auth.deps import CurrentUser, get_current_user
from app.modules.common import (
    ApiResp,
    PageData,
    PaginateDep,
    PaginateParams,
)
from app.modules.content.schemas import (
    ContentCommentCreate,
    ContentCommentInfo,
    ContentItemCreate,
    ContentItemInfo,
)
from app.modules.content.service import (
    create_comment,
    create_item,
    delete_item,
    get_item,
    get_item_by_slug,
    like_item,
    list_comments,
    list_items,
    unlike_item,
)
from app.modules.rbac.deps import RequirePermission
from app.modules.rbac.permissions import Permission
from app.modules.rbac.service import check_owner

router = APIRouter(prefix="/content", tags=["content"])


@router.get("/items", response_model=ApiResp[PageData[ContentItemInfo]])
@respond
async def get_content_items(
    pag: PaginateParams = Depends(PaginateDep()),
    board_id: int | None = Query(default=None, ge=1),
    content_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_read_session),
) -> PageData[ContentItemInfo]:
    return await list_items(
        db,
        page=pag.page,
        limit=pag.limit,
        board_id=board_id,
        content_type=content_type,
    )


@router.post("/items", response_model=ApiResp[ContentItemInfo])
@respond
async def create_content_item(
    info: ContentItemCreate,
    cur: CurrentUser = RequirePermission(Permission.content_create),
    db: AsyncSession = Depends(get_session),
) -> ContentItemInfo:
    return await create_item(db, cur.id, info)


@router.get("/items/{item_id}", response_model=ApiResp[ContentItemInfo])
@respond
async def get_content_detail(
    item_id: int, db: AsyncSession = Depends(get_session)
) -> ContentItemInfo:
    return await get_item(db, item_id, bump_view=True)


@router.get("/by-slug/{slug}", response_model=ApiResp[ContentItemInfo])
@respond
async def get_content_by_slug(
    slug: str, db: AsyncSession = Depends(get_session)
) -> ContentItemInfo:
    return await get_item_by_slug(db, slug)


@router.post("/items/{item_id}/like", response_model=ApiResp[dict[str, Any]])
@respond
async def like_content_item(
    item_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return {"like_count": await like_item(db, item_id, cur.id)}


@router.delete("/items/{item_id}/like", response_model=ApiResp[dict[str, Any]])
@respond
async def unlike_content_item(
    item_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return {"like_count": await unlike_item(db, item_id, cur.id)}


@router.delete("/items/{item_id}", response_model=ApiResp[dict[str, Any]])
@respond
async def delete_content_item(
    item_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await check_owner(
        db, cur, item_id, ContentItem, "author_id", Permission.content_owner_delete
    )
    await delete_item(db, item_id, cur.id)
    return {"ok": True}


@router.get(
    "/items/{item_id}/comments", response_model=ApiResp[PageData[ContentCommentInfo]]
)
@respond
async def get_content_comments(
    item_id: int,
    pag: PaginateParams = Depends(PaginateDep()),
    db: AsyncSession = Depends(get_read_session),
) -> PageData[ContentCommentInfo]:
    return await list_comments(db, item_id, page=pag.page, limit=pag.limit)


@router.post("/items/{item_id}/comments", response_model=ApiResp[ContentCommentInfo])
@respond
async def create_content_comment(
    item_id: int,
    info: ContentCommentCreate,
    cur: CurrentUser = RequirePermission(Permission.content_comment_create),
    db: AsyncSession = Depends(get_session),
) -> ContentCommentInfo:
    return await create_comment(db, item_id, cur.id, info)
