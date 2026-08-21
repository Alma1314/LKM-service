import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.err import BizError, CommonErr
from app.db.models import ForumComment, ForumPost, ForumPostLike, User
from app.db.repo import get_or_raise
from app.modules.common import (
    PageData,
    paginate_offset,
    paginate_pages,
)
from app.modules.forum.errors import ForumErr
from app.modules.forum.models import FORUM_TABLE_PLAN
from app.modules.forum.schemas import (
    CommentCreate,
    CommentInfo,
    PostCreate,
    PostInfo,
)
from app.modules.points.rules import enqueue_points_event


def _author_name(user: User) -> str:
    if user.profile and user.profile.nickname:
        return user.profile.nickname
    return user.username


def _excerpt_of(content: str, limit: int = 150) -> str:
    text = re.sub(r"<[^>]+>", " ", content)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _post_to_schema(p: ForumPost, author_name: str) -> PostInfo:
    return PostInfo.model_validate(p).model_copy(update={"author_name": author_name})


def _comment_to_schema(c: ForumComment, author_name: str) -> CommentInfo:
    return CommentInfo.model_validate(c).model_copy(update={"author_name": author_name})


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


def get_forum_plan() -> dict[str, Any]:
    return {
        "status": "implemented_minimal",
        "tables": FORUM_TABLE_PLAN,
        "next_steps": [
            "Add comment delete API",
            "Add post moderation and report workflow",
            "Board relation already connected via board_id",
        ],
    }


async def list_posts(
    db: AsyncSession,
    page: int = 1,
    limit: int = 20,
    board_id: int | None = None,
) -> PageData[PostInfo]:
    base = select(ForumPost)
    if board_id:
        base = base.where(ForumPost.board_id == board_id)

    count_stmt = select(func.count()).select_from(base.subquery())
    total_count = await db.scalar(count_stmt) or 0

    stmt = (
        base.order_by(ForumPost.is_pinned.desc(), ForumPost.id.desc())
        .offset(paginate_offset(page, limit))
        .limit(limit)
    )
    result = await db.execute(stmt)
    posts = result.scalars().all()

    names = await _author_map(db, [p.author_id for p in posts])
    items = [_post_to_schema(p, names.get(p.author_id, "")) for p in posts]
    return PageData(
        items=items,
        total=total_count,
        page=page,
        pages=paginate_pages(total_count, limit),
    )


async def get_post(db: AsyncSession, post_id: int, bump_view: bool = False) -> PostInfo:
    post = await get_or_raise(
        db, ForumPost, ForumErr.POST_NOT_FOUND, ForumPost.id == post_id
    )

    if bump_view:
        post.view_count += 1
        await db.flush()

    names = await _author_map(db, [post.author_id])
    return _post_to_schema(post, names.get(post.author_id, ""))


async def create_post(db: AsyncSession, author_id: int, info: PostCreate) -> PostInfo:
    # 发言准入：板块存在 / 可见 / 未禁言 / 认证 / 日限发
    from app.modules.boards.service import check_post_allowed

    await check_post_allowed(db, info.board_id, author_id)

    post = ForumPost(
        author_id=author_id,
        board_id=info.board_id,
        title=info.title,
        excerpt=_excerpt_of(info.content),
        content=info.content,
        tags=json.dumps(info.tags, ensure_ascii=False),
    )
    db.add(post)
    await db.flush()
    # 发帖事件入队（异步计分，不阻塞 200）
    await enqueue_points_event(author_id, "post", f"post:{post.id}")

    names = await _author_map(db, [post.author_id])
    return _post_to_schema(post, names.get(post.author_id, ""))


async def delete_post(
    db: AsyncSession,
    post_id: int,
    current_user_id: int,
    as_admin: bool = False,
) -> int:
    """删除帖子并返回作者 id。普通用户只能删自己的；as_admin=True（管理员代删）跳过 owner 校验。"""
    post = await get_or_raise(
        db, ForumPost, ForumErr.POST_NOT_FOUND, ForumPost.id == post_id
    )
    if not as_admin and post.author_id != current_user_id:
        raise BizError(CommonErr.FORBIDDEN)
    author_id = post.author_id
    await db.delete(post)
    await db.flush()
    return author_id


async def like_post(db: AsyncSession, post_id: int, user_id: int) -> int:
    post = await get_or_raise(
        db, ForumPost, ForumErr.POST_NOT_FOUND, ForumPost.id == post_id
    )

    # 幂等：同一用户重复点赞不重复计数（复合主键兜底并发下的唯一约束）
    existing = (
        (
            await db.execute(
                select(ForumPostLike).where(
                    ForumPostLike.post_id == post_id,
                    ForumPostLike.user_id == user_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return post.like_count

    db.add(ForumPostLike(user_id=user_id, post_id=post_id))
    post.like_count += 1
    await db.flush()
    # 仅新增点赞路径入队（幂等分支不含）
    await enqueue_points_event(user_id, "like", f"post:{post_id}")
    return post.like_count


async def list_comments(
    db: AsyncSession,
    post_id: int,
    page: int = 1,
    limit: int = 20,
) -> PageData[CommentInfo]:
    await get_or_raise(db, ForumPost, ForumErr.POST_NOT_FOUND, ForumPost.id == post_id)

    total = (
        await db.scalar(
            select(func.count(ForumComment.id)).where(ForumComment.post_id == post_id)
        )
        or 0
    )
    stmt = (
        select(ForumComment)
        .where(ForumComment.post_id == post_id)
        .order_by(ForumComment.floor_number.asc())
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


async def create_comment(
    db: AsyncSession,
    post_id: int,
    user_id: int,
    info: CommentCreate,
) -> CommentInfo:
    post = await get_or_raise(
        db, ForumPost, ForumErr.POST_NOT_FOUND, ForumPost.id == post_id
    )

    if info.parent_id is not None:
        await get_or_raise(
            db,
            ForumComment,
            ForumErr.COMMENT_NOT_FOUND,
            ForumComment.id == info.parent_id,
            ForumComment.post_id == post_id,
        )

    result = await db.execute(
        select(ForumComment)
        .where(ForumComment.post_id == post_id)
        .order_by(ForumComment.floor_number.desc())
        .limit(1)
    )
    floor = result.scalars().first()
    next_floor = floor.floor_number + 1 if floor else 1

    comment = ForumComment(
        post_id=post_id,
        user_id=user_id,
        content=info.content,
        floor_number=next_floor,
        parent_id=info.parent_id,
    )
    db.add(comment)
    post.comment_count += 1
    await db.flush()
    # 评论事件入队（异步入账）
    await enqueue_points_event(user_id, "comment", f"comment:{comment.id}")

    names = await _author_map(db, [comment.user_id])
    return _comment_to_schema(comment, names.get(comment.user_id, ""))
