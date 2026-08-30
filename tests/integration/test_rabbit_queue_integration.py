"""RabbitMQ 集成测试：真实 Rabbit 下 publish → 消费拓扑成立。

默认排除（`-m integration`）。需 LKM_RABBIT_URL 指向可用 Rabbit，否则 skip。
"""

import asyncio
import json
import os
from typing import Any

import aio_pika
import pytest

from app.core import amqp, worker

pytestmark = pytest.mark.integration


async def _declare_test_exchange(ch: Any) -> None:
    await worker._declare_topology(ch)


async def test_publish_and_topology() -> None:
    url = os.environ.get("LKM_RABBIT_URL", "")
    if not url:
        pytest.skip("LKM_RABBIT_URL 为空")
    conn = await aio_pika.connect_robust(url)
    ch = await conn.channel()
    await _declare_test_exchange(ch)

    # 发布一条 send_code 事件（走模块共享 channel，按 settings.rabbit_url 连接）
    await amqp._publish(
        worker.RKEY_SEND_CODE,
        {"fn": "send_code", "args": ["email", "it@example.com", "123456"]},
    )

    # 验证 SEND_QUEUE 收到 1 条。用 burst 消费：get_queue 取句柄 → iterator 定时取 →
    # ack 空跑，避免把 CancelledError 混入 aio-pika 内部 consumer task。
    queue = await ch.get_queue(worker.SEND_QUEUE)
    got: list[str] = []

    async def _consume_one() -> None:
        async with queue.iterator() as it:
            async for msg in it:
                body = msg.body.decode()
                got.append(body)
                await msg.ack()
                if len(got) >= 1:
                    return

    await asyncio.wait_for(_consume_one(), timeout=10)

    await amqp.close_amqp()  # 复位模块共享 channel，避免泄漏到后续测试
    await ch.close()
    await conn.close()

    assert len(got) == 1, f"预期收到 1 条，实收 {len(got)}"
    payload = json.loads(got[0])
    assert payload["fn"] == "send_code"
