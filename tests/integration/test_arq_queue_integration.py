"""ARQ 队列集成测试：真实 Redis 下入队 → 真实 burst Worker 消费。

要点：队列用 ZSET(实证 `enqueue_job` 内 `zadd`)，用 ZCARD 探测长度。
测试环境 provider 默认 console(打印不炸)，故 send_code 能成功执行、任务离队。
"""

import os

import pytest
from arq import create_pool
from arq.worker import Worker

from app.core.worker import SEND_FUNCTIONS, SEND_QUEUE, _redis_settings

pytestmark = pytest.mark.integration


async def _queue_len(pool, q: str) -> int:
    """arq 0.28 入队用 zadd(queue, {job_id: score})，故 ZCARD 探测队列长度。"""
    return int(await pool.execute_command("ZCARD", q))


async def test_enqueue_then_worker_consumes() -> None:
    url = os.environ.get("LKM_REDIS_URL", "")
    if not url:
        pytest.skip("LKM_REDIS_URL 为空")
    rs = _redis_settings()

    # 入队一个 send_code 任务到发送队列
    pool = await create_pool(rs, default_queue_name=SEND_QUEUE)
    job = await pool.enqueue_job(
        "send_code", "email", "it@example.com", "123456", _queue_name=SEND_QUEUE
    )
    assert job is not None
    assert await _queue_len(pool, SEND_QUEUE) >= 1

    # 用真实 burst Worker 消费发送队列（执行为 console provider，成功即离队）
    # Worker 须显式传 redis_settings，否则默认连 localhost:6379
    w = Worker(
        SEND_FUNCTIONS,
        queue_name=SEND_QUEUE,
        burst=True,
        max_tries=1,
        redis_settings=rs,
    )
    await w.async_run()

    # 消费后队列应清空（任务被取出并成功执行）
    assert await _queue_len(pool, SEND_QUEUE) == 0
    await pool.aclose()
