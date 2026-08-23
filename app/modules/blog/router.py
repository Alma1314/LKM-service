from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.models import ArticleCategory
from app.db.session import get_read_session, get_session
from app.modules.articles.schemas import ArticleDetail
from app.modules.auth.deps import (
    CurrentUser,
    get_current_user,
    get_optional_user,
)
from app.modules.blog.schemas import (
    BlogCommentCreate,
    BlogCommentInfo,
    BlogSeriesCreate,
    BlogSeriesDetail,
    BlogSeriesInfo,
    BlogSeriesUpdate,
    BlogStarStatus,
    GitFileContent,
    SeriesFileWrite,
    SeriesPublish,
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
    publish_series_file,
    toggle_star,
    update_series,
    write_series_file,
)
from app.modules.common import ApiResp, ListData, PageData, PaginateDep, PaginateParams

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


@router.get("/series", response_model=ApiResp[PageData[BlogSeriesInfo]])
@respond
async def list_blog_series(
    db: AsyncSession = Depends(get_read_session),
    cur: CurrentUser | None = Depends(get_optional_user),
    pag: PaginateParams = Depends(PaginateDep()),
) -> PageData[BlogSeriesInfo]:
    user_id = cur.id if cur else None
    return await list_series(
        db, current_user_id=user_id, page=pag.page, limit=pag.limit
    )


@router.get("/series/{series_id}", response_model=ApiResp[BlogSeriesDetail])
@respond
async def get_blog_series(
    series_id: int,
    db: AsyncSession = Depends(get_read_session),
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
    db: AsyncSession = Depends(get_read_session),
) -> dict[str, Any]:
    return await get_file_content(db, series_id, filepath)


@router.put(
    "/series/{series_id}/files/{filepath:path}",
    response_model=ApiResp[None],
)
@respond
async def put_blog_file(
    series_id: int,
    filepath: str,
    body: SeriesFileWrite,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> None:
    await write_series_file(db, series_id, cur.id, filepath, body.content, body.message)
    return None


@router.post("/series/{series_id}/publish", response_model=ApiResp[ArticleDetail])
@respond
async def publish_series_file_endpoint(
    series_id: int,
    body: SeriesPublish,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ArticleDetail:
    article = await publish_series_file(
        db, series_id, cur.id, body.filepath, body.override
    )
    # article.tags 是 Tag 对象列表，ArticleDetail.tags 期望字符串 list。
    # 不能直接 model_validate(article)：from_attributes 会读 article.tags 得到 Tag
    # 对象而校验失败。故从标量属性构造 dict，tags 单独 map 成字符串。
    # category_title 非 ORM 标量，须另行解析（article 仅有 category_id 外键）。
    category_title = await db.scalar(
        select(ArticleCategory.title).where(ArticleCategory.id == article.category_id)
    )
    return ArticleDetail(
        **{
            k: v
            for k, v in article.__dict__.items()
            if k in ArticleDetail.model_fields and k != "tags"
        },
        category_title=str(category_title) if category_title is not None else "",
        tags=[t.name for t in (article.tags or [])],
    )


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
    db: AsyncSession = Depends(get_read_session),
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
