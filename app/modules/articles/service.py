from typing import Any, cast

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Article, ArticleTag, Tag
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
    detail.tags = [t.name for t in (article.tags or [])]
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


def _fts_search_stmt(q: str):
    """按驱动返回 sqlalchemy 查询表达式，供 search_articles 使用。"""
    if settings.db_driver == "postgresql":
        # PostgreSQL 真 FTS：simple 分词（中文分词效果已知受限，属 spec 取舍）
        vector = func.to_tsvector(
            "simple",
            func.concat_ws(
                " ", Article.title, Article.description, Article.content
            ),
        )
        query = func.plainto_tsquery("simple", q)
        return vector.match(query), func.ts_rank(vector, query)
    # SQLite 降级：ilike 通配（跨驱动安全）
    pattern = f"%{q}%"
    cond = or_(
        Article.title.ilike(pattern),
        Article.description.ilike(pattern),
        Article.content.ilike(pattern),
    )
    return cond, None


async def search_articles(
    db: AsyncSession, q: str, page: int = 1, page_size: int = 50
) -> dict[str, Any]:
    cond, rank = _fts_search_stmt(q)
    count_stmt = select(func.count()).select_from(Article).where(cond)
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = select(Article).where(cond)
    if rank is not None:
        stmt = stmt.order_by(rank.desc())
    else:
        stmt = stmt.order_by(Article.published.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(stmt)).scalars().all()
    return {
        "items": [ArticleListItem.model_validate(a) for a in items],
        "total": total,
    }


async def list_tags(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(Tag.name, func.count(ArticleTag.article_id))
            .join(ArticleTag, ArticleTag.tag_id == Tag.id)
            .group_by(Tag.id)
        )
    ).all()
    return [
        {"name": name, "article_count": count} for name, count in rows
    ]


async def get_about() -> dict[str, str]:
    return {
        "title": "LKM 官方博客",
        "description": "LKM 团队博客，发布技术文章与官方资讯。",
        "maintainer": "LKM",
    }
