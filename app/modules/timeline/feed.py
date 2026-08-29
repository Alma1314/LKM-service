"""时间线数据源层：把异构内容实体归一为统一 FeedItem。

每个源实现 ``fetch_items(db, author_ids, board_ids, before_time, before_id, limit)``，
按可见时间降序返回当页候选（已按 cursor 下滤）。排序合并/游标推进在 service 统一做。

* 可见时间（feed_time）：优先 ``published``/``published_at``，否则 ``created_at``——
  即"内容对外可见的时间"，作为跨源排序锚点。
* 可见性过滤（各源 SQL WHERE）：Article 仅 published、Column 仅 PUBLISHED、
  QA 仅 open/accepted、Project 仅 active、ForumPost 全可见。
* 作者名：逐源批查 ``User.profile.nickname`` 兜底 ``username``；Article 无作者外键，
  ``author_id=None``、``author_name=publisher``。
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Article,
    ColumnPost,
    ColumnPostStatus,
    ContentItem,
    ForumPost,
    Project,
    QAQuestion,
    User,
)
from app.modules.content.models import ContentStatus
from app.modules.timeline.schemas import FeedItem

_PREVIEW_LEN = 150


def _preview_of(text: str | None, limit: int = _PREVIEW_LEN) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


async def _author_map(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    result = await db.execute(
        select(User).where(User.id.in_(user_ids)).options(selectinload(User.profile))
    )
    out: dict[int, str] = {}
    for u in result.scalars().all():
        if u.profile and u.profile.nickname:
            out[u.id] = u.profile.nickname
        else:
            out[u.id] = u.username
    return out


def _before_conds(
    col_time: Any,
    model_id: Any,
    before_time: datetime | None,
    before_id: int,
) -> list[Any]:
    """(created_at, id) 游标下滤条件。before_time 为 None 时返回空（首页）。"""
    if before_time is None:
        return []
    return [
        # created_at < before_time OR (created_at == before_time AND id < before_id)
        (col_time < before_time) | ((col_time == before_time) & (model_id < before_id))
    ]


# ---------------------------------------------------------------------------
# Forum
# ---------------------------------------------------------------------------


async def _fetch_forum(
    db: AsyncSession,
    author_ids: set[int] | None,
    board_ids: set[int] | None,
    before_time: datetime | None,
    before_id: int,
    limit: int,
) -> list[FeedItem]:
    conditions: list[Any] = []
    # follow 模式：关注作者 或 关注版块；hot 模式不限制
    if author_ids is not None and board_ids is not None:
        conditions.append(
            ForumPost.author_id.in_(author_ids) | ForumPost.board_id.in_(board_ids)
        )
    if before_time is not None:
        conditions.extend(
            _before_conds(ForumPost.created_at, ForumPost.id, before_time, before_id)
        )
    stmt = select(ForumPost)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(ForumPost.created_at.desc(), ForumPost.id.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    names = await _author_map(db, {r.author_id for r in rows})
    return [
        FeedItem(
            item_type="forum",
            id=r.id,
            author_id=r.author_id,
            author_name=names.get(r.author_id, ""),
            title=r.title,
            content_preview=_preview_of(r.excerpt or r.content),
            created_at=r.created_at,
            sort_score=_forum_heat(r),
            board_id=r.board_id,
            url=f"/forum/posts/{r.id}",
        )
        for r in rows
    ]


def _forum_heat(r: Any) -> float:
    """论坛热度：读写阅赞评藏加权。"""
    return math.log1p(
        r.view_count + r.like_count * 2 + r.comment_count * 3 + r.bookmark_count * 4
    )


# ---------------------------------------------------------------------------
# Article（无作者外键：仅 hot，follow 时不参与）
# ---------------------------------------------------------------------------


async def _fetch_article(
    db: AsyncSession,
    author_ids: set[int] | None,
    board_ids: set[int] | None,
    before_time: datetime | None,
    before_id: int,
    limit: int,
) -> list[FeedItem]:
    conditions: list[Any] = [Article.status == "published"]
    if before_time is not None:
        conditions.extend(
            _before_conds(Article.created_at, Article.id, before_time, before_id)
        )
    stmt = (
        select(Article)
        .where(*conditions)
        .order_by(Article.created_at.desc(), Article.id.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        FeedItem(
            item_type="article",
            id=r.id,
            author_id=None,
            author_name=r.publisher or "",
            title=r.title,
            content_preview=_preview_of(r.description or r.content),
            created_at=r.created_at,
            sort_score=_article_heat(r),
            board_id=None,
            url=f"/articles/{r.slug}",
        )
        for r in rows
    ]


def _article_heat(r: Article) -> float:
    return math.log1p(r.views + r.likes * 2 + r.comments * 3 + r.bookmarks * 4)


# ---------------------------------------------------------------------------
# Column
# ---------------------------------------------------------------------------


async def _fetch_column(
    db: AsyncSession,
    author_ids: set[int] | None,
    board_ids: set[int] | None,
    before_time: datetime | None,
    before_id: int,
    limit: int,
) -> list[FeedItem]:
    conditions: list[Any] = [ColumnPost.status == ColumnPostStatus.PUBLISHED]
    if author_ids is not None:
        conditions.append(ColumnPost.author_id.in_(author_ids))
    if before_time is not None:
        conditions.extend(
            _before_conds(ColumnPost.created_at, ColumnPost.id, before_time, before_id)
        )
    stmt = (
        select(ColumnPost)
        .where(*conditions)
        .order_by(ColumnPost.created_at.desc(), ColumnPost.id.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    names = await _author_map(db, {r.author_id for r in rows})
    return [
        FeedItem(
            item_type="column",
            id=r.id,
            author_id=r.author_id,
            author_name=names.get(r.author_id, ""),
            title=r.title,
            content_preview=_preview_of(r.summary or r.content),
            created_at=r.created_at,
            sort_score=_column_heat(r),
            board_id=None,
            url=f"/columns/{r.column_id}/posts/{r.id}",
        )
        for r in rows
    ]


def _column_heat(r: ColumnPost) -> float:
    return math.log1p(r.view_count + r.like_count * 2 + r.comment_count * 3)


# ---------------------------------------------------------------------------
# QA
# ---------------------------------------------------------------------------


async def _fetch_qa(
    db: AsyncSession,
    author_ids: set[int] | None,
    board_ids: set[int] | None,
    before_time: datetime | None,
    before_id: int,
    limit: int,
) -> list[FeedItem]:
    conditions: list[Any] = [QAQuestion.status.in_(["open", "accepted"])]
    if author_ids is not None:
        conditions.append(QAQuestion.author_id.in_(author_ids))
    if before_time is not None:
        conditions.extend(
            _before_conds(QAQuestion.created_at, QAQuestion.id, before_time, before_id)
        )
    stmt = (
        select(QAQuestion)
        .where(*conditions)
        .order_by(QAQuestion.created_at.desc(), QAQuestion.id.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    names = await _author_map(db, {r.author_id for r in rows})
    return [
        FeedItem(
            item_type="qa",
            id=r.id,
            author_id=r.author_id,
            author_name=names.get(r.author_id, ""),
            title=r.title,
            content_preview=_preview_of(r.content or r.situation),
            created_at=r.created_at,
            sort_score=0.0,
            board_id=None,
            url=f"/qa/{r.id}",
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


async def _fetch_project(
    db: AsyncSession,
    author_ids: set[int] | None,
    board_ids: set[int] | None,
    before_time: datetime | None,
    before_id: int,
    limit: int,
) -> list[FeedItem]:
    conditions: list[Any] = [Project.status == "active"]
    if author_ids is not None:
        conditions.append(Project.applicant_id.in_(author_ids))
    if before_time is not None:
        conditions.extend(
            _before_conds(Project.created_at, Project.id, before_time, before_id)
        )
    stmt = (
        select(Project)
        .where(*conditions)
        .order_by(Project.created_at.desc(), Project.id.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    names = await _author_map(db, {r.applicant_id for r in rows})
    return [
        FeedItem(
            item_type="project",
            id=r.id,
            author_id=r.applicant_id,
            author_name=names.get(r.applicant_id, ""),
            title=r.title,
            content_preview=_preview_of(r.summary or r.description),
            created_at=r.created_at,
            sort_score=0.0,
            board_id=None,
            url=f"/projects/{r.id}",
        )
        for r in rows
    ]


async def _fetch_blog(
    db: AsyncSession,
    author_ids: set[int] | None,
    board_ids: set[int] | None,
    before_time: datetime | None,
    before_id: int,
    limit: int,
) -> list[FeedItem]:
    """博客发布产物（统一内容表中 content_type==blog_post）。

    blog_post 只落 content_items、无独立分表源（forum/article/column/qa 走各自旧表），
    故单独从 content_items 补源，避免与其他源重复。
    """
    conditions: list[Any] = [
        ContentItem.content_type == "blog_post",
        ContentItem.status == ContentStatus.PUBLISHED,
    ]
    if author_ids is not None:
        conditions.append(ContentItem.author_id.in_(author_ids))
    if before_time is not None:
        conditions.extend(
            _before_conds(ContentItem.created_at, ContentItem.id, before_time, before_id)
        )
    stmt = (
        select(ContentItem)
        .where(*conditions)
        .order_by(ContentItem.created_at.desc(), ContentItem.id.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    names = await _author_map(db, {r.author_id for r in rows if r.author_id})
    return [
        FeedItem(
            item_type="blog",
            id=r.id,
            author_id=r.author_id,
            author_name=names.get(r.author_id or -1, r.publisher or ""),
            title=r.title,
            content_preview=_preview_of(r.excerpt or r.content),
            created_at=r.created_at,
            sort_score=0.0,
            board_id=r.board_id,
            url=f"/blog/posts/{r.slug}" if r.slug else f"/forum/boards/{r.board_id}",
        )
        for r in rows
    ]


SOURCES: dict[str, Any] = {
    "forum": _fetch_forum,
    "article": _fetch_article,
    "column": _fetch_column,
    "qa": _fetch_qa,
    "project": _fetch_project,
    "blog": _fetch_blog,
}

# follow 模式参与的源（按关注作者过滤；forum 额外按关注版块）
FOLLOW_SOURCES: list[str] = ["forum", "column", "qa", "project", "blog"]
# hot 模式参与的源（全站、不按关注过滤、包含无作者外键的 Article）
HOT_SOURCES: list[str] = ["forum", "article", "column", "qa", "project", "blog"]
