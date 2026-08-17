from typing import Any, cast

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.err import BizError, CommonErr
from app.db.models import Article, ArticleComment, ArticleLike, ArticleTag, Profile, Tag
from app.db.repo import get_or_raise
from app.modules.articles.errors import ArticleErr
from app.modules.articles.schemas import (
    ArticleCategory,
    ArticleCommentOut,
    ArticleDetail,
    ArticleListItem,
)
from app.modules.auth.schemas import ProfileInfo

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


async def _bump_article_count(
    db: AsyncSession, article_id: int, column: str, delta: int
) -> None:
    """原子回填计数列（SET col = col ± N），防并发丢更新。"""
    await db.execute(
        update(Article)
        .where(Article.id == article_id)
        .values({column: getattr(Article, column) + delta})
    )


async def toggle_article_like(
    db: AsyncSession, slug: str, user_id: int
) -> dict[str, Any]:
    article = await get_or_raise(db, Article, ArticleErr.NOT_FOUND, Article.slug == slug)
    existing = (
        await db.execute(
            select(ArticleLike).where(
                ArticleLike.article_id == article.id,
                ArticleLike.user_id == user_id,
            )
        )
    ).scalars().first()
    if existing:
        await db.delete(existing)
        await db.flush()
        await _bump_article_count(db, article.id, "likes", -1)
        liked = False
    else:
        db.add(ArticleLike(article_id=article.id, user_id=user_id))
        await db.flush()
        await _bump_article_count(db, article.id, "likes", 1)
        liked = True
    like_count = (
        await db.execute(
            select(func.count()).select_from(ArticleLike).where(
                ArticleLike.article_id == article.id
            )
        )
    ).scalar_one()
    return {"liked": liked, "like_count": like_count}


async def create_article_comment(
    db: AsyncSession, slug: str, user_id: int, content: str, parent_id: int | None = None
) -> ArticleComment:
    article = await get_or_raise(db, Article, ArticleErr.NOT_FOUND, Article.slug == slug)
    if parent_id is not None:
        parent = await get_or_raise(
            db, ArticleComment, ArticleErr.COMMENT_NOT_FOUND, ArticleComment.id == parent_id
        )
        if parent.article_id != article.id:
            raise BizError(ArticleErr.COMMENT_PARENT_MISMATCH)
    comment = ArticleComment(
        article_id=article.id, user_id=user_id, content=content, parent_id=parent_id
    )
    db.add(comment)
    await db.flush()
    await _bump_article_count(db, article.id, "comments", 1)
    return comment


async def _get_author_profiles(
    db: AsyncSession, user_ids: set[int]
) -> dict[int, ProfileInfo | None]:
    """批量查询多个评论作者的 Profile，避免逐条查询的 N+1（照 blog 模块范式，在 articles 模块内自建）。"""
    if not user_ids:
        return {}
    rows = (
        (
            await db.execute(select(Profile).where(Profile.user_id.in_(user_ids)))
        )
        .scalars()
        .all()
    )
    return {p.user_id: ProfileInfo.model_validate(p) for p in rows}


async def list_article_comments(db: AsyncSession, slug: str) -> list[ArticleCommentOut]:
    article = await get_or_raise(db, Article, ArticleErr.NOT_FOUND, Article.slug == slug)
    rows = (
        await db.execute(
            select(ArticleComment)
            .where(ArticleComment.article_id == article.id)
            .options(selectinload(ArticleComment.user))
            .order_by(ArticleComment.created_at.asc())
        )
    ).scalars().all()
    user_ids = {c.user_id for c in rows}
    profiles = await _get_author_profiles(db, user_ids)
    return [
        ArticleCommentOut.model_validate(c).model_copy(
            update={"profile": profiles.get(c.user_id)}
        )
        for c in rows
    ]


async def delete_article_comment(
    db: AsyncSession, comment_id: int, user_id: int
) -> None:
    comment = await get_or_raise(
        db, ArticleComment, ArticleErr.COMMENT_NOT_FOUND, ArticleComment.id == comment_id
    )
    if comment.user_id != user_id:
        raise BizError(CommonErr.FORBIDDEN)
    await db.delete(comment)
    await _bump_article_count(db, comment.article_id, "comments", -1)
