from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Article
from app.db.repo import get_or_raise
from app.modules.articles.errors import ArticleErr
from app.modules.articles.schemas import (
    ArticleCategory,
    ArticleDetail,
    ArticleListItem,
)

ARTICLE_CATEGORY_NAMES: dict[str, str] = {
    "announcement": "公告",
    "architecture": "架构",
    "security": "安全",
    "engineering": "工程",
    "ai": "AI",
    "community": "社区",
    "culture": "文化",
    "news": "科技新闻",
    "science": "科普相关",
}

# 默认阅读速度：中文约 300 字/分钟
READING_SPEED_CPS = 300


def estimate_reading_time(content: str) -> int:
    """按中文字符数估算阅读分钟数（不足 1 分钟计 1；空内容为 0）。"""
    text_length = len(content)
    if not text_length:
        return 0
    return max(1, round(text_length / READING_SPEED_CPS))


async def list_articles(
    db: AsyncSession, page: int = 1, page_size: int = 50
) -> dict[str, Any]:
    total = (await db.execute(select(func.count()).select_from(Article))).scalar_one()
    stmt = (
        select(Article)
        .order_by(Article.published.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = (await db.execute(stmt)).scalars().all()
    return {
        "items": [ArticleListItem.model_validate(a) for a in items],
        "total": total,
    }


async def get_article(db: AsyncSession, slug: str) -> ArticleDetail:
    article = await get_or_raise(
        db, Article, ArticleErr.NOT_FOUND, Article.slug == slug
    )
    detail = ArticleDetail.model_validate(article)
    detail.reading_time = estimate_reading_time(article.content)
    return detail


async def list_categories(db: AsyncSession) -> list[ArticleCategory]:
    rows = (
        await db.execute(
            select(Article.category, func.count(Article.id)).group_by(Article.category)
        )
    ).all()
    return [
        ArticleCategory(
            # Article.category 为非空列，聚合行推断为 str|None，这里显式收窄
            slug=cast("str", slug),
            name=ARTICLE_CATEGORY_NAMES.get(cast("str", slug), cast("str", slug)),
            article_count=count,
        )
        for slug, count in rows
    ]
