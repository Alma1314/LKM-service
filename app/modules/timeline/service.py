"""时间线服务：read-time 合流多内容源 × 关注过滤 × 审校降权 × 游标分页。

合流策略（对齐 Solar 参考）：**查询时合流**，非写入 fan-out——
每次请求实时从各内容源按 (created_at, id) 游标各取一页，合并后过滤审校隐藏项，
按（关注加权 + 审校排除后的）时间倒序返回。

审校：命中 hide 的条目在合流前剔除；命中 derank 的压低 ``sort_score`` 字段值
（v1 主序仍为时间倒序，derank 反映到排序分供后续热度排序使用，且 hide 即时生效）。
"""

from __future__ import annotations

import base64
import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.follow import service as follow_service
from app.modules.moderation.engine import evaluate, load_active_rules
from app.modules.timeline import feed as feed_src
from app.modules.timeline.schemas import FeedItem, FeedResponse


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

    candidates: list[FeedItem] = []
    for name in source_names:
        fetch = feed_src.SOURCES[name]
        if mode == "follow":
            # forum 额外按关注版块过滤；其余按关注作者过滤
            b_ids = board_ids if name == "forum" else None
            a_ids = following_ids
        else:
            a_ids, b_ids = None, None
        items = await fetch(db, a_ids, b_ids, before_time, before_id, limit)
        candidates.extend(items)

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
