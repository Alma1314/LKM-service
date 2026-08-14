from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.session import get_session
from app.modules.auth.deps import CurrentUser, get_current_user, get_optional_user
from app.modules.blog.schemas import (
    BlogCommentCreate,
    BlogCommentInfo,
    BlogSeriesCreate,
    BlogSeriesDetail,
    BlogSeriesInfo,
    BlogSeriesUpdate,
    BlogStarStatus,
    GitFileContent,
)
from app.modules.blog.service import (
    create_comment,
    create_series,
    delete_comment,
    delete_series,
    get_file_content,
    get_series,
    list_comments,
    list_series,
    toggle_star,
    update_series,
)
from app.modules.common import ApiResp, ListData

router = APIRouter(prefix="/blog", tags=["blog"])


# ---- Series ----


@router.post("/series", response_model=ApiResp[BlogSeriesInfo])
@respond
async def create_blog_series(
    info: BlogSeriesCreate,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> BlogSeriesInfo:
    return await create_series(db, cur.id, info)


@router.get("/series", response_model=ApiResp[ListData[BlogSeriesInfo]])
@respond
async def list_blog_series(
    db: AsyncSession = Depends(get_session),
    cur: CurrentUser | None = Depends(get_optional_user),
    page: int = Query(1, ge=1),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> dict[str, Any]:
    user_id = cur.id if cur else None
    return {
        "items": await list_series(db, current_user_id=user_id, page=page, limit=limit)
    }


@router.get("/series/{series_id}", response_model=ApiResp[BlogSeriesDetail])
@respond
async def get_blog_series(
    series_id: int,
    db: AsyncSession = Depends(get_session),
    cur: CurrentUser | None = Depends(get_optional_user),
) -> BlogSeriesDetail:
    user_id = cur.id if cur else None
    return await get_series(db, series_id, current_user_id=user_id)


@router.put("/series/{series_id}", response_model=ApiResp[BlogSeriesInfo])
@respond
async def update_blog_series(
    series_id: int,
    info: BlogSeriesUpdate,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> BlogSeriesInfo:
    return await update_series(db, series_id, cur.id, info)


@router.delete("/series/{series_id}")
@respond
async def delete_blog_series(
    series_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> None:
    await delete_series(db, series_id, cur.id)
    return None


# ---- Files ----


@router.get(
    "/series/{series_id}/files/{filepath:path}",
    response_model=ApiResp[GitFileContent],
)
@respond
async def get_blog_file(
    series_id: int,
    filepath: str,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await get_file_content(db, series_id, filepath)


# ---- Stars ----


@router.post("/series/{series_id}/star", response_model=ApiResp[BlogStarStatus])
@respond
async def star_blog_series(
    series_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> BlogStarStatus:
    return await toggle_star(db, series_id, cur.id)


# ---- Comments ----


@router.post(
    "/series/{series_id}/comments",
    response_model=ApiResp[BlogCommentInfo],
)
@respond
async def create_blog_comment(
    series_id: int,
    info: BlogCommentCreate,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> BlogCommentInfo:
    return await create_comment(db, series_id, cur.id, info)


@router.get(
    "/series/{series_id}/comments",
    response_model=ApiResp[ListData[BlogCommentInfo]],
)
@respond
async def list_blog_comments(
    series_id: int,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return {"items": await list_comments(db, series_id)}


@router.delete("/series/{series_id}/comments/{comment_id}")
@respond
async def delete_blog_comment(
    series_id: int,
    comment_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> None:
    await delete_comment(db, series_id, comment_id, cur.id)
    return None
