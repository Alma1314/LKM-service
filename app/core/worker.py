"""ARQ worker 配置与入口：发送队列与默认队列各一个 worker。"""

import urllib.parse

from arq import cron
from arq.connections import RedisSettings
from arq.worker import Worker

from app.core.config import settings
from app.tasks import cleanup, notify, points_worker, reconcile_blog_repos, send


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
    import app.modules.content.column_models  # 预 import Column StrEnum 常量
    import app.modules.files.models  # noqa: F401  # 副作用导入：预注册 ORM 模型（LibraryFile）

    # 确保 User.profile 等本文件内定义的 relationship target 也完成解析
    from app.db.models import Base

    # 触发一次 mapper 配置（幂等），把任何缺失提前暴露
    Base.registry.configure()


_ensure_models()

SEND_QUEUE = "arq:queue:send"  # 高优发送队列
NOTIFY_QUEUE = "arq:queue:notify"  # 对象事件通知队列
DEFAULT_QUEUE = "arq:queue"  # 默认队列，预留重活
POINTS_QUEUE = "arq:queue:points"  # 积分事件队列

# 单个任务的上限时长：超时即由 arq 判失败并按 max_tries 重试，防止 hung 任务
# 无限占用 worker 槽位。发送/通知/积分任务正常都远低于此。
_JOB_TIMEOUT_S = 120
# 超时后额外延长任务的"结束"宽限，给 cleanup/finish 留时间，避免被误收割。
_EXPIRES_EXTRA_MS = 5_000


def _base_worker_kwargs() -> dict[str, object]:
    """各 worker 共享的 ARQ 加固参数（超时 + 崩溃清理宽限）。

    ``**kwargs`` 展开 dict 时，ty 无法把不同 key 匹配到 Worker 的各自形参类型——
    展开后每个未显式传的形参都被推断成 keys 的统一值类型而误报。这是 ty 对运行时
    kwargs 展开的已知限制：即使把值类型收敛成 int，其他形参（bool/str/时区等）仍会被
    推断成 int 而报 invalid-argument-type。故调用侧逐个加 ``# ty: ignore`` 视为受控边界。
    """
    return {
        "job_timeout": _JOB_TIMEOUT_S,
        "expires_extra_ms": _EXPIRES_EXTRA_MS,
    }


SEND_FUNCTIONS = [send.send_code, send.send_magic_link]
NOTIFY_FUNCTIONS = [notify.notify_upload]
POINTS_FUNCTIONS = [points_worker.apply_point_event]


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
    w = Worker(
        SEND_FUNCTIONS,
        queue_name=SEND_QUEUE,
        redis_settings=_redis_settings(),
        max_tries=5,
        max_jobs=10,
        **_base_worker_kwargs(),  # ty: ignore[invalid-argument-type]  # kwargs 展开受限控边界，见 _base_worker_kwargs 注释
    )
    await w.async_run()


async def run_notify_worker() -> None:
    """对象事件通知队列专属 worker（compose worker-notify 入口，后续 Task 4 加入）。"""
    w = Worker(
        NOTIFY_FUNCTIONS,
        queue_name=NOTIFY_QUEUE,
        redis_settings=_redis_settings(),
        max_tries=5,
        max_jobs=10,
        **_base_worker_kwargs(),  # ty: ignore[invalid-argument-type]  # kwargs 展开受限控边界，见 _base_worker_kwargs 注释
    )
    await w.async_run()


async def run_default_worker() -> None:
    """默认队列 worker（预留重活 + 孤儿清扫周期任务；compose worker 入口）。"""
    w = Worker(
        [],
        queue_name=DEFAULT_QUEUE,
        redis_settings=_redis_settings(),
        max_tries=5,
        max_jobs=10,
        **_base_worker_kwargs(),  # ty: ignore[invalid-argument-type]  # kwargs 展开受限控边界，见 _base_worker_kwargs 注释
        cron_jobs=[
            cron(
                cleanup.cleanup_expired_uploads, hour=set(range(24)), minute=0
            ),  # 每小时整点清扫
            cron(
                reconcile_blog_repos.reconcile_blog_repos,
                weekday="thurs",
                hour=4,
                minute=0,
            ),  # 每周四 04:00 对账孤儿博客仓库
        ],
    )
    await w.async_run()


async def run_points_worker() -> None:
    """积分事件队列专属 worker（compose worker-points 入口）。"""
    w = Worker(
        POINTS_FUNCTIONS,
        queue_name=POINTS_QUEUE,
        redis_settings=_redis_settings(),
        max_tries=5,
        max_jobs=10,
        **_base_worker_kwargs(),  # ty: ignore[invalid-argument-type]  # kwargs 展开受限控边界，见 _base_worker_kwargs 注释
    )
    await w.async_run()
