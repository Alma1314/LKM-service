import json
from typing import Any

from sqlalchemy import select

from app.core import worker_dlq
from app.modules.admin.models import DlqMessage


def test_make_model_maps_json_body() -> None:
    """坏 JSON → raw 兜底；好 JSON → payload 结构。"""
    payload = {"fn": "send_code", "args": ["email", "a@b.com", "123456"]}
    m = worker_dlq._make_model(
        routing_key="event.send_code",
        body=json.dumps(payload).encode(),
        attempts=2,
        reason="nack",
        status="pending",
    )
    assert m.routing_key == "event.send_code"
    assert json.loads(m.payload_json)["payload"] == payload
    assert m.attempts == 2
    assert m.status == "pending"
    # 坏 JSON 兜底
    bad = worker_dlq._make_model(
        routing_key="event.x", body=b"not-json", attempts=0, reason="", status="pending"
    )
    assert "raw" in json.loads(bad.payload_json)["payload"]


async def test_persist_writes_row(db: Any) -> None:
    """_persist 把模型落库到 db 表。"""
    m = worker_dlq._make_model(
        routing_key="event.send_code",
        body=json.dumps({"fn": "send_code", "args": ["e", "c", "123"]}).encode(),
        attempts=1,
        reason="dead-lettered",
        status="pending",
    )
    db.add(m)
    await db.commit()
    fetched = (
        (await db.execute(select(DlqMessage))).scalars().one()
    )
    assert fetched.routing_key == "event.send_code"


async def test_requeue_publishes_and_marks_requeued(db: Any, monkeypatch: Any) -> None:
    """重投端点把消息 re-publish 回原 routing key 并标记 requeued。"""
    published: list[tuple] = []

    async def fake_pub(rk: str, payload: dict) -> bool:
        published.append((rk, payload))
        return True

    monkeypatch.setattr(worker_dlq.amqp, "_publish", fake_pub)

    m = DlqMessage(routing_key="event.point", payload_json='{"payload":{"fn":"apply_point_event","args":[1,"like","x:1"]}}')
    db.add(m)
    await db.commit()
    await db.refresh(m)

    ok = await worker_dlq.requeue(db, m.id)
    assert ok is True
    await db.refresh(m)
    assert m.status == "requeued"
    assert m.requeued_at is not None
    assert published[0][0] == "event.point"
    assert published[0][1]["fn"] == "apply_point_event"
