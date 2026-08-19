"""任务入队封装：Redis 可用则入队；否则降级同步发送（fail-open，不丢）。

对象事件通知入队为 fire-and-forget：无同步等价物，Redis 不可用时静默 no-op
（事件侧可经确认/重建恢复，遇 Redis 故障宁可丢弃也不阻塞回调 200 时序）。
"""

from typing import Any

from arq import create_pool

from app.core import redis as _redis
from app.core.worker import NOTIFY_QUEUE, SEND_QUEUE, _redis_settings


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


async def enqueue_upload_notify(upload_id: str) -> bool:
    """把对象事件入队到 notify 队列，待 worker 消费完成登记。

    Redis 不可用/入队失败一律静默 no-op 返回 False（fire-and-forget，不抛）：
    回调端点必须快速 200 确认，登记注册交给异步 worker；无同步等价物可降级。
    返回是否成功入队，供测试断言。
    """
    if await _redis.get_redis() is None:
        return False
    pool = None
    try:
        pool = await create_pool(_redis_settings(), default_queue_name=NOTIFY_QUEUE)
        job = await pool.enqueue_job(
            "notify_upload", upload_id, _queue_name=NOTIFY_QUEUE
        )
        return job is not None
    except Exception:
        return False
    finally:
        if pool is not None:
            await pool.aclose()
