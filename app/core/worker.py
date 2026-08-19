"""ARQ worker 配置与入口：发送队列与默认队列各一个 worker。"""

import urllib.parse

from arq import cron
from arq.connections import RedisSettings
from arq.worker import Worker

from app.core.config import settings
from app.tasks import cleanup, notify, send


def _ensure_models() -> None:
    """预注册全部 ORM 模型，保证 worker 进程的 SQLAlchemy mapper 可完整解析。

    主进程经 ``app.main``→``app.api.router`` 全量加载各模块，连带注册其 ORM 模型；
    独立 arq worker（send/notify/default）只 import 用得到的任务链，不会进入那条路径。
    一旦 worker 首次实例化实体（如 ``LibraryFile``）触发 on-init 的 ``_check_configure``，
    会级联配置整个 registry，此时 ``User`` 上经 TYPE_CHECKING 引用的 relationship 目标
    （RefreshToken/ForumPost/BlogSeries/Column* 等）若未注册即抛 InvalidRequestError。
    这里在 worker 启动时预 import 各模型模块，复现主进程的全量注册。
    """

    # 各模块 ORM 模型（新增模块模型时必须在此登记，与 app.main 的 _register_all_errors 同理）
    import app.modules.auth.models
    import app.modules.blog.models
    import app.modules.columns.models
    import app.modules.files.models
    import app.modules.forum.models
    import app.modules.members.models  # noqa: F401  Profile 等

    # 确保 User.profile 等本文件内定义的 relationship target 也完成解析
    from app.db.models import Base

    # 触发一次 mapper 配置（幂等），把任何缺失提前暴露
    Base.registry.configure()


_ensure_models()

SEND_QUEUE = "arq:queue:send"  # 高优发送队列
NOTIFY_QUEUE = "arq:queue:notify"  # 对象事件通知队列
DEFAULT_QUEUE = "arq:queue"  # 默认队列，预留重活

SEND_FUNCTIONS = [send.send_code, send.send_magic_link]
NOTIFY_FUNCTIONS = [notify.notify_upload]


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


async def run_notify_worker() -> None:
    """对象事件通知队列专属 worker（compose worker-notify 入口，后续 Task 4 加入）。"""
    w = Worker(NOTIFY_FUNCTIONS, queue_name=NOTIFY_QUEUE, max_tries=5, max_jobs=10)
    await w.async_run()


async def run_default_worker() -> None:
    """默认队列 worker（预留重活 + 孤儿清扫周期任务；compose worker 入口）。"""
    w = Worker(
        [],
        queue_name=DEFAULT_QUEUE,
        max_tries=5,
        max_jobs=10,
        cron_jobs=[
            cron(cleanup.cleanup_expired_uploads, hour=set(range(24)), minute=0),  # 每小时整点清扫
        ],
    )
    await w.async_run()
