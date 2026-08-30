"""积分事件消费任务：reward 入账 + 更新行为计数 + 解锁成就 + 推进任务并达标另发奖励分。

worker 无请求上下文，用 app.db.session.new_session() 自建会话，独立事务。
入账用 reward()（幂等，ref 唯一约束防重复发分）。失败向上抛 → 死信 DLQ（不重试）。
"""

from app.db.session import new_session
from app.modules.points.rules import RULE_DELTAS
from app.modules.points.service import reward


async def apply_point_event(user_id: int, event: str, ref_id: str) -> None:
    """积分事件任务：消费一个积分事件。"""
    from app.modules.points.engine import apply_event_side_effects  # Task 3 提供

    db = await new_session()
    try:
        delta = RULE_DELTAS.get(event, 0)
        # answer_accepted 或未知事件不额外发分（QA 已派发 bounty）
        if delta > 0:
            await reward(db, user_id, delta, event, event, ref_id)
        await apply_event_side_effects(db, user_id, event, ref_id)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
