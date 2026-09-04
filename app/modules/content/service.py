import datetime as _dt
import json
import re

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import (
    bump_collection_version,
    cached_read,
    collection_version,
    make_key,
)
from app.core.common import PageData, paginate_offset, paginate_pages
from app.core.err import BizError
from app.core.metrics import post_created_total
from app.db.repo import get_or_raise
from app.modules.auth.models import User
from app.modules.content.errors import ContentErr
from app.modules.content.models import (
    Board,
    Column,
    ContentComment,
    ContentItem,
    ContentLike,
    ContentStatus,
    ContentType,
)
from app.modules.content.schemas import (
    ContentCommentCreate,
    ContentCommentInfo,
    ContentItemCreate,
    ContentItemInfo,
)
from app.modules.points.rules import enqueue_points_event

READING_WPM = 300  # 每 300 字约 1 分钟阅读时间


def _author_name(user: User | None) -> str:
    if user is None:
        return ""
    if user.profile and user.profile.nickname:
        return user.profile.nickname
    return user.username


def _excerpt_of(content: str, limit: int = 150) -> str:
    text = re.sub(r"<[^>]+>", " ", content)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _reading_time(content: str) -> int:
    if not content:
        return 0
    return max(1, len(content) // READING_WPM)


def _item_to_schema(
    item: ContentItem,
    author_name: str,
    column_title: str | None = None,
) -> ContentItemInfo:
    return ContentItemInfo.model_validate(item).model_copy(
        update={
            "author_name": author_name,
            "column_title": column_title or "",
            "reading_time": _reading_time(item.content),
        }
    )


def _comment_to_schema(c: ContentComment, author_name: str) -> ContentCommentInfo:
    return ContentCommentInfo.model_validate(c).model_copy(
        update={"author_name": author_name}
    )


async def _author_map(db: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    result = await db.execute(
        select(User)
        .where(User.id.in_(set(user_ids)))
        .options(selectinload(User.profile))
    )
    users = result.scalars().all()
    return {u.id: _author_name(u) for u in users}


async def _column_title_map(db: AsyncSession, column_ids: list[int]) -> dict[int, str]:
    if not column_ids:
        return {}
    result = await db.execute(select(Column).where(Column.id.in_(set(column_ids))))
    columns = result.scalars().all()
    return {c.id: c.title for c in columns}


async def list_items(
    db: AsyncSession,
    page: int = 1,
    limit: int = 20,
    board_id: int | None = None,
    content_type: str | None = None,
) -> PageData[ContentItemInfo]:
    base = select(ContentItem).where(ContentItem.status == ContentStatus.PUBLISHED)
    if board_id:
        base = base.where(ContentItem.board_id == board_id)
    if content_type:
        base = base.where(ContentItem.content_type == content_type)

    # 计数走短 TTL 缓存 + content 集合版本号：任何增删 ContentItem 的行都会
    # bump_content_version() 递增集合版本，使旧(count)键立即失效，杜绝脏计数。
    async def _count() -> int:
        count_stmt = select(func.count()).select_from(base.subquery())
        total: int | None = await db.scalar(count_stmt)
        return total or 0

    ver = await collection_version("content")
    total_count = await cached_read(
        make_key("content:list:total", ver, board_id or "", content_type or ""),
        60,
        _count,
    )

    stmt = (
        base.order_by(ContentItem.is_pinned.desc(), ContentItem.id.desc())
        .offset(paginate_offset(page, limit))
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    author_ids = [i.author_id for i in items if i.author_id]
    column_ids = [i.column_id for i in items if i.column_id]
    names = await _author_map(db, author_ids)
    cols = await _column_title_map(db, column_ids)
    out = [
        _item_to_schema(
            i,
            names.get(i.author_id or -1, "") if i.author_id else (i.publisher or ""),
            cols.get(i.column_id or -1) if i.column_id else None,
        )
        for i in items
    ]
    return PageData(
        items=out,
        total=total_count,
        page=page,
        pages=paginate_pages(total_count, limit),
    )


# 视图计数写会话缝：GraphQL 用只读会话不能写，故 bump 自建独立写会话。
# 默认 new_session()；测试可替换为 conftest 内存会话以断言落库（仿 blog git _session_factory）。
async def _new_write_session() -> AsyncSession:
    from app.db.session import new_session

    return await new_session()


async def bump_item_view(item_id: int) -> None:
    """原子地给内容项 view_count +1（供公开详情阅读计数增长路径）。

    前端详情走 GraphQL ``contentItem``，此前 get_item 恒 bump_view=False 且 REST 无详情
    端点，导致 view_count 无增长路径。GraphQL 用只读会话（读后显式 rollback），不能在其上写，
    故自建独立写会话原子 UPDATE 并 commit，原子 UPDATE 避免并发 read-modify-write 丢计数。
    """
    dbw = await _new_write_session()
    try:
        await dbw.execute(
            sa_update(ContentItem)
            .where(ContentItem.id == item_id)
            .values(view_count=ContentItem.view_count + 1)
        )
        await dbw.commit()
    finally:
        await dbw.close()


async def get_item(
    db: AsyncSession, item_id: int, bump_view: bool = False
) -> ContentItemInfo:
    item = await get_or_raise(
        db, ContentItem, ContentErr.CONTENT_NOT_FOUND, ContentItem.id == item_id
    )
    if bump_view:
        item.view_count += 1
        await db.flush()

    author_name = ""
    if item.author_id:
        names = await _author_map(db, [item.author_id])
        author_name = names.get(item.author_id, "")
    else:
        author_name = item.publisher or ""
    column_title = ""
    if item.column_id:
        cols = await _column_title_map(db, [item.column_id])
        column_title = cols.get(item.column_id, "")
    return _item_to_schema(item, author_name, column_title or None)


async def get_item_by_slug(db: AsyncSession, slug: str) -> ContentItemInfo:
    item = await get_or_raise(
        db, ContentItem, ContentErr.CONTENT_NOT_FOUND, ContentItem.slug == slug
    )
    author_name = ""
    if item.author_id:
        names = await _author_map(db, [item.author_id])
        author_name = names.get(item.author_id, "")
    else:
        author_name = item.publisher or ""
    column_title = ""
    if item.column_id:
        cols = await _column_title_map(db, [item.column_id])
        column_title = cols.get(item.column_id, "")
    return _item_to_schema(item, author_name, column_title or None)


async def _require_unique_slug(db: AsyncSession, slug: str | None) -> None:
    if not slug:
        return
    # 应用层唯一校验（兼容 SQLite 多 NULL unique 差异；Postgres 走部分唯一索引）
    existing = (
        (
            await db.execute(
                select(ContentItem.id).where(ContentItem.slug == slug).limit(1)
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        raise BizError(ContentErr.SLUG_TAKEN)


async def create_item(
    db: AsyncSession,
    author_id: int,
    info: ContentItemCreate,
) -> ContentItemInfo:
    # 发言准入：板块存在 / 认证 / 日限发（仅社区用户写作体裁）
    if info.content_type in (
        ContentType.DISCUSSION,
        ContentType.COLUMN_POST,
        ContentType.BLOG_POST,
        ContentType.QA,
    ):
        from app.modules.content.boards.service import check_post_allowed

        await check_post_allowed(db, info.board_id, author_id)

    await get_or_raise(db, Board, ContentErr.BOARD_NOT_FOUND, Board.id == info.board_id)

    if info.content_type == ContentType.COLUMN_POST:
        if not info.column_id:
            raise BizError(ContentErr.COLUMN_NOT_FOUND)
        await get_or_raise(
            db, Column, ContentErr.COLUMN_NOT_FOUND, Column.id == info.column_id
        )

    if info.content_type == ContentType.ARTICLE:
        await _require_unique_slug(db, info.slug)

    status = info.status
    if info.content_type == ContentType.DISCUSSION:
        status = ContentStatus.PUBLISHED  # 讨论帖无审稿，发即公开

    item = ContentItem(
        content_type=info.content_type,
        board_id=info.board_id,
        author_id=author_id,
        publisher=info.publisher,
        department=info.department,
        column_id=(
            info.column_id if info.content_type == ContentType.COLUMN_POST else None
        ),
        qa_question_id=(
            info.qa_question_id if info.content_type == ContentType.QA else None
        ),
        slug=info.slug if info.content_type == ContentType.ARTICLE else None,
        title=info.title,
        excerpt=_excerpt_of(info.content),
        content=info.content,
        summary=info.summary,
        cover=info.cover,
        keywords=json.dumps(info.keywords, ensure_ascii=False)
        if info.keywords
        else None,
        tags=json.dumps(info.tags, ensure_ascii=False),
        status=status,
        is_pinned=info.is_pinned,
        is_featured=info.is_featured,
        published_at=None,
    )
    db.add(item)
    await db.flush()

    # 积分事件（异步计分，不阻塞 200）
    await enqueue_points_event(db, author_id, "post", f"item:{item.id}")
    await bump_collection_version("content")

    # M0.5.2 业务指标：本方法统一写 content_items（discussion/column_post/
    # article/blog_post/qa），谓成功落库即全内容 dumps 的“发帖/新版产出”。
    post_created_total.labels(item.content_type).inc()

    names = await _author_map(db, [author_id])
    return _item_to_schema(item, names.get(author_id, ""))


async def delete_item(
    db: AsyncSession,
    item_id: int,
    current_user_id: int,
    as_admin: bool = False,
) -> int:
    """删除统一内容项并返回作者 id（admin 代删时可能无作者返回 0）。"""
    item = await get_or_raise(
        db, ContentItem, ContentErr.CONTENT_NOT_FOUND, ContentItem.id == item_id
    )
    author_id = item.author_id or -1
    await db.delete(item)
    await db.flush()
    await bump_collection_version("content")
    return author_id


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


async def like_item(db: AsyncSession, item_id: int, user_id: int) -> int:
    item = await get_or_raise(
        db, ContentItem, ContentErr.CONTENT_NOT_FOUND, ContentItem.id == item_id
    )
    existing = (
        (
            await db.execute(
                select(ContentLike).where(
                    ContentLike.content_id == item_id,
                    ContentLike.user_id == user_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return item.like_count

    db.add(ContentLike(content_id=item_id, user_id=user_id))
    item.like_count += 1
    await db.flush()
    await enqueue_points_event(db, user_id, "like", f"item:{item_id}")
    return item.like_count


async def unlike_item(db: AsyncSession, item_id: int, user_id: int) -> int:
    item = await get_or_raise(
        db, ContentItem, ContentErr.CONTENT_NOT_FOUND, ContentItem.id == item_id
    )
    existing = (
        (
            await db.execute(
                select(ContentLike).where(
                    ContentLike.content_id == item_id,
                    ContentLike.user_id == user_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is None:
        return item.like_count
    await db.delete(existing)
    item.like_count = max(0, item.like_count - 1)
    await db.flush()
    return item.like_count


async def list_comments(
    db: AsyncSession,
    item_id: int,
    page: int = 1,
    limit: int = 20,
) -> PageData[ContentCommentInfo]:
    await get_or_raise(
        db, ContentItem, ContentErr.CONTENT_NOT_FOUND, ContentItem.id == item_id
    )
    total = (
        await db.scalar(
            select(func.count(ContentComment.id)).where(
                ContentComment.content_id == item_id
            )
        )
        or 0
    )
    stmt = (
        select(ContentComment)
        .where(ContentComment.content_id == item_id)
        .order_by(ContentComment.floor_number.asc())
        .offset(paginate_offset(page, limit))
        .limit(limit)
    )
    result = await db.execute(stmt)
    comments = result.scalars().all()
    names = await _author_map(db, [c.user_id for c in comments])
    items = [_comment_to_schema(c, names.get(c.user_id, "")) for c in comments]
    return PageData(
        items=items,
        total=total,
        page=page,
        pages=paginate_pages(total, limit),
    )


async def list_all_comments(db: AsyncSession, item_id: int) -> list[ContentCommentInfo]:
    """一次取回某内容的全部评论（floor 升序），供 GraphQL 组装评论树。"""
    await get_or_raise(
        db, ContentItem, ContentErr.CONTENT_NOT_FOUND, ContentItem.id == item_id
    )
    stmt = (
        select(ContentComment)
        .where(ContentComment.content_id == item_id)
        .order_by(ContentComment.floor_number.asc())
    )
    result = await db.execute(stmt)
    comments = result.scalars().all()
    names = await _author_map(db, [c.user_id for c in comments])
    return [_comment_to_schema(c, names.get(c.user_id, "")) for c in comments]


async def create_comment(
    db: AsyncSession,
    item_id: int,
    user_id: int,
    info: ContentCommentCreate,
) -> ContentCommentInfo:
    item = await get_or_raise(
        db, ContentItem, ContentErr.CONTENT_NOT_FOUND, ContentItem.id == item_id
    )
    if info.parent_id is not None:
        await get_or_raise(
            db,
            ContentComment,
            ContentErr.COMMENT_NOT_FOUND,
            ContentComment.id == info.parent_id,
            ContentComment.content_id == item_id,
        )

    result = await db.execute(
        select(ContentComment)
        .where(ContentComment.content_id == item_id)
        .order_by(ContentComment.floor_number.desc())
        .limit(1)
    )
    floor = result.scalars().first()
    next_floor = floor.floor_number + 1 if floor else 1

    comment = ContentComment(
        content_id=item_id,
        user_id=user_id,
        content=info.content,
        floor_number=next_floor,
        parent_id=info.parent_id,
    )
    db.add(comment)
    item.comment_count += 1
    await db.flush()
    await enqueue_points_event(db, user_id, "comment", f"comment:{comment.id}")

    names = await _author_map(db, [comment.user_id])
    return _comment_to_schema(comment, names.get(comment.user_id, ""))


# ---- 供 blog publish 等内部调用（直接落 content_items）----


async def publish_blog_item(
    db: AsyncSession,
    owner_id: int,
    *,
    board_id: int,
    slug: str | None,
    title: str,
    content: str,
    summary: str | None,
    cover: str | None,
    tags: list[str],
) -> int:
    """把 blog 发布产物落成一条 content_items（content_type=blog_post）。

    幂等：同 slug 更新现有行（重发），否则新建。返回 content_items.id。
    """
    existing = None
    if slug:
        existing = (
            (
                await db.execute(
                    select(ContentItem).where(ContentItem.slug == slug).limit(1)
                )
            )
            .scalars()
            .first()
        )

    if existing is not None:
        existing.title = title
        existing.content = content
        existing.excerpt = _excerpt_of(content)
        existing.summary = summary or existing.summary
        existing.cover = cover or existing.cover
        existing.tags = json.dumps(tags, ensure_ascii=False)
        existing.content_type = ContentType.BLOG_POST
        existing.board_id = board_id
        existing.status = ContentStatus.PUBLISHED
        existing.published_at = existing.published_at or _now()
        await db.flush()
        return existing.id

    item = ContentItem(
        content_type=ContentType.BLOG_POST,
        board_id=board_id,
        author_id=owner_id,
        publisher=None,
        department=None,
        slug=slug or None,
        title=title,
        excerpt=_excerpt_of(content),
        content=content,
        summary=summary,
        cover=cover,
        tags=json.dumps(tags, ensure_ascii=False),
        status=ContentStatus.PUBLISHED,
        published_at=_now(),
    )
    db.add(item)
    await db.flush()
    # M0.5.2：仅“新建”分支记入博客发布产出；同 slug 重发（上面 existing 更新早退）不复计。
    post_created_total.labels(ContentType.BLOG_POST).inc()
    await enqueue_points_event(db, owner_id, "post", f"item:{item.id}")
    await bump_collection_version("content")
    return item.id
