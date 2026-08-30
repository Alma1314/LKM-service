"""任务入队封装：Redis 可用则入队；否则降级同步发送（fail-open，不丢）。

对象事件通知入队为 fire-and-forget：无同步等价物，Redis 不可用时静默 no-op
（事件侧可经确认/重建恢复，遇 Redis 故障宁可丢弃也不阻塞回调 200 时序）。
"""

import asyncio
import logging
from contextlib import suppress
from typing import Any

from arq import create_pool

from app.core import redis as _redis
from app.core.worker import NOTIFY_QUEUE, SEND_QUEUE, _redis_settings

logger = logging.getLogger("lkm.jobs")

# 懒初始化的共享 ArqRedis pool：入队高频（验证码/事件逐次调用），复用一个连接池避免
# 每次入队都重建 Redis 连接（TCP 握手 + 池初始化开销）。进程内全局单例。
_pool: Any = None

# 降级同步发送的上限时长：Redis 故障时仍尽力当场发送（保可用性），但邮件/短信服务
# 若慢或卡死，超时即放弃返回，避免拖住验证码/登录请求 RT。
_SEND_TIMEOUT_S = 10.0


async def _get_pool(queue: str) -> Any:
    """懒初始化并缓存共享 pool；失败抛异常由调用方降级。"""
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings(), default_queue_name=queue)
    return _pool


async def close_jobs_pool() -> None:
    """收尾：关闭共享 pool 并清空（应用 shutdown 或测试复位调用）。幂等。"""
    global _pool
    pool, _pool = _pool, None
    if pool is not None:
        with suppress(Exception):
            await pool.aclose()


async def _enqueue(func: str, *args: Any, queue: str) -> bool:
    """入队到指定队列。Redis 不可用或入队异常返回 False（由调用方降级）。"""
    if await _redis.get_redis() is None:
        return False
    try:
        pool = await _get_pool(queue)
        job = await pool.enqueue_job(func, *args, _queue_name=queue)
        return job is not None
    except Exception:
        return False


async def _degraded_send(coro_factory: Any, *, kind: str) -> None:
    """降级同步发送：带超时上限，慢/卡死的通道不拖住请求（尽力而为 + 记日志）。"""
    try:
        await asyncio.wait_for(coro_factory(), timeout=_SEND_TIMEOUT_S)
    except TimeoutError:
        logger.warning("degraded %s send timed out after %ss", kind, _SEND_TIMEOUT_S)
    except Exception:
        logger.exception("degraded %s send failed", kind)


async def send_code(channel_key: str, contact: str, code: str) -> None:
    """发送验证码：优先入队；Redis 不可用则降级同步发送（带超时）。"""
    if await _enqueue("send_code", channel_key, contact, code, queue=SEND_QUEUE):
        return
    from app.modules.auth.channels import CHANNELS

    await _degraded_send(
        lambda: CHANNELS[channel_key].send_code(contact, code), kind="code"
    )


async def send_magic_link(email: str, link: str) -> None:
    """发送魔法链接：优先入队；Redis 不可用则降级同步发送（带超时）。"""
    if await _enqueue("send_magic_link", email, link, queue=SEND_QUEUE):
        return
    from app.modules.auth.deps import get_email_provider

    await _degraded_send(
        lambda: get_email_provider().send_magic_link(email, link), kind="magic_link"
    )


async def enqueue_upload_notify(upload_id: str) -> bool:
    """把对象事件入队到 notify 队列，待 worker 消费完成登记。

    Redis 不可用/入队失败一律静默 no-op 返回 False（fire-and-forget，不抛）：
    回调端点必须快速 200 确认，登记注册交给异步 worker；无同步等价物可降级。
    返回是否成功入队，供测试断言。
    """
    return await _enqueue("notify_upload", upload_id, queue=NOTIFY_QUEUE)
