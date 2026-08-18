from datetime import datetime
from typing import Any, cast

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.dialects import sqlite as sq
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.err import BizError, CommonErr
from app.db.models import (
    Article,
    ArticleComment,
    ArticleLike,
    ArticleTag,
    Profile,
    Tag,
    now_iso,
)
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


async def _sync_article_tags(
    db: AsyncSession, article_id: int, names: list[str]
) -> None:
    """按 name upsert Tag 并关联 ArticleTag（幂等，批量 O(log N)，保序去重）。

    相比逐 tag 查/插的旧实现：tag 存在性 1 次批量查 + 缺失 tag 一次批量插（on
    conflict do nothing）+ 一次批量回查，关联查/插各一次，全程固定次数往返且
    保持输入 name 顺序（避免 set 迭代造成的顺序随机，修复预存的标签顺序 flaky）。
    """
    # 去空 + 保首现顺序去重（勿用 set：顺序非确定会打乱 tags 返回序）
    ordered: list[str] = []
    seen: set[str] = set()
    for n in names:
        if n and n not in seen:
            ordered.append(n)
            seen.add(n)
    if not ordered:
        return

    # 1) 批量查已存在 tag（name -> id）
    rows = (
        await db.execute(select(Tag.id, Tag.name).where(Tag.name.in_(ordered)))
    ).all()
    name_to_id = {name: tag_id for tag_id, name in rows}

    # 2) 缺失的 tag 一批插；再批量回查拿全量 id（跨驱动用 on_conflict 免唯一冲突）
    missing = [n for n in ordered if n not in name_to_id]
    if missing:
        dialect_insert = pg.insert if settings.db_driver == "postgresql" else sq.insert
        await db.execute(
            dialect_insert(Tag)
            .values([{"name": n} for n in missing])
            .on_conflict_do_nothing(index_elements=["name"])
        )
        await db.flush()
        rows = (
            await db.execute(select(Tag.id, Tag.name).where(Tag.name.in_(ordered)))
        ).all()
        name_to_id = {name: tag_id for tag_id, name in rows}

    # 3) 批量查该文章的既有关联，只补缺失
    tag_ids = [name_to_id[n] for n in ordered]
    existing = (
        (
            await db.execute(
                select(ArticleTag.tag_id).where(
                    ArticleTag.article_id == article_id,
                    ArticleTag.tag_id.in_(tag_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    existing_set = set(existing)
    for n in ordered:
        tag_id = name_to_id[n]
        if tag_id not in existing_set:
            db.add(ArticleTag(article_id=article_id, tag_id=tag_id))


async def create_article(
    db: AsyncSession,
    slug: str,
    title: str,
    category: str,
    content: str,
    published: datetime | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> Article:
    # 幂等：同 slug 已存在则更新（重发 = 更新）
    existing = (
        (await db.execute(select(Article).where(Article.slug == slug)))
        .scalars()
        .first()
    )
    if existing:
        existing.title = title
        existing.category = category
        existing.content = content
        if description is not None:
            existing.description = description
        await _sync_article_tags(db, existing.id, tags or [])
        existing.updated_at = now_iso()
        await db.flush()
        return existing
    article = Article(
        slug=slug,
        title=title,
        category=category,
        content=content,
        published=published or now_iso(),
        description=description,
    )
    db.add(article)
    await db.flush()
    if tags:
        await _sync_article_tags(db, article.id, tags)
    return article


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
    # article.tags 是 Tag 对象列表，ArticleDetail.tags 期望字符串 list。
    # 不能直接 model_validate(article)：from_attributes 会读 article.tags 得到
    # Tag 对象而校验失败，故从标量属性构造 dict，tags 单独 map 成字符串。
    detail = ArticleDetail(
        **{
            k: v
            for k, v in article.__dict__.items()
            if k in ArticleDetail.model_fields and k != "tags"
        },
        tags=[t.name for t in (article.tags or [])],
    )
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


def _fts_search_stmt(q: str) -> tuple[Any, Any]:
    """按驱动返回 sqlalchemy 查询表达式，供 search_articles 使用。"""
    if settings.db_driver == "postgresql":
        # PostgreSQL 真 FTS：simple 分词（中文分词效果已知受限，属 spec 取舍）
        vector = func.to_tsvector(
            "simple",
            func.concat_ws(" ", Article.title, Article.description, Article.content),
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
    return [{"name": name, "article_count": count} for name, count in rows]


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
    article = await get_or_raise(
        db, Article, ArticleErr.NOT_FOUND, Article.slug == slug
    )
    existing = (
        (
            await db.execute(
                select(ArticleLike).where(
                    ArticleLike.article_id == article.id,
                    ArticleLike.user_id == user_id,
                )
            )
        )
        .scalars()
        .first()
    )
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
            select(func.count())
            .select_from(ArticleLike)
            .where(ArticleLike.article_id == article.id)
        )
    ).scalar_one()
    return {"liked": liked, "like_count": like_count}


async def create_article_comment(
    db: AsyncSession,
    slug: str,
    user_id: int,
    content: str,
    parent_id: int | None = None,
) -> ArticleComment:
    article = await get_or_raise(
        db, Article, ArticleErr.NOT_FOUND, Article.slug == slug
    )
    if parent_id is not None:
        parent = await get_or_raise(
            db,
            ArticleComment,
            ArticleErr.COMMENT_NOT_FOUND,
            ArticleComment.id == parent_id,
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
        (await db.execute(select(Profile).where(Profile.user_id.in_(user_ids))))
        .scalars()
        .all()
    )
    return {p.user_id: ProfileInfo.model_validate(p) for p in rows}


async def list_article_comments(db: AsyncSession, slug: str) -> list[ArticleCommentOut]:
    article = await get_or_raise(
        db, Article, ArticleErr.NOT_FOUND, Article.slug == slug
    )
    rows = (
        (
            await db.execute(
                select(ArticleComment)
                .where(ArticleComment.article_id == article.id)
                .options(selectinload(ArticleComment.user))
                .order_by(ArticleComment.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
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
        db,
        ArticleComment,
        ArticleErr.COMMENT_NOT_FOUND,
        ArticleComment.id == comment_id,
    )
    if comment.user_id != user_id:
        raise BizError(CommonErr.FORBIDDEN)
    await db.delete(comment)
    await _bump_article_count(db, comment.article_id, "comments", -1)
