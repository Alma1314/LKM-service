"""points 模块队列任务：积分事件消费（reward 入账 + 更新行为计数 + 解锁成就等）。

worker 无请求上下文，用 app.db.session.new_session() 自建会话，独立事务。
入账用 reward()（幂等，ref 唯一约束防重复发分）。失败向上抛 → 死信 DLQ（不重试）。

任务经 ``register_task`` 注册到 points 队列（§6.2）。
"""

from app.core.task_registry import register_queue, register_task
from app.db.session import new_session
from app.modules.points.rules import RULE_DELTAS
from app.modules.points.service import reward

QUEUE = "lkm.points"  # points worker 进程消费
ROUTING_KEYS = ["event.apply_point"]

register_queue(QUEUE, ROUTING_KEYS)


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


register_task(QUEUE, "apply_point_event", apply_point_event)
