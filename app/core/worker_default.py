"""compose worker 服务入口：跑默认队列 worker。"""

import asyncio

from app.core.worker import run_default_worker


async def _main() -> None:
    await run_default_worker()


if __name__ == "__main__":
    asyncio.run(_main())
