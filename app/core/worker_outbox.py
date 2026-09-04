"""compose worker-outbox 服务入口：跑 outbox relay 单 owner poller（M1.1）。"""

import asyncio

from app.core.outbox_relay import run_outbox_loop


async def _main() -> None:
    await run_outbox_loop()


if __name__ == "__main__":
    asyncio.run(_main())
