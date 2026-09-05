"""RabbitMQ worker 配置与入口：注册表驱动的拓扑声明 + 通用消费者（计划 §6.2）。

四个独立 worker 进程（send/notify/points/jobs）各自 consume 一个队列，保留故障隔离。
业务队列配 x-dead-letter-exchange → 统一 DLQ，死信由 worker_dlq 落库。cron 由独立
APScheduler 进程发布 cron.* 消息到 DEFAULT_QUEUE 消费（run_default_worker 消费 cron key）。

任务归属由各模块 ``tasks.py`` 通过 ``task_registry.register_queue/register_task`` 声明；
本模块加载时调用 ``task_registry.import_task_modules()`` 触发注册，随后拓扑声明与
handler 分发都从注册表读取——**新增任务不再改本文件**。
"""

import asyncio
import json
import logging
from typing import Any

import aio_pika

from app.core import amqp, task_registry
from app.db.event_processed import already_processed, record_processed
from app.db.session import new_session

logger = logging.getLogger("lkm.worker")

JOB_TIMEOUT_S = 120  # 单任务执行上限，超时→死信重投

# 队列/拓扑常量（稳定标识，供部署编排与测试引用）
EXCHANGE = amqp.EXCHANGE  # lkm.events (topic)
SEND_QUEUE = "lkm.send"
NOTIFY_QUEUE = "lkm.notify"
POINTS_QUEUE = "lkm.points"
DEFAULT_QUEUE = "lkm.jobs"
DLX = "lkm.dlx"  # dead-letter exchange (fanout)
DLQ = "lkm.dlq"  # 统一死信队列

# routing key 常量（与 modules/*/tasks.py 的 ROUTING_KEYS 对齐，供发布侧引用）
RKEY_SEND_CODE = "event.send_code"
RKEY_SEND_MAGIC = "event.send_magic_link"
RKEY_NOTIFY = "event.notify_upload"
RKEY_POINTS = "event.apply_point"
RKEY_USER_UPDATED = "event.user.updated"
RKEY_USER_BANNED = "event.user.banned"
RKEY_USER_SESSION_REVOKE = "event.user.session_revoke"
RKEY_CLEANUP = "cron.cleanup"
RKEY_RECONCILE = "cron.reconcile"


def _ensure_models() -> None:
    """预注册全部 ORM 模型（防 worker 进程 SQLAlchemy mapper 缺失）。"""
    from app.db.model_registry import ensure_all_models

    ensure_all_models()


_ensure_models()
task_registry.import_task_modules()


async def _declare_topology(ch: Any) -> None:
    """幂等声明：exchange + 各业务队列(含 x-dead-letter) + DLX + DLQ，均来自注册表。

    注意 DLX 用 **FANOUT**：Rabbit 死信会把消息以【原始 routing key】republish 到
    x-dead-letter-exchange。若 DLX 是 DIRECT 且有零绑定，死信因 unroutable 被静默丢弃，
    进不到 DLQ。FANOUT 忽略 routing key、投递到所有绑定队列 → 绑定 DLQ 后任何死信都落库。
    """
    await ch.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
    await ch.declare_exchange(DLX, aio_pika.ExchangeType.FANOUT, durable=True)
    dlq = await ch.declare_queue(DLQ, durable=True)
    # 绑定 DLQ → DLX（fanout 忽略 key，"" 即通配全量）。缺这步死信会丢。
    await ch.bind_queue(dlq, DLX, "")
    # 业务队列与绑定由注册表驱动：queue -> routing keys
    for qname, rks in task_registry.topology().items():
        q = await ch.declare_queue(
            qname,
            durable=True,
            arguments={"x-dead-letter-exchange": DLX},
        )
        for rk in rks:
            await ch.bind_queue(q, EXCHANGE, rk)


async def _dispatch_with_dedup(
    payload: dict[str, Any], handler: Any, args: list[Any]
) -> None:
    """带 M1.3 幂等的任务分派（模块工具，供 _on_msg 闭包复用）。

    - payload 带 event_id（outbox relay 发布透传）→ 开临时会话查 event_processed：
      已处理 → 返回（外层对其 ack，不二次执行）；未处理 → 跑 handler，成功后记账。
    - 无 event_id（send/cron 等直发）→ 原语义直跑，不经 DB，零额外开销。
    - event_id 在且查账/记账时 DB 异常 → 记日志并令外层视「首次未记账」处理（宁可重试
      也不丢），由既有 DLQ/超时语义兜底，不卡后续消息。
    """
    eid = payload.get("event_id")
    if not isinstance(eid, str) or not eid:
        await handler(*args)
        return
    db = await new_session()
    try:
        try:
            if await already_processed(db, eid):
                logger.info("outbox 幂等跳过已处理 event_id=%s", eid)
                return  # ack，不重复执行 handler
        except Exception:
            # 账本查不动：保守当作未记账，继续执行，避免一旦 DB 抖动业务停摆。
            logger.exception("event_processed 查账失败,继续执行 event_id=%s", eid)
        await handler(*args)
        try:
            await record_processed(db, eid)
        except Exception:
            # 记账失败(罕见)：已跑过一次副作用，宁可让 DLQ requeue 重试走幂等查账兜底。
            logger.exception("event_processed 记账失败 event_id=%s", eid)
            raise
    finally:
        await db.close()


async def _consume(queue_name: str) -> None:
    """消费指定队列，按 payload.fn 从注册表分发 handler。任务执行包 120s 超时。

    handler 成功 → ack；异常/超时 → nack(requeue=False) → 死信 DLQ。
    拓扑由 _declare_topology 统一幂等声明；注销本队列的 handler 语义由注册表提供。

    M1.3 幂等：对带 ``event_id`` 的消息（outbox relay 发布时透传），消费前查
    `event_processed` 账本——已处理 → ack 跳过（重放/DLQ requeue 不再二次副作用）；
    未处理 → 执行 handler，成功后记账。无 event_id 的直发/cron 消息照常，不走去重。
    """
    handlers = task_registry.handlers_for(queue_name)
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
                    logger.warning(
                        "队列入队消息非法 JSON, 丢弃 queue=%s body=%r",
                        queue_name,
                        msg.body,
                    )
                    return  # ack 丢弃坏消息, 避免死信风暴
                fn = payload.get("fn")
                args = payload.get("args", [])
                handler = handlers.get(fn) if isinstance(fn, str) else None
                if handler is None:
                    logger.warning("未知任务 %s, 丢弃", fn)
                    return  # ack 丢弃
                # M1.3 幂等：带 event_id 的消息走“查账→执行→记账”，其余按原语义直跑。
                # handler 抛错仍由外层 except 兜到死信（此处不吞），不卡后续消息。
                await _dispatch_with_dedup(payload, handler, args)
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
# 各 worker 仅需消费对应队列：handler 表与拓扑均由注册表提供。


async def run_send_worker() -> None:
    await _consume(SEND_QUEUE)


async def run_notify_worker() -> None:
    await _consume(NOTIFY_QUEUE)


async def run_points_worker() -> None:
    await _consume(POINTS_QUEUE)


async def run_default_worker() -> None:
    """jobs 队列 worker：消费 cron.cleanup / cron.reconcile（由调度进程发布）。"""
    await _consume(DEFAULT_QUEUE)
