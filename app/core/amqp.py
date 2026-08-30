"""RabbitMQ 连接单例：生产侧统一入口，fail-open（未配置/连不上 → None/False）。

与 ``core.redis`` 的 fail-open 哲学一致：发布失败不阻塞请求，由调用方降级
（send 同步发送 / 事件静默 no-op）。共享一个 RobustChannel，RobustConnection
自动断线重连。消息经 *lkm.events* topic exchange 按 routing key 路由到队列。
"""

import asyncio
import json
import logging
from contextlib import suppress
from typing import cast

import aio_pika
import aio_pika.abc

from app.core.config import settings

logger = logging.getLogger("lkm.amqp")

EXCHANGE = "lkm.events"  # topic exchange，routing key event.* / cron.*

_channel: aio_pika.abc.AbstractRobustChannel | None = None
_lock = asyncio.Lock()


async def _connect_channel() -> aio_pika.abc.AbstractRobustChannel:
    """建立 RobustConnection 并取得 channel。仅内部测试可 monkeypatch 替换。"""
    conn = await aio_pika.connect_robust(settings.rabbit_url)
    # ty 对 aio_pika stub 的 channel() 仅解析为 AbstractChannel，无法精化到
    # RobustChannel；这里 cast 以保住共享 channel 的 Robust 重连语义。
    return cast(aio_pika.abc.AbstractRobustChannel, await conn.channel())


async def get_amqp() -> aio_pika.abc.AbstractRobustChannel | None:
    """懒初始化共享 channel；未配置返回 None。init 失败抛异常由调用方降级。"""
    global _channel
    if not settings.rabbit_url:
        return None
    if _channel is not None and not _channel.is_closed:
        return _channel
    async with _lock:
        if _channel is None or _channel.is_closed:
            _channel = await _connect_channel()
    return _channel


async def close_amqp() -> None:
    """幂等收尾：关闭共享 channel（应用 shutdown / 测试复位）。"""
    global _channel
    ch, _channel = _channel, None
    if ch is not None:
        with suppress(Exception):
            await ch.close()


async def amqp_ready() -> bool:
    """共享连接是否已就绪（未配置 → False）。"""
    if not settings.rabbit_url:
        return False
    ch = await get_amqp()
    return ch is not None and not ch.is_closed


async def _publish(routing_key: str, payload: dict) -> bool:
    """发布 JSON 消息到 lkm.events。fail-open：不可用/异常 → False。

    注意：**发布到具名 exchange `lkm.events`**（非 default_exchange）——default_exchange
    按"队列名"路由，而本拓扑按 routing key（event.*/cron.*）经 topic exchange 分流，
    若发 default_exchange 会 miss 到所有队列。declaration 幂等（Rabbit 允许多次同名）。
    """
    try:
        ch = await get_amqp()
        if ch is None:
            return False
        exchange = await ch.declare_exchange(
            EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
        )
        msg = aio_pika.Message(
            body=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await exchange.publish(msg, routing_key=routing_key)
        return True
    except Exception:
        logger.exception("rabbitmq publish failed rk=%s", routing_key)
        return False
