"""时间线服务：read-time 合流多内容源 × 关注过滤 × 审校降权 × 游标分页。

合流策略（对齐 Solar 参考）：**查询时合流**，非写入 fan-out——
每次请求实时从各内容源按 (created_at, id) 游标各取一页，合并后过滤审校隐藏项，
按（关注加权 + 审校排除后的）时间倒序返回。

审校：命中 hide 的条目在合流前剔除；命中 derank 的压低 ``sort_score`` 字段值
（v1 主序仍为时间倒序，derank 反映到排序分供后续热度排序使用，且 hide 即时生效）。
"""

from __future__ import annotations

import asyncio
import base64
import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.moderation.engine import evaluate, load_active_rules
from app.modules.auth.models import Profile, User
from app.modules.follow import service as follow_service
from app.modules.timeline import feed as feed_src
from app.modules.timeline.schemas import FeedItem, FeedResponse


async def _fill_authors(db: AsyncSession, items: list[FeedItem]) -> None:
    """把各源返回的 ``author_id`` 去重后批量查询一次并回填 ``author_name``。

    feed 各源不再各自查作者（除 blog 保留 publisher 兜底），避免同一作者在多源被
    重复 IN 查询。仅回填 ``author_name`` 仍为空者（blog 已填充/兜底的不触碰）。
    解析语义与 feed 一致：优先 profile.nickname，否则 username。
    """
    author_ids = {it.author_id for it in items if it.author_id and not it.author_name}
    if not author_ids:
        return
    rows = (
        await db.execute(
            select(User.id, User.username, Profile.nickname)
            .outerjoin(Profile, Profile.user_id == User.id)
            .where(User.id.in_(author_ids))
        )
    ).all()
    name_of: dict[int, str] = {}
    for uid, username, nickname in rows:
        name_of[int(uid)] = nickname or username or ""
    for it in items:
        if it.author_id in name_of and not it.author_name:
            it.author_name = name_of[it.author_id]


def _encode_cursor(created_at: datetime.datetime, item_id: int) -> str:
    raw = f"{created_at.isoformat()}|{item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str | None) -> tuple[datetime.datetime | None, int]:
    if not cursor:
        return None, 0
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        time_s, id_s = raw.rsplit("|", 1)
        return datetime.datetime.fromisoformat(time_s), int(id_s)
    except (ValueError, UnicodeDecodeError):
        return None, 0


def _recency_multiplier(created_at: datetime.datetime, now: datetime.datetime) -> float:
    age_hours = max(0.0, (now - created_at).total_seconds() / 3600)
    return (age_hours + 2.0) ** -1.2


async def _compute_scores(
    items: list[FeedItem],
    following_ids: set[int] | None,
    rules: list[Any],
) -> list[FeedItem]:
    now = datetime.datetime.now(datetime.UTC)
    for it in items:
        recency = (
            1.0
            if it.created_at.tzinfo is None
            else _recency_multiplier(it.created_at, now)
        )
        follow_bonus = 0.0
        if following_ids is not None and it.author_id in following_ids:
            follow_bonus = 5.0
        # 审校：hide 已在上游剔除；这里只处理 derank 扣分
        text = f"{it.title} {it.content_preview}"
        mod = evaluate(text, rules)
        penalty = 0.0 if mod.should_hide else mod.penalty
        # 时间基分(recency*1000)保证 0 热度内容也有>0基分，使 derank 扣分可分辨；
        # 关注权重(follow_bonus)加在前面、不被审校削减。
        base = it.sort_score * 500 + recency * 1000
        it.sort_score = base * (1.0 - penalty) + follow_bonus
    return items


async def get_timeline(
    db: AsyncSession,
    *,
    user_id: int | None,
    mode: str,
    cursor: str | None,
    limit: int,
) -> FeedResponse:
    before_time, before_id = _decode_cursor(cursor)

    following_ids: set[int] | None = None
    board_ids: set[int] | None = None
    if mode == "follow":
        if user_id is None:
            mode = "hot"  # 匿名只能看全站热门
        else:
            following_ids = set(await follow_service.get_following_ids(db, user_id))
            board_ids = set(await follow_service.get_followed_board_ids(db, user_id))
            # 空关注 → 返回空流
            if not following_ids and not board_ids:
                return FeedResponse(items=[], next_cursor=None)

    # 选源：follow 用 FOLLOW_SOURCES（article 无作者外键不进个性化），hot 全含
    source_names = feed_src.FOLLOW_SOURCES if mode == "follow" else feed_src.HOT_SOURCES

    # 各内容源互不依赖，gather 并行拉取，而非串行 await（时间线多源往返叠加）。
    async def _fetch_one(name: str) -> list[FeedItem]:
        fetch = feed_src.SOURCES[name]
        if mode == "follow":
            # discussion 额外按关注版块过滤；其余按关注作者过滤
            b_ids = board_ids if name == "discussion" else None
            a_ids = following_ids
        else:
            a_ids, b_ids = None, None
        return await fetch(db, a_ids, b_ids, before_time, before_id, limit)

    fetched: list[list[FeedItem]] = await asyncio.gather(
        *(_fetch_one(n) for n in source_names)
    )
    candidates: list[FeedItem] = [it for group in fetched for it in group]

    # 合并回填作者名：各源只返回 author_id，此处一次性批量查询（抵消每源各查一次）
    await _fill_authors(db, candidates)

    # 审校隐藏剔除 + 排序分计算
    rules = await load_active_rules(db)
    kept: list[FeedItem] = []
    for it in candidates:
        text = f"{it.title} {it.content_preview}"
        mod = evaluate(text, rules)
        if mod.should_hide:
            continue
        kept.append(it)
    await _compute_scores(kept, following_ids, rules)

    # 主序：时间倒序（稳定性靠 id 倒序兜底）
    kept.sort(key=lambda it: (it.created_at, it.id), reverse=True)
    page = kept[:limit]

    next_cursor: str | None = None
    if page and not (len(kept) <= limit):
        last = page[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    return FeedResponse(items=page, next_cursor=next_cursor)
