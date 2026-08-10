from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from app.core.err import BizError, CommonErr
from app.modules.blog.errors import BlogErr
from app.db.models import BlogComment, BlogSeries, BlogStar, Profile, now_iso
from app.db.repo import get_or_raise
from app.modules.blog import git_svc
from app.modules.auth.schemas import ProfileInfo
from app.modules.blog.schemas import (
    BlogCommentCreate,
    BlogCommentInfo,
    BlogSeriesCreate,
    BlogSeriesDetail,
    BlogSeriesInfo,
    BlogSeriesUpdate,
    BlogStarStatus,
)


# ---- private converters ----


def _series_to_info(
    s: BlogSeries, star_count: int = 0, is_starred: bool = False
) -> BlogSeriesInfo:
    return BlogSeriesInfo.model_validate(s).model_copy(
        update={"star_count": star_count, "is_starred": is_starred}
    )


def _comment_to_info(c: BlogComment, profile: ProfileInfo | None = None) -> BlogCommentInfo:
    return BlogCommentInfo.model_validate(c).model_copy(update={"profile": profile})


# ---- star helpers ----


async def _star_count(db: AsyncSession, series_id: int) -> int:
    return (
        await db.scalar(select(func.count(BlogStar.user_id)).where(BlogStar.series_id == series_id))
        or 0
    )


async def _is_starred(db: AsyncSession, series_id: int, user_id: int) -> bool:
    return (
        await db.execute(
            select(BlogStar).where(BlogStar.series_id == series_id, BlogStar.user_id == user_id)
        )
    ).scalars().first() is not None


async def _star_counts(db: AsyncSession, series_ids: list[int]) -> dict[int, int]:
    """批量统计多个系列的 star 数量，避免逐条查询的 N+1。"""
    if not series_ids:
        return {}
    rows = (
        await db.execute(
            select(BlogStar.series_id, func.count(BlogStar.user_id))
            .where(BlogStar.series_id.in_(set(series_ids)))
            .group_by(BlogStar.series_id)
        )
    ).all()
    return {sid: cnt for sid, cnt in rows}


async def _starred_ids(db: AsyncSession, series_ids: list[int], user_id: int) -> set[int]:
    """批量查当前用户 star 了哪些系列，避免逐条查询的 N+1。"""
    if not series_ids:
        return set()
    rows = (
        await db.execute(
            select(BlogStar.series_id).where(
                BlogStar.series_id.in_(set(series_ids)), BlogStar.user_id == user_id
            )
        )
    ).all()
    return {sid for (sid,) in rows}


async def _get_profile(db: AsyncSession, user_id: int) -> ProfileInfo | None:
    profile = (await db.execute(select(Profile).where(Profile.user_id == user_id))).scalars().first()
    if profile:
        return ProfileInfo.model_validate(profile)
    return None


# ---- series CRUD ----


async def create_series(db: AsyncSession, user_id: int, info: BlogSeriesCreate) -> BlogSeriesInfo:
    existing = (
        await db.execute(select(BlogSeries).where(BlogSeries.repo_name == info.repo_name))
    ).scalars().first()
    if existing:
        raise BizError(CommonErr.INVALID_INPUT, "Repository name already taken")

    git_svc.init_bare_repo(info.repo_name)

    series = BlogSeries(
        owner_id=user_id,
        title=info.title,
        description=info.description,
        cover_url=info.cover_url,
        repo_name=info.repo_name,
    )
    db.add(series)
    await db.flush()
    return _series_to_info(series)


async def list_series(
    db: AsyncSession, current_user_id: int | None = None
) -> list[BlogSeriesInfo]:
    items = (await db.execute(select(BlogSeries).order_by(BlogSeries.id.desc()))).scalars().all()
    ids = [s.id for s in items]
    counts = await _star_counts(db, ids)
    starred_ids = await _starred_ids(db, ids, current_user_id) if current_user_id else set()
    result: list[BlogSeriesInfo] = []
    for s in items:
        result.append(
            _series_to_info(s, star_count=counts.get(s.id, 0), is_starred=s.id in starred_ids)
        )
    return result


async def get_series(
    db: AsyncSession, series_id: int, current_user_id: int | None = None
) -> BlogSeriesDetail:
    series = await get_or_raise(
        db, BlogSeries, BlogErr.SERIES_NOT_FOUND, BlogSeries.id == series_id,
    )

    sc = await _star_count(db, series_id)
    starred = (
        await _is_starred(db, series_id, current_user_id) if current_user_id else False
    )

    file_tree: list[dict[str, Any]] | None = None
    if git_svc.ensure_repo_has_commits(series.repo_name):
        file_tree = git_svc.get_file_tree(series.repo_name)

    return BlogSeriesDetail.model_validate(series).model_copy(
        update={"star_count": sc, "is_starred": starred, "file_tree": file_tree}
    )


async def update_series(
    db: AsyncSession, series_id: int, user_id: int, info: BlogSeriesUpdate
) -> BlogSeriesInfo:
    series = await get_or_raise(
        db, BlogSeries, BlogErr.SERIES_NOT_FOUND, BlogSeries.id == series_id,
    )
    if series.owner_id != user_id:
        raise BizError(CommonErr.FORBIDDEN)

    if info.title is not None:
        series.title = info.title
    if info.description is not None:
        series.description = info.description
    if info.cover_url is not None:
        series.cover_url = info.cover_url
    if info.status is not None:
        series.status = info.status
    series.updated_at = now_iso()

    await db.flush()
    return _series_to_info(series)


async def delete_series(db: AsyncSession, series_id: int, user_id: int) -> None:
    series = await get_or_raise(
        db, BlogSeries, BlogErr.SERIES_NOT_FOUND, BlogSeries.id == series_id,
    )
    if series.owner_id != user_id:
        raise BizError(CommonErr.FORBIDDEN)

    git_svc.delete_repo(series.repo_name)
    await db.delete(series)
    await db.flush()


# ---- star toggle ----


async def toggle_star(db: AsyncSession, series_id: int, user_id: int) -> BlogStarStatus:
    await get_or_raise(db, BlogSeries, BlogErr.SERIES_NOT_FOUND, BlogSeries.id == series_id)

    existing = (
        await db.execute(
            select(BlogStar).where(BlogStar.series_id == series_id, BlogStar.user_id == user_id)
        )
    ).scalars().first()

    if existing:
        await db.delete(existing)
        await db.flush()
        return BlogStarStatus(starred=False, star_count=await _star_count(db, series_id))

    star = BlogStar(user_id=user_id, series_id=series_id)
    db.add(star)
    await db.flush()
    return BlogStarStatus(starred=True, star_count=await _star_count(db, series_id))


# ---- comments ----


async def create_comment(
    db: AsyncSession, series_id: int, user_id: int, info: BlogCommentCreate
) -> BlogCommentInfo:
    await get_or_raise(db, BlogSeries, BlogErr.SERIES_NOT_FOUND, BlogSeries.id == series_id)

    if info.parent_id is not None:
        parent = await get_or_raise(
            db, BlogComment, CommonErr.INVALID_INPUT,
            BlogComment.id == info.parent_id,
        )
        if parent.series_id != series_id:
            raise BizError(CommonErr.INVALID_INPUT, "Parent comment not found")

    comment = BlogComment(
        user_id=user_id,
        series_id=series_id,
        content=info.content,
        parent_id=info.parent_id,
    )
    db.add(comment)
    await db.flush()
    # 重新用 selectinload 预载 replies，避免序列化时懒加载触发 MissingGreenlet
    loaded_comment = (
        await db.execute(
            select(BlogComment)
            .where(BlogComment.id == comment.id)
            .options(selectinload(BlogComment.replies))
        )
    ).scalars().first()
    if loaded_comment is None:
        loaded_comment = comment
    return _comment_to_info(loaded_comment, profile=await _get_profile(db, user_id))


async def list_comments(db: AsyncSession, series_id: int) -> list[BlogCommentInfo]:
    await get_or_raise(db, BlogSeries, BlogErr.SERIES_NOT_FOUND, BlogSeries.id == series_id)

    comments = (
        await db.execute(
            select(BlogComment)
            .where(BlogComment.series_id == series_id)
            .order_by(BlogComment.created_at.asc())
            .options(selectinload(BlogComment.replies))
        )
    ).scalars().all()

    user_ids = {c.user_id for c in comments}
    profiles: dict[int, ProfileInfo | None] = {}
    for uid in user_ids:
        profiles[uid] = await _get_profile(db, uid)

    comment_map: dict[int, BlogCommentInfo] = {}
    roots: list[BlogCommentInfo] = []

    for c in comments:
        info = _comment_to_info(c, profile=profiles.get(c.user_id))
        comment_map[c.id] = info

    for c in comments:
        info = comment_map[c.id]
        if c.parent_id is not None and c.parent_id in comment_map:
            comment_map[c.parent_id].replies.append(info)
        else:
            roots.append(info)

    return roots


async def delete_comment(db: AsyncSession, series_id: int, comment_id: int, user_id: int) -> None:
    comment = await get_or_raise(
        db, BlogComment, BlogErr.COMMENT_NOT_FOUND,
        BlogComment.id == comment_id,
        BlogComment.series_id == series_id,
    )
    if comment.user_id != user_id:
        raise BizError(CommonErr.FORBIDDEN)
    await db.delete(comment)
    await db.flush()


# ---- files ----


async def get_file_content(db: AsyncSession, series_id: int, filepath: str) -> dict[str, Any]:
    series = await get_or_raise(
        db, BlogSeries, BlogErr.SERIES_NOT_FOUND, BlogSeries.id == series_id,
    )
    content = git_svc.read_file(series.repo_name, filepath)
    return {"filepath": filepath, "content": content}
