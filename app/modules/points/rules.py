"""积分规则表：事件类型 → 单次积分。事件属展示/计数 + 入账两用。"""

# event → delta 奖励分（answer_accepted 不给分：QA 已按悬赏派发，见设计中说明）
RULE_DELTAS: dict[str, int] = {
    "post": 10,
    "comment": 2,
    "like": 1,
    "file_approved": 15,
    "answer_accepted": 0,  # 只计数不加分（QA 已派发 bounty）
    "checkin": 5,
    "competition": 50,
}


async def enqueue_points_event(user_id: int, event: str, ref_id: str) -> None:
    """把用户行为事件入队给 points worker 异步入账（fire-and-forget，不阻塞主流程）。

    Redis 不可用/入队失败静默 no-op（对齐 enqueue_upload_notify 的 fail-open 语义）：
    事件侧可经确认/重建恢复，宁可丢弃也不阻塞业务动作的 200 时序。
    """
    from app.core.jobs import _enqueue
    from app.core.worker import POINTS_QUEUE

    await _enqueue("apply_point_event", user_id, event, ref_id, queue=POINTS_QUEUE)
