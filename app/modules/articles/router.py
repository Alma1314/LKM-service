from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.session import get_read_session, get_session
from app.modules.articles.schemas import (
    AboutItem,
    ArticleCategory,
    ArticleCommentCreate,
    ArticleCommentOut,
    ArticleCreate,
    ArticleDetail,
    ArticleLikeStatus,
    ArticleListItem,
    ArticleUpdate,
    CategoryCreate,
    CategoryOut,
    ReviewArticleRequest,
    TagItem,
)
from app.modules.articles.service import (
    assert_super_admin,
    create_article_comment,
    create_article_ex,
    create_category_ex,
    delete_article_comment,
    delete_category_ex,
    get_about,
    get_article,
    hard_delete_article,
    list_article_comments,
    list_articles,
    list_categories,
    list_tags,
    review_article,
    search_articles,
    soft_delete_article,
    toggle_article_like,
    update_article_ex,
    update_category_ex,
)
from app.modules.auth.deps import CurrentUser, get_current_user
from app.modules.common import ApiResp, ListData, PageData

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=ApiResp[PageData[ArticleListItem]])
@respond
async def get_articles(
    db: AsyncSession = Depends(get_read_session),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    return await list_articles(db, page=page, page_size=page_size)


@router.get("/categories", response_model=ApiResp[ListData[ArticleCategory]])
@respond
async def get_article_categories(
    db: AsyncSession = Depends(get_read_session),
) -> dict[str, Any]:
    return {"items": await list_categories(db)}


@router.get("/tags", response_model=ApiResp[ListData[TagItem]])
@respond
async def get_article_tags(
    db: AsyncSession = Depends(get_read_session),
) -> dict[str, Any]:
    return {"items": await list_tags(db)}


@router.get("/search", response_model=ApiResp[PageData[ArticleListItem]])
@respond
async def search_articles_endpoint(
    q: str = Query(..., min_length=1, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_read_session),
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
    db: AsyncSession = Depends(get_read_session),
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
    slug: str, db: AsyncSession = Depends(get_read_session)
) -> ArticleDetail:
    return await get_article(db, slug)


# ——————— 写端点（均需 super_admin） ———————


@router.post("", response_model=ApiResp[ArticleDetail])
@respond
async def create_article(
    info: ArticleCreate,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ArticleDetail:
    assert_super_admin(cur)
    return await create_article_ex(db, info)


@router.patch("/{slug}", response_model=ApiResp[ArticleDetail])
@respond
async def patch_article(
    slug: str,
    patch: ArticleUpdate,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ArticleDetail:
    assert_super_admin(cur)
    return await update_article_ex(db, slug, patch, is_super=True)


@router.delete("/{slug}", response_model=ApiResp[dict[str, bool]])
@respond
async def soft_delete(
    slug: str,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    assert_super_admin(cur)
    await soft_delete_article(db, slug)
    return {"ok": True}


@router.delete("/{slug}/hard", response_model=ApiResp[dict[str, bool]])
@respond
async def hard_delete(
    slug: str,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    assert_super_admin(cur)
    await hard_delete_article(db, slug)
    return {"ok": True}


@router.post("/{slug}/review", response_model=ApiResp[ArticleDetail])
@respond
async def review_article_endpoint(
    slug: str,
    body: ReviewArticleRequest,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ArticleDetail:
    assert_super_admin(cur)
    return await review_article(db, slug, body.approve)


@router.post("/categories", response_model=ApiResp[CategoryOut])
@respond
async def add_category(
    info: CategoryCreate,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> CategoryOut:
    assert_super_admin(cur)
    return await create_category_ex(db, info)


@router.patch("/categories/{category_id}", response_model=ApiResp[CategoryOut])
@respond
async def update_category(
    category_id: int,
    info: CategoryCreate,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> CategoryOut:
    assert_super_admin(cur)
    return await update_category_ex(db, category_id, info)


@router.delete("/categories/{category_id}", response_model=ApiResp[dict[str, bool]])
@respond
async def delete_category(
    category_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    assert_super_admin(cur)
    await delete_category_ex(db, category_id)
    return {"ok": True}
