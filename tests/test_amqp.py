from typing import Any

import aio_pika
import pytest

from app.core import amqp


@pytest.fixture(autouse=True)
async def _reset() -> Any:
    await amqp.close_amqp()
    yield
    await amqp.close_amqp()


async def test_amqp_not_configured_returns_none(monkeypatch: Any) -> None:
    monkeypatch.setattr(amqp.settings, "rabbit_url", "")
    assert await amqp.get_amqp() is None
    assert await amqp.amqp_ready() is False


async def test_publish_fails_open_when_not_configured(monkeypatch: Any) -> None:
    monkeypatch.setattr(amqp.settings, "rabbit_url", "")
    assert await amqp._publish("event.send_code", {"fn": "send_code", "args": [1]}) is False


async def test_publish_publishes_to_channel(monkeypatch: Any) -> None:
    published: list[tuple] = []
    declared: list[tuple] = []

    class _FakeExchange:
        async def publish(self, msg: Any, routing_key: str) -> None:
            published.append((msg.body, routing_key))

    class _FakeChan:
        async def declare_exchange(self, name: str, typ: Any, **kw: Any) -> Any:
            declared.append((name, typ))
            return _FakeExchange()

    fake = _FakeChan()
    monkeypatch.setattr(amqp.settings, "rabbit_url", "amqp://h:5672/")

    async def _fake_connect() -> Any:
        return fake

    monkeypatch.setattr(amqp, "_connect_channel", _fake_connect)
    ok = await amqp._publish(
        "event.send_code",
        {"fn": "send_code", "args": ["email", "a@b.com", "123"]},
    )
    assert ok is True
    # 发布必须落到具名 lkm.events topic exchange（而非 default_exchange / 改名）
    assert len(declared) == 1
    assert declared[0][0] == amqp.EXCHANGE
    assert declared[0][1] == aio_pika.ExchangeType.TOPIC
    assert published[0][1] == "event.send_code"
