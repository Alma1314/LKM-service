"""任务入队封装：Redis 可用则入队；否则降级同步发送（fail-open，不丢）。"""

from typing import Any

from arq import create_pool

from app.core import redis as _redis
from app.core.worker import SEND_QUEUE, _redis_settings


async def _enqueue_or_none(func: str, *args: Any) -> bool:
    """入队到发送队列。Redis 不可用或入队异常返回 False（由调用方降级）。"""
    if await _redis.get_redis() is None:
        return False
    pool = None
    try:
        pool = await create_pool(_redis_settings(), default_queue_name=SEND_QUEUE)
        job = await pool.enqueue_job(func, *args, _queue_name=SEND_QUEUE)
        return job is not None
    except Exception:
        return False
    finally:
        if pool is not None:
            await pool.aclose()


async def send_code(channel_key: str, contact: str, code: str) -> None:
    """发送验证码：优先入队；Redis 不可用则降级同步发送。"""
    if await _enqueue_or_none("send_code", channel_key, contact, code):
        return
    from app.modules.auth.channels import CHANNELS

    await CHANNELS[channel_key].send_code(contact, code)


async def send_magic_link(email: str, link: str) -> None:
    """发送魔法链接：优先入队；Redis 不可用则降级同步发送。"""
    if await _enqueue_or_none("send_magic_link", email, link):
        return
    from app.modules.auth.deps import get_email_provider

    await get_email_provider().send_magic_link(email, link)
