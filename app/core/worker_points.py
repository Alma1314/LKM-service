"""compose worker-points 服务入口：跑积分事件队列 worker。"""

import asyncio

from app.core.worker import run_points_worker


async def _main() -> None:
    await run_points_worker()


if __name__ == "__main__":
    asyncio.run(_main())
