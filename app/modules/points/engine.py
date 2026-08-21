"""积分事件消费副作用：更新行为计数 + 解锁成就 + 推进当日任务并达标另发奖励分。"""

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Achievement,
    Task,
    UserAchievement,
    UserBehaviorStat,
    UserTaskProgress,
)
from app.modules.points.service import reward

# 事件 → 行为统计计数键（写入 UserBehaviorStat.stats）
EVENT_STAT_KEY: dict[str, str] = {
    "post": "post",
    "comment": "comment",
    "like": "like",
    "file_approved": "file_approved",
    "answer_accepted": "answer_accepted",
    "competition": "competition",
}

# 行为计数键 → 成就 type 的匹配（用于重算成就进度）
STAT_TO_ACHIEVEMENT_TYPE: dict[str, str] = {
    "post": "post_count",
    "like": "like_count",
    "file_approved": "approved_files",
    "answer_accepted": "accepted_answers",
    "checkin_streak": "checkin_streak",
    "competition": "competition_count",
}


def _today() -> str:
    """当前日期（本地时区，YYYY-MM-DD）。"""
    return datetime.date.today().isoformat()


async def _get_or_create_stats(db: AsyncSession, user_id: int) -> UserBehaviorStat:
    """惰性取/建用户行为统计行。"""
    stat = await db.get(UserBehaviorStat, user_id)
    if stat is None:
        stat = UserBehaviorStat(user_id=user_id, stats={})
        db.add(stat)
        await db.flush()
    return stat


async def _bump_count(db: AsyncSession, user_id: int, key: str) -> int:
    """把某行为计数字段 +1，返回新值。

    JSON 列的 in-place 变更不会被 SQLAlchemy 追踪，需整列重赋以标记 dirty。
    """
    stat = await _get_or_create_stats(db, user_id)
    cur = int(stat.stats.get(key, 0))
    stat.stats = {**stat.stats, key: cur + 1}
    return cur + 1


async def apply_event_side_effects(
    db: AsyncSession,
    user_id: int,
    event: str,
    ref_id: str,
    *,
    today: str | None = None,
) -> None:
    """事件副作用主入口。today 可注入，便于测试对齐日期。"""
    tday = today or _today()
    # 1. 行为计数 + 成就重算
    stat_key = EVENT_STAT_KEY.get(event)
    if stat_key:
        await _bump_count(db, user_id, stat_key)
        await _recheck_achievements(db, user_id, stat_key)
    # 2. 每日任务推进
    await _advance_tasks(db, user_id, event, today=tday)


async def _progress_for(db: AsyncSession, user_id: int, type_: str) -> int:
    """计算某成就类型的当前进度（读 UserBehaviorStat.stats）。"""
    stat = await _get_or_create_stats(db, user_id)
    key = {  # 成就 type → stats 键
        "post_count": "post",
        # 预留：本期无数据源，命中即返回 0（不额外建行为映射，YAGNI）
        "featured_count": "featured_count",
        "accepted_answers": "answer_accepted",
        "approved_files": "file_approved",
        "checkin_streak": "checkin_streak",
        "project_count": "project_count",
        "column_articles": "column_articles",
        "like_count": "like",
        "competition_count": "competition",
        "onboarding": "onboarding",
    }.get(type_)
    if not key:
        return 0
    return int(stat.stats.get(key, 0))


async def _recheck_achievements(db: AsyncSession, user_id: int, stat_key: str) -> None:
    """对受影响的成就重算进度，达阈值即解锁。"""
    type_ = STAT_TO_ACHIEVEMENT_TYPE.get(stat_key)
    if type_ is None:
        return
    achievements = (
        (await db.execute(select(Achievement).where(Achievement.type == type_)))
        .scalars()
        .all()
    )
    progress = await _progress_for(db, user_id, type_)
    for ach in achievements:
        ua = (
            (
                await db.execute(
                    select(UserAchievement).where(
                        UserAchievement.user_id == user_id,
                        UserAchievement.achievement_id == ach.id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if ua is None:
            ua = UserAchievement(user_id=user_id, achievement_id=ach.id)
            db.add(ua)
            await db.flush()  # 先落库拿到该行，便于同会话后续查询可见
        ua.progress = min(progress, ach.threshold)
        if not ua.unlocked and progress >= ach.threshold:
            ua.unlocked = True
            ua.unlocked_at = datetime.datetime.now(datetime.UTC)


async def _advance_tasks(
    db: AsyncSession, user_id: int, event: str, *, today: str
) -> None:
    """推进当日任务进度，达标且未奖励的发放额外积分。"""
    task_events = {
        "post": "post",
        # 评论不入任何任务：仅发帖(post)推进发表任务，回帖不再 feed
        "answer_accepted": "answer",
        "like": "like",
        "file_approved": "file_upload",
        "checkin": "checkin",
        "competition": "competition",
    }
    cat = task_events.get(event)
    if cat is None:
        return
    tasks = (await db.execute(select(Task).where(Task.category == cat))).scalars().all()
    for t in tasks:
        up = (
            (
                await db.execute(
                    select(UserTaskProgress).where(
                        UserTaskProgress.user_id == user_id,
                        UserTaskProgress.task_id == t.id,
                        UserTaskProgress.period_date == today,
                    )
                )
            )
            .scalars()
            .first()
        )
        if up is None:
            up = UserTaskProgress(
                user_id=user_id,
                task_id=t.id,
                period_date=today,
                progress=0,
            )
            db.add(up)
            await db.flush()  # 先落库（拿到 id）再就地推进，供同会话查询可见
        up.progress = min(int(up.progress) + 1, t.requirement_count)
        # 打卡特判：requirement_count==1 的 checkin 任务直接置 progress=1（幂等）
        if t.requirement_count == 1 and event == "checkin":
            up.progress = 1
        if not up.completed and up.progress >= t.requirement_count:
            up.completed = True
            # 达标额外发分（rewarded 防重复）
            if not up.rewarded:
                await reward(
                    db,
                    user_id,
                    t.reward_points,
                    "daily_task",
                    "task",
                    f"{t.key}:{today}",
                )
                up.rewarded = True
