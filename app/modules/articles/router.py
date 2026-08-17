from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.session import get_session
from app.modules.articles.schemas import (
    AboutItem,
    ArticleCategory,
    ArticleCommentCreate,
    ArticleCommentOut,
    ArticleDetail,
    ArticleLikeStatus,
    ArticleListData,
    TagItem,
)
from app.modules.articles.service import (
    create_article_comment,
    delete_article_comment,
    get_about,
    get_article,
    list_article_comments,
    list_articles,
    list_categories,
    list_tags,
    search_articles,
    toggle_article_like,
)
from app.modules.auth.deps import CurrentUser, get_current_user
from app.modules.common import ApiResp, ListData

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=ApiResp[ArticleListData])
@respond
async def get_articles(
    db: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    return await list_articles(db, page=page, page_size=page_size)


@router.get("/categories", response_model=ApiResp[ListData[ArticleCategory]])
@respond
async def get_article_categories(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return {"items": await list_categories(db)}


@router.get("/tags", response_model=ApiResp[ListData[TagItem]])
@respond
async def get_article_tags(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return {"items": await list_tags(db)}


@router.get("/search", response_model=ApiResp[ArticleListData])
@respond
async def search_articles_endpoint(
    q: str = Query(..., min_length=1, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await search_articles(db, q=q, page=page, page_size=page_size)


@router.get("/about", response_model=ApiResp[AboutItem])
@respond
async def get_about_endpoint() -> dict[str, str]:
    return await get_about()


@router.post("/{slug}/like", response_model=ApiResp[ArticleLikeStatus])
@respond
async def like_article(
    slug: str,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await toggle_article_like(db, slug, cur.id)


@router.get("/{slug}/comments", response_model=ApiResp[ListData[ArticleCommentOut]])
@respond
async def get_article_comments(
    slug: str,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # service 已返回带 profile 的 schema 列表，直接透传，避免二次 model_validate 丢失 profile
    return {"items": await list_article_comments(db, slug)}


@router.post("/{slug}/comments", response_model=ApiResp[ArticleCommentOut])
@respond
async def add_article_comment(
    body: ArticleCommentCreate,
    slug: str,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ArticleCommentOut:
    # 返回序列化后的 schema，避免 @respond 直接 model_dump 无法处理 ORM 对象
    return ArticleCommentOut.model_validate(
        await create_article_comment(db, slug, cur.id, body.content, body.parent_id)
    )


@router.delete("/comments/{comment_id}", response_model=ApiResp[None])
@respond
async def remove_article_comment(
    comment_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> None:
    await delete_article_comment(db, comment_id, cur.id)
    return None


@router.get("/{slug}", response_model=ApiResp[ArticleDetail])
@respond
async def get_article_detail(
    slug: str, db: AsyncSession = Depends(get_session)
) -> ArticleDetail:
    return await get_article(db, slug)
