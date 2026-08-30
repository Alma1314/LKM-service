"""RabbitMQ worker 配置与入口：拓扑声明 + 四队列消费者。

四个独立 worker 进程（send/notify/points/jobs）各自 consume 一个队列，
保留故障隔离。业务队列配 x-dead-letter-exchange → 统一 DLQ，死信由
worker_dlq 落库（见 scheduler/dlq 任务）。cron 由独立 APScheduler 进程
发布 cron.* 消息到 DEFAULT_QUEUE 消费（run_default_worker 消费 cron key）。
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import aio_pika

from app.core import amqp

logger = logging.getLogger("lkm.worker")

JOB_TIMEOUT_S = 120  # 单任务执行上限，超时→死信重投


def _ensure_models() -> None:
    """预注册全部 ORM 模型（同旧实现，防 worker 进程 SQLAlchemy mapper 缺失）。"""
    import app.modules.auth.models
    import app.modules.blog.models
    import app.modules.content.column_models  # 预 import Column StrEnum 常量
    import app.modules.files.models  # noqa: F401  # 副作用导入
    from app.db.models import Base

    Base.registry.configure()


_ensure_models()

# 拓扑常量
EXCHANGE = amqp.EXCHANGE  # lkm.events (topic)
SEND_QUEUE = "lkm.send"
NOTIFY_QUEUE = "lkm.notify"
POINTS_QUEUE = "lkm.points"
DEFAULT_QUEUE = "lkm.jobs"
DLX = "lkm.dlx"  # dead-letter exchange (fanout)
DLQ = "lkm.dlq"  # 统一死信队列

# routing key 常量（与 jobs.py 对齐）
RKEY_SEND_CODE = "event.send_code"
RKEY_SEND_MAGIC = "event.send_magic_link"
RKEY_NOTIFY = "event.notify_upload"
RKEY_POINTS = "event.apply_point"
RKEY_CLEANUP = "cron.cleanup"
RKEY_RECONCILE = "cron.reconcile"


async def _declare_topology(ch: Any) -> None:
    """幂等声明：exchange + 四业务队列(含各自的 x-dead-letter) + DLX + DLQ。

    注意 DLX 用 **FANOUT**：Rabbit 死信会把消息以【原始 routing key】republish 到
    x-dead-letter-exchange。若 DLX 是 DIRECT 且有零绑定，死信因 unroutable 被静默丢弃，
    进不到 DLQ。FANOUT 忽略 routing key、投递到所有绑定队列 → 绑定 DLQ 后任何死信都落库。
    """
    await ch.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
    await ch.declare_exchange(DLX, aio_pika.ExchangeType.FANOUT, durable=True)
    dlq = await ch.declare_queue(DLQ, durable=True)
    # 绑定 DLQ → DLX（fanout 忽略 key，"" 即通配全量）。缺这步死信会丢。
    await ch.bind_queue(dlq, DLX, "")
    for qname, rks in (
        (SEND_QUEUE, [RKEY_SEND_CODE, RKEY_SEND_MAGIC]),
        (NOTIFY_QUEUE, [RKEY_NOTIFY]),
        (POINTS_QUEUE, [RKEY_POINTS]),
        (DEFAULT_QUEUE, [RKEY_CLEANUP, RKEY_RECONCILE]),
    ):
        q = await ch.declare_queue(
            qname,
            durable=True,
            arguments={"x-dead-letter-exchange": DLX},
        )
        for rk in rks:
            await ch.bind_queue(q, EXCHANGE, rk)


async def _consume(
    queue_name: str,
    handlers: dict[str, Callable[..., Any]],
) -> None:
    """消费指定队列，按 rk 分发 handler。任务执行包 120s 超时。

    handler 成功 → ack；异常/超时 → nack(requeue=False) → 死信 DLQ。
    拓扑（exchange/四队列/DLX/DLQ/绑定）由 _declare_topology 统一幂等声明，此处只取句柄：
    用不同 arguments 重声明同一队列会让 Rabbit 406 PRECONDITION_FAILED 关 channel。
    """
    ch = await amqp.get_amqp()
    if ch is None:
        logger.error("rabbitmq 未配置/不可用，block=%s 无法消费", queue_name)
        return  # worker 进程空转退出由外层处理
    await _declare_topology(ch)
    queue = await ch.get_queue(queue_name)

    async def _on_msg(msg: Any) -> None:
        payload: dict[str, Any] = {}
        async with msg.process(requeue=False):
            try:
                try:
                    payload = json.loads(msg.body)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    logger.warning("队列入队消息非法 JSON, 丢弃 queue=%s body=%r", queue_name, msg.body)
                    return  # ack 丢弃坏消息, 避免死信风暴
                fn = payload.get("fn")
                args = payload.get("args", [])
                handler = handlers.get(fn) if isinstance(fn, str) else None
                if handler is None:
                    logger.warning("未知任务 %s, 丢弃", fn)
                    return  # ack 丢弃
                await asyncio.wait_for(handler(*args), timeout=JOB_TIMEOUT_S)
            except Exception:
                logger.exception(
                    "任务失败入死信 queue=%s fn=%s", queue_name, payload.get("fn")
                )
                raise  # nack(requeue=False) → 死信。注意：不可 suppress TimeoutError，
                # 否则超时被当成功 ack，违背"超时→死信重投"语义。

    await queue.consume(_on_msg, no_ack=False)
    await asyncio.sleep(0)  # 让 consume 注册完成
    # 保持事件循环存活，消费循环由 aio-pika 内部 task 驱动
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        raise


# ---- 四个 run_*_worker 入口（worker_*.py 调用）----


async def run_send_worker() -> None:
    from app.tasks import send

    await _consume(
        SEND_QUEUE,
        {"send_code": send.send_code, "send_magic_link": send.send_magic_link},
    )


async def run_notify_worker() -> None:
    from app.tasks import notify

    await _consume(NOTIFY_QUEUE, {"notify_upload": notify.notify_upload})


async def run_points_worker() -> None:
    from app.tasks import points_worker as pw

    await _consume(POINTS_QUEUE, {"apply_point_event": pw.apply_point_event})


async def run_default_worker() -> None:
    """jobs 队列 worker：消费 cron.cleanup / cron.reconcile（由调度进程发布）。"""
    from app.tasks import cleanup, reconcile_blog_repos

    await _consume(
        DEFAULT_QUEUE,
        {
            "cleanup_expired_uploads": cleanup.cleanup_expired_uploads,
            "reconcile_blog_repos": reconcile_blog_repos.reconcile_blog_repos,
        },
    )
