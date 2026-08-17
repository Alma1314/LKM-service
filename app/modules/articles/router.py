from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.session import get_session
from app.modules.articles.schemas import (
    AboutItem,
    ArticleCategory,
    ArticleDetail,
    ArticleListData,
    TagItem,
)
from app.modules.articles.service import (
    get_about,
    get_article,
    list_articles,
    list_categories,
    list_tags,
    search_articles,
)
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


@router.get("/{slug}", response_model=ApiResp[ArticleDetail])
@respond
async def get_article_detail(
    slug: str, db: AsyncSession = Depends(get_session)
) -> ArticleDetail:
    return await get_article(db, slug)
