"""compose worker-notify 服务入口：跑对象事件通知队列 worker。"""

import asyncio

from app.core.worker import run_notify_worker


async def _main() -> None:
    await run_notify_worker()


if __name__ == "__main__":
    asyncio.run(_main())
