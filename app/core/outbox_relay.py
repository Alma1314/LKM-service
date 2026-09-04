"""outbox relay：领取 pending 事件投递到消息总线并置 published（M1.1）。

单 owner：relay 跑在单个独立进程（compose worker-outbox），本功能只作单进程串行 poller，
无 Redis/DB 租约 —— 多副本接管属 M1.2。投递语义=`amqp._publish` 成功即 published（无
broker publish-confirm，publisher-confirm 后续增强）。未配置 Rabbit → enqueue 已被
`app/db/outbox.enqueue_outbox` gate 掉不会入队，因此本 poll 也空转退出，与现有 worker
"无 rabbit 降级空转返回" 一致。

`relay_poll` 刻意收敛为**纯函数**（不启动任何循环/会话生命周期），单测经 monkeypatch /
`new_session` seam 注入即可直接驱动。
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import amqp
from app.core.config import settings
from app.core.metrics import outbox_pending_count
from app.db.outbox import (
    _BACKOFF_CAP_S,
    MAX_TRIES,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_PUBLISHED,
    OutboxMessage,
)
from app.db.session import new_session

logger = logging.getLogger("lkm.outbox")

# 会话工厂类型：relay_poll 允许单测注入独立内存库会话，默认走生产 async_session(new_session)
SessionFactory = Callable[..., Awaitable[AsyncSession]]


async def relay_poll(
    batch: int = 100, *, session_factory: SessionFactory | None = None
) -> int:
    """扫一批到期的 pending 事件投递；返回本轮成功(published)事件数。

    语义：
    - 领取窗口 = `status=pending AND next_retry_at<=now`，按 attempt 升序（少重试者在先）。
    - 投递（`amqp._publish(routing_key, parsed)`）成功 → `published_at=now, status=published`。
    - 失败/异常 → `attempt_count += 1`；达 `MAX_TRIES` 置 `failed`（不再投），否则指数退避
      `next_retry_at = now + 2**attempt s`（cap 1h）保持 pending 待下轮。
    - 每事件独立 flush/commit，单条失败不影响其余。
    - 可观测（M0.5.2）：每轮末尾统计表内仍 `status=pending`（含退避等待下一轮）件数
      set 到 `outbox_pending_count` gauge 供积压看板。投递失败计数不在此重复——提交经
      `amqp._publish`，其抛出/不可用路径已由 amqp 层自身计 `notify_failed_total`。
    """
    factory = session_factory or new_session
    db = await factory()
    succeeded = 0
    try:
        now = datetime.now(UTC)
        rows = list(
            (
                await db.execute(
                    select(OutboxMessage)
                    .where(
                        OutboxMessage.status == OUTBOX_PENDING,
                        OutboxMessage.next_retry_at <= now,
                    )
                    .order_by(OutboxMessage.attempt_count.asc(), OutboxMessage.id.asc())
                    .limit(batch)
                )
            )
            .scalars()
            .all()
        )
        for msg in rows:
            try:
                payload = json.loads(msg.payload_json)
                ok = await amqp._publish(msg.routing_key, payload)
            except Exception:
                logger.exception(
                    "outbox publish exception id=%s rk=%s", msg.id, msg.routing_key
                )
                ok = False

            if ok:
                msg.status = OUTBOX_PUBLISHED
                msg.published_at = datetime.now(UTC)
                succeeded += 1
                await db.commit()
                continue

            msg.attempt_count += 1
            if msg.attempt_count >= MAX_TRIES:
                # 达上限不再投；status 摘成 failed，relay 不再扫（next_retry 已失去意义但须非空）
                msg.status = OUTBOX_FAILED
                msg.next_retry_at = datetime.now(UTC)
            else:
                # 指数退避（cap 1h）保持 pending 待下轮；幂等靠唯一 event_id，不重复入队
                msg.next_retry_at = datetime.now(UTC) + timedelta(
                    seconds=min(2 ** int(msg.attempt_count), _BACKOFF_CAP_S)
                )
            await db.commit()
        if rows and succeeded:
            logger.info("outbox relay 本轮成功 %s 条", succeeded)
        return succeeded
    finally:
        # 积压 gauge：会话仍可分页前统计一遍仍 pending 的件数（含本轮退避、failed 摘除后的剩
        # 余 pending）。统计失败仅记日志（gauge 保上次值），不扰动本应有的 relay 语义。
        try:
            pending_left = await db.scalar(
                select(func.count())
                .select_from(OutboxMessage)
                .where(OutboxMessage.status == OUTBOX_PENDING)
            )
            outbox_pending_count.set(pending_left or 0)
        except Exception:
            logger.exception("outbox pending gauge 统计失败，保留上次值")
        await db.close()


async def run_outbox_loop(interval_s: float = 2.0) -> None:
    """独立进程主循环：周期 poll outbox（未配置 rabbit 空转退出，语义同 worker）。"""
    if not settings.rabbit_url:
        logger.error("rabbitmq 不可用，outbox relay 空转退出")
        return
    logger.info("outbox relay 启动（interval=%ss）", interval_s)
    while True:
        try:
            await relay_poll()
        except Exception:
            logger.exception("outbox relay_poll 异常，下轮重试")
        await asyncio.sleep(interval_s)
