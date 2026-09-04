"""M1.1 outbox 事务发件箱 + relay 验收。

与 conftest 的 client（内存 db 依赖覆盖）解耦：本文件自带静态 sqlite+aiosqlite+StaticPool
内存库。enqueue（业务会话）与 relay（session_factory 注入同一 engine）读写同一库，
避免 relay 默认走生产 new_session 而连到别的库、读不到内存行。
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import app.db.outbox  # noqa: F401  # 确保 OutboxMessage 已入 Base.metadata
from app.core import outbox_relay
from app.core.config import settings
from app.db.base import Base
from app.db.model_registry import ensure_all_models
from app.db.outbox import (
    MAX_TRIES,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_PUBLISHED,
    OutboxMessage,
    enqueue_outbox,
)

_RK = "event.apply_point"
_PAYLOAD = {"fn": "apply_point_event", "args": [7, "post", "item:9"]}


@pytest.fixture
async def engine() -> AsyncEngine:
    """隔离内存库：全量 ensure 模型（含 outbox_events）+ 该引擎独立建表。"""
    ensure_all_models()
    eng = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def fact(engine: AsyncEngine):
    """返回会话工厂：业务(enqueue/add) 与 relay session_factory 共用此引擎。"""
    maker = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)

    async def _new() -> AsyncSession:
        return maker()

    return _new


@pytest.fixture(autouse=True)
def _rabbit_on(monkeypatch) -> None:
    """本文件默认当“配置了 Rabbit”，放行 enqueue gate。"""
    monkeypatch.setattr(settings, "rabbit_url", "amqp://ci:5672")


async def _seed_one(fact, **row_kw) -> None:
    """enqueue 一条事件并提交。"""
    db = await fact()
    try:
        await enqueue_outbox(
            db,
            row_kw.pop("routing_key", _RK),
            row_kw.pop("payload", _PAYLOAD),
            event_id=None,
        )
        await db.commit()
    finally:
        await db.close()


async def _row(fact):
    db = await fact()
    try:
        return (await db.execute(sa.select(OutboxMessage))).scalars().one()
    finally:
        await db.close()


async def test_enqueue_persists_then_relay_publishes(fact, monkeypatch) -> None:
    sent: list[tuple[str, dict]] = []

    async def _pub(rk: str, payload: dict) -> bool:
        sent.append((rk, dict(payload)))
        return True

    monkeypatch.setattr(outbox_relay.amqp, "_publish", _pub)

    await _seed_one(fact)
    done = await outbox_relay.relay_poll(session_factory=fact)

    assert done == 1
    assert sent == [(_RK, _PAYLOAD)]
    row = await _row(fact)
    assert row.status == OUTBOX_PUBLISHED
    assert row.published_at is not None


async def test_enqueue_skips_when_rabbit_blank(fact, monkeypatch) -> None:
    monkeypatch.setattr(settings, "rabbit_url", "")
    db = await fact()
    try:
        assert await enqueue_outbox(db, _RK, _PAYLOAD) is False
        await db.commit()
    finally:
        await db.close()

    db2 = await fact()
    try:
        rows = (await db2.execute(sa.select(OutboxMessage))).scalars().all()
        assert rows == []
    finally:
        await db2.close()


async def test_enqueue_idempotent_by_event_id(fact) -> None:
    # 第一次加入并提交
    db = await fact()
    try:
        assert await enqueue_outbox(db, _RK, _PAYLOAD, event_id="dup-evt-1") is True
        await db.commit()
    finally:
        await db.close()

    # 第二次（新事务）同 event_id、仍 pending：跳过，不产生第二行
    db2 = await fact()
    try:
        assert await enqueue_outbox(db2, _RK, _PAYLOAD, event_id="dup-evt-1") is False
        await db2.commit()
        rows = (await db2.execute(sa.select(OutboxMessage))).scalars().all()
        assert len(rows) == 1
    finally:
        await db2.close()


async def test_relay_failure_backoff_then_recovery(fact, monkeypatch) -> None:
    calls = {"n": 0}

    async def _pub(_rk: str, _payload: dict) -> bool:
        calls["n"] += 1
        return calls["n"] >= 2  # 第 1 次失败、第 2 次成功

    monkeypatch.setattr(outbox_relay.amqp, "_publish", _pub)

    await _seed_one(fact)
    first = await outbox_relay.relay_poll(session_factory=fact)
    assert first == 0  # 首次失败未发布

    # 把重试时间拨回过去，让下一轮立即可领
    db = await fact()
    try:
        row = (await db.execute(sa.select(OutboxMessage))).scalars().one()
        assert row.status == OUTBOX_PENDING
        assert row.attempt_count == 1
        assert row.next_retry_at > datetime.now(UTC)  # 已退避到将来
        row.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    finally:
        await db.close()

    second = await outbox_relay.relay_poll(session_factory=fact)
    assert second == 1
    row = await _row(fact)
    assert row.status == OUTBOX_PUBLISHED
    assert row.attempt_count == 1  # 只投成功一次，无重复副作用


async def test_relay_marks_failed_at_max_tries(fact, monkeypatch) -> None:
    async def _fail(_rk: str, _payload: dict) -> bool:
        return False

    monkeypatch.setattr(outbox_relay.amqp, "_publish", _fail)

    # 预置 near-max（此刻即就绪）；一次失败后累到 MAX → failed 摘出，不再挤占后续轮
    db = await fact()
    m = OutboxMessage(
        event_id="near-max",
        routing_key=_RK,
        payload_json=json.dumps(_PAYLOAD),
        status=OUTBOX_PENDING,
        attempt_count=MAX_TRIES - 2,
    )
    try:
        db.add(m)
        await db.commit()
        # 逐轮失败（拨回 next_retry 就地即可领），直到 reaching failed
        for _ in range(2):
            row = (await db.execute(sa.select(OutboxMessage))).scalars().one()
            row.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
            await db.commit()
            await outbox_relay.relay_poll(session_factory=fact)
        row = (await db.execute(sa.select(OutboxMessage))).scalars().one()
        assert row.status == OUTBOX_FAILED
        assert row.attempt_count == MAX_TRIES
    finally:
        await db.close()
