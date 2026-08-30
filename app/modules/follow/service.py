"""关注关系服务：用户关注/解关注用户、关注/解关注版块，id 集合供时间线过滤。

幂等实现走「软删墓碑」：follow 时将已有行 ``deleted_at`` 置 NULL（若存在；
否则新插入）；unfollow 仅置 ``deleted_at``，不删行。配合 ``(follower_id,
following_id)`` 唯一约束保证不产生第二行活动关注。

「我关注了谁」的 id 集合被时间线高频读取 → 短 TTL 缓存；follow/unfollow 写路径
显式失效。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import (
    TTL_ITEM_S,
    cache_invalidate,
    cached_read,
    make_key,
)
from app.core.err import BizError
from app.db.models import (
    Board,
    BoardFollow,
    Profile,
    User,
    UserFollow,
    now_iso,
)
from app.modules.follow.errors import FollowErr


def _following_key(user_id: int) -> str:
    return make_key("follow", "following", user_id)


def _board_ids_key(user_id: int) -> str:
    return make_key("follow", "boards", user_id)


async def _invalidate_follow_cache(user_id: int) -> None:
    """关注集合缓存显式失效（follow/unfollow 低频但需即时）。"""
    await cache_invalidate(_following_key(user_id), _board_ids_key(user_id))


async def follow_user(db: AsyncSession, follower_id: int, following_id: int) -> None:
    """follower 关注 following（幂等：重复关注静默成功）。"""
    if follower_id == following_id:
        raise BizError(FollowErr.CANNOT_FOLLOW_SELF, "不能关注自己")
    target = await db.get(User, following_id)
    if target is None:
        raise BizError(FollowErr.TARGET_NOT_FOUND, "关注目标用户不存在")

    row = await db.scalar(
        select(UserFollow).where(
            UserFollow.follower_id == follower_id,
            UserFollow.following_id == following_id,
        )
    )
    if row is None:
        db.add(UserFollow(follower_id=follower_id, following_id=following_id))
    elif row.deleted_at is not None:
        row.deleted_at = None
    await db.flush()
    await _invalidate_follow_cache(follower_id)


async def unfollow_user(db: AsyncSession, follower_id: int, following_id: int) -> None:
    """follower 取消关注 following（幂等：末关注时静默成功）。"""
    if follower_id == following_id:
        raise BizError(FollowErr.CANNOT_FOLLOW_SELF, "不能操作自己的关注")
    row = await db.scalar(
        select(UserFollow).where(
            UserFollow.follower_id == follower_id,
            UserFollow.following_id == following_id,
        )
    )
    if row is not None and row.deleted_at is None:
        row.deleted_at = now_iso()
        await db.flush()
        await _invalidate_follow_cache(follower_id)


async def follow_board(db: AsyncSession, follower_id: int, board_id: int) -> None:
    """follower 关注版块（幂等）。"""
    target = await db.get(Board, board_id)
    if target is None:
        raise BizError(FollowErr.TARGET_NOT_FOUND, "关注版块不存在")

    row = await db.scalar(
        select(BoardFollow).where(
            BoardFollow.follower_id == follower_id,
            BoardFollow.board_id == board_id,
        )
    )
    if row is None:
        db.add(BoardFollow(follower_id=follower_id, board_id=board_id))
    elif row.deleted_at is not None:
        row.deleted_at = None
    await db.flush()
    await _invalidate_follow_cache(follower_id)


async def unfollow_board(db: AsyncSession, follower_id: int, board_id: int) -> None:
    """follower 取消关注版块（幂等）。"""
    row = await db.scalar(
        select(BoardFollow).where(
            BoardFollow.follower_id == follower_id,
            BoardFollow.board_id == board_id,
        )
    )
    if row is not None and row.deleted_at is None:
        row.deleted_at = now_iso()
        await db.flush()
        await _invalidate_follow_cache(follower_id)


async def get_following_ids(db: AsyncSession, user_id: int) -> list[int]:
    """我关注的所有用户 id（缓存，供时间线过滤）。"""

    async def load() -> list[int]:
        rows = (
            (
                await db.execute(
                    select(UserFollow.following_id).where(
                        UserFollow.follower_id == user_id,
                        UserFollow.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    return await cached_read(_following_key(user_id), TTL_ITEM_S, load)


async def get_followed_board_ids(db: AsyncSession, user_id: int) -> list[int]:
    """我关注的所有版块 id（缓存，供时间线过滤）。"""

    async def load() -> list[int]:
        rows = (
            (
                await db.execute(
                    select(BoardFollow.board_id).where(
                        BoardFollow.follower_id == user_id,
                        BoardFollow.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    return await cached_read(_board_ids_key(user_id), TTL_ITEM_S, load)


async def is_following_user(
    db: AsyncSession, follower_id: int, following_id: int
) -> bool:
    """follower 当前是否关注 following（软删过滤）。"""
    row = await db.scalar(
        select(UserFollow.id).where(
            UserFollow.follower_id == follower_id,
            UserFollow.following_id == following_id,
            UserFollow.deleted_at.is_(None),
        )
    )
    return row is not None


async def list_following_users(
    db: AsyncSession, user_id: int
) -> list[tuple[int, str, str | None]]:
    """我关注的用户列表：(user_id, display_name, avatar)。

    display_name 取 ``nickname or username``（沿用 points 榜惯例），avatar 取
    Profile.avatar。走 id 集合 + 一次 join，避免逐条查询。
    """
    ids = await get_following_ids(db, user_id)
    if not ids:
        return []
    rows = (
        await db.execute(
            select(User.id, User.username, Profile.nickname, Profile.avatar)
            .outerjoin(Profile, Profile.user_id == User.id)
            .where(User.id.in_(ids))
        )
    ).all()
    by_id: dict[int, tuple[str, str | None]] = {}
    for uid, username, nickname, avatar in rows:
        by_id[uid] = (nickname or username or "", avatar)
    return [
        (uid, by_id.get(uid, (str(uid), None))[0], by_id.get(uid, (str(uid), None))[1])
        for uid in ids
    ]


async def list_followed_boards(db: AsyncSession, user_id: int) -> list[tuple[int, str]]:
    """我关注的版块列表：(board_id, title)。"""
    ids = await get_followed_board_ids(db, user_id)
    if not ids:
        return []
    rows = (
        await db.execute(select(Board.id, Board.title).where(Board.id.in_(ids)))
    ).all()
    title_by_id = {bid: title for bid, title in rows}
    return [(bid, title_by_id.get(bid, "")) for bid in ids]
