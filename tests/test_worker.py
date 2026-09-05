"""worker 配置测试：队列命名、拓扑声明幂等、消费者装配。"""

from typing import Any

from app.core import worker


def test_queue_naming() -> None:
    assert worker.SEND_QUEUE == "lkm.send"
    assert worker.NOTIFY_QUEUE == "lkm.notify"
    assert worker.POINTS_QUEUE == "lkm.points"
    assert worker.DEFAULT_QUEUE == "lkm.jobs"
    assert worker.EXCHANGE == "lkm.events"


async def test_declare_topology_declares_queues_and_dlx() -> None:
    declared_exchanges: list[str] = []
    declared_queues: list[tuple[str, dict]] = []
    bound: list[tuple[str, str, str]] = []

    class _FakeQueue:
        def __init__(self, name: str) -> None:
            self.name = name

    class _FakeChan:
        async def declare_exchange(self, name: str, typ: Any, **kw: Any) -> Any:
            declared_exchanges.append(name)
            return None

        async def declare_queue(self, name: str, **kw: Any) -> _FakeQueue:
            declared_queues.append((name, dict(kw)))
            return _FakeQueue(name)

        async def bind_queue(self, q: Any, exchange: str, routing_key: str) -> None:
            bound.append((q.name, exchange, routing_key))

    fake = _FakeChan()
    await worker._declare_topology(fake)  # type: ignore[arg-type]
    assert worker.EXCHANGE in declared_exchanges
    assert worker.DLX in declared_exchanges
    names = [n for n, _ in declared_queues]
    assert worker.SEND_QUEUE in names
    assert worker.NOTIFY_QUEUE in names
    assert worker.POINTS_QUEUE in names
    assert worker.DEFAULT_QUEUE in names
    assert worker.DLQ in names
    send_args = dict(declared_queues)[worker.SEND_QUEUE]
    assert send_args["arguments"]["x-dead-letter-exchange"] == worker.DLX
    # DLQ 是直连死信队列, 不设 x-dead-letter（避免死信再死信）
    dlq_args = dict(declared_queues)[worker.DLQ]
    assert "x-dead-letter-exchange" not in dlq_args.get("arguments", {})
    # 每条业务队列都绑定到 exchange（send(2) notify(1) points(1) jobs(5)）+ DLQ→DLX(1)。
    # jobs 列 = cron.reconcile + cron.cleanup + 三条 auth user 事件(event.user.{updated,banned,session_revoke})，
    # 见 app/modules/auth/tasks.py 的 ROUTING_KEYS_SNAP；此处如实反映现行拓扑。
    send_keys = {b[2] for b in bound if b[0] == worker.SEND_QUEUE}
    assert send_keys == {"event.send_code", "event.send_magic_link"}
    jobs_keys = {b[2] for b in bound if b[0] == worker.DEFAULT_QUEUE}
    assert {
        "cron.reconcile",
        "cron.cleanup",
        "event.user.updated",
        "event.user.banned",
        "event.user.session_revoke",
    } <= jobs_keys
    assert len(bound) == 2 + 1 + 1 + 5 + 1
    # DLQ 必须绑定到 DLX（fanout，死信消息按原始 rk republish 到 DLX → 落 DLQ；
    # 缺这步死信会因 unroutable 被静默丢弃）。显式断言这一关键路由存在。
    dlq_binds = [b for b in bound if b[0] == worker.DLQ]
    assert len(dlq_binds) == 1
    assert dlq_binds[0][1] == worker.DLX  # exchange 是 DLX

