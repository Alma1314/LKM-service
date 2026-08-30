"""任务入队封装：Rabbit 可用则入队；否则降级同步发送（fail-open，不丢）。

对象事件通知入队为 fire-and-forget：无同步等价物，Rabbit 不可用时静默 no-op
（事件侧可经确认/重建恢复，遇故障宁可丢弃也不阻塞回调 200 时序）。
"""

import asyncio
import logging
from typing import Any

from app.core import amqp

logger = logging.getLogger("lkm.jobs")

RKEY_SEND_CODE = "event.send_code"
RKEY_SEND_MAGIC = "event.send_magic_link"
RKEY_NOTIFY = "event.notify_upload"
RKEY_POINTS = "event.apply_point"

# 降级同步发送的上限时长（同旧实现）。
_SEND_TIMEOUT_S = 10.0


async def _enqueue(fn: str, *args: Any, routing_key: str) -> bool:
    """发 JSON 消息到 lkm.events。不可用/异常返回 False（由调用方降级）。"""
    try:
        return await amqp._publish(routing_key, {"fn": fn, "args": list(args)})
    except Exception:
        # amqp._publish 内已 fail-open 捕获异常返回 False；此处兜底以防极少数
        # 直接抛出的情况（如测试注入），保持一致：异常视为入队失败 → 降级。
        logger.exception("enqueue %s failed", fn)
        return False


async def _degraded_send(coro_factory: Any, *, kind: str) -> None:
    try:
        await asyncio.wait_for(coro_factory(), timeout=_SEND_TIMEOUT_S)
    except TimeoutError:
        logger.warning("degraded %s send timed out after %ss", kind, _SEND_TIMEOUT_S)
    except Exception:
        logger.exception("degraded %s send failed", kind)


async def send_code(channel_key: str, contact: str, code: str) -> None:
    if await _enqueue("send_code", channel_key, contact, code, routing_key=RKEY_SEND_CODE):
        return
    from app.modules.auth.channels import CHANNELS

    await _degraded_send(
        lambda: CHANNELS[channel_key].send_code(contact, code), kind="code"
    )


async def send_magic_link(email: str, link: str) -> None:
    if await _enqueue("send_magic_link", email, link, routing_key=RKEY_SEND_MAGIC):
        return
    from app.modules.auth.deps import get_email_provider

    await _degraded_send(
        lambda: get_email_provider().send_magic_link(email, link), kind="magic_link"
    )


async def enqueue_upload_notify(upload_id: str) -> bool:
    return await _enqueue("notify_upload", upload_id, routing_key=RKEY_NOTIFY)
