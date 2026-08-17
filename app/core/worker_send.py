"""compose worker-send 服务入口：跑发送队列 worker。"""

import asyncio

from app.core.worker import run_send_worker


async def _main() -> None:
    await run_send_worker()


if __name__ == "__main__":
    asyncio.run(_main())
