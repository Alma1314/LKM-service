"""死信消费者：消费 lkm.dlq 队列，把每条死信落库 dlq_messages 供人工重投/审计。

消费语义：ack（落库成功即移出 Rabbit 的 DLQ，后续从 DB 治理）。重投走 admin 端点
re-publish 回原 routing_key。配置 Rabbit 不可用 → 日志降级（DLQ 队列堆积待恢复）。
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import aio_pika
from sqlalchemy import select

from app.core import amqp
from app.core.worker import DLQ, DLX
from app.db.session import new_session
from app.modules.admin.models import DlqMessage

logger = logging.getLogger("lkm.worker_dlq")


def _make_model(
    *,
    routing_key: str,
    body: bytes,
    attempts: int,
    reason: str,
    status: str,
) -> DlqMessage:
    """把一条死信消息体映射为 DlqMessage（坏 JSON 兜底存 raw，不丢）。"""
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        parsed = {"raw": body.decode("utf-8", "replace")}
    return DlqMessage(
        routing_key=routing_key,
        payload_json=json.dumps({"payload": parsed}),
        exchange="lkm.events",
        attempts=attempts,
        reason=reason[:255],
        status=status,
        created_at=datetime.now(UTC),
    )


def _read_attempts(msg: Any) -> int:
    """从消息头 x-death.count 取死信次数（缺失=0）。"""
    death = getattr(msg, "headers", None) or {}
    death_list = death.get("x-death", [])
    if not death_list:
        return 0
    first = death_list[0] if isinstance(death_list, list) else death_list
    return int(first.get("count", 0)) if isinstance(first, dict) else 0


async def _persist(model: DlqMessage) -> None:
    """把一条 DLQ 模型落库（独立事务，与请求上下文解耦）。"""
    db = await new_session()
    try:
        db.add(model)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def requeue(db: Any, dlq_id: int) -> bool:
    """把一条 pending 死信 re-publish 回原 routing_key，标记 requeued。"""
    m = await db.scalar(select(DlqMessage).where(DlqMessage.id == dlq_id))
    if m is None or m.status != "pending":
        return False
    parsed = json.loads(m.payload_json).get("payload", {})
    ok = await amqp._publish(m.routing_key, parsed)
    if ok:
        m.status = "requeued"
        m.requeued_at = datetime.now(UTC)
        await db.commit()
    return ok


async def consume_dlq() -> None:
    """DLQ 消费者主循环（compose worker-dlq 入口）。

    消费语义：成功落库即 ack 移出（后续从 DB 治理）；落库失败 raise → msg.process
    发 nack(requeue=False)。因本队列不设 x-dead-letter，nack 后消息被丢弃（避免
    死信再死信死循环），已在日志记录，可人工审计。
    """
    ch = await amqp.get_amqp()
    if ch is None:
        logger.error("rabbitmq 不可用，dlq 消费者空转退出")
        return
    q = await ch.declare_queue(DLQ, durable=True)
    # 本进程(独立 worker_dlq)也确保 DLX(fanout)→DLQ 绑定存在，不依赖业务 worker 先跑拓扑。
    # 缺此绑定且业务 worker 未启动时，死信 hit DLX 会因 unroutable 被静默丢弃。
    # Rabbit 幂等合并，重复 declare/bind 无害，不破坏 _declare_topology 行为。
    dlx = await ch.declare_exchange(DLX, aio_pika.ExchangeType.FANOUT, durable=True)
    await q.bind(dlx, "")
    await asyncio.sleep(0)

    async def _on(msg: Any) -> None:
        async with msg.process(requeue=False):
            try:
                model = _make_model(
                    routing_key=msg.routing_key,
                    body=msg.body,
                    attempts=_read_attempts(msg),
                    reason="dead-lettered",
                    status="pending",
                )
                await _persist(model)
            except Exception:
                logger.exception("dlq 落库失败")
                raise

    await q.consume(_on, no_ack=False)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(consume_dlq())
