"""ARQ worker 配置与入口：发送队列与默认队列各一个 worker。"""

import urllib.parse

from arq.connections import RedisSettings
from arq.worker import Worker

from app.core.config import settings
from app.tasks import send

SEND_QUEUE = "arq:queue:send"  # 高优发送队列
DEFAULT_QUEUE = "arq:queue"  # 默认队列，预留重活

SEND_FUNCTIONS = [send.send_code, send.send_magic_link]


def _redis_settings() -> RedisSettings:
    """把 settings.redis_url(redis://[u:p@]host:port[/db]) 解析为 RedisSettings。"""
    p = urllib.parse.urlparse(settings.redis_url)
    db = int((p.path or "/0").lstrip("/") or 0)
    return RedisSettings(
        host=p.hostname or "localhost",
        port=p.port or 6379,
        database=db,
        username=p.username,
        password=p.password,
    )


async def run_send_worker() -> None:
    """发送队列专属 worker（compose worker-send 入口）。"""
    w = Worker(SEND_FUNCTIONS, queue_name=SEND_QUEUE, max_tries=5, max_jobs=10)
    await w.async_run()


async def run_default_worker() -> None:
    """默认队列 worker（预留重活；compose worker 入口）。"""
    w = Worker([], queue_name=DEFAULT_QUEUE, max_tries=5, max_jobs=10)
    await w.async_run()
