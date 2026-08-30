"""APScheduler 独立调度进程：cron 到点发布 cron.* 消息到 RabbitMQ。

不直接执行任务——只把触发作为普通消息发布，由 DEFAULT_QUEUE worker 消费。
与消息系统解耦，Rabbit 不可用时发布 fail-open（日志+跳过），下次整点再触发。
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core import amqp

logger = logging.getLogger("lkm.scheduler")

RKEY_CLEANUP = "cron.cleanup"
RKEY_RECONCILE = "cron.reconcile"


async def _fire(routing_key: str, fn: str) -> None:
    ok = await amqp._publish(routing_key, {"fn": fn})
    if not ok:
        logger.warning("cron %s 发布失败(fail-open), fn=%s", routing_key, fn)


def build_scheduler() -> AsyncIOScheduler:
    """构建含两个 cron job 的调度器（cleanup 每小时整点 / reconcile 每周四 04:00）。

    *fn* 必须与 worker.run_default_worker 的 handler 键精确一致：
    ``cleanup_expired_uploads`` / ``reconcile_blog_repos``——否则 worker 按 fn 查表
    得 None 会当"未知任务"丢弃，cron 永远不执行。故这里显式传 fn，不在调度器里
    从 routing key 反推。
    """
    s = AsyncIOScheduler()
    s.add_job(
        _fire,
        CronTrigger(hour="*", minute=0),
        kwargs={"routing_key": RKEY_CLEANUP, "fn": "cleanup_expired_uploads"},
        id="cleanup_expired_uploads",
    )
    s.add_job(
        _fire,
        CronTrigger(day_of_week="thu", hour=4, minute=0),
        kwargs={"routing_key": RKEY_RECONCILE, "fn": "reconcile_blog_repos"},
        id="reconcile_blog_repos",
    )
    return s
