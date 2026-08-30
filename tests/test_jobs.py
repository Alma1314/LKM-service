"""jobs 入队封装测试：入队优先，Rabbit 不可用/失败降级同步发送。"""

from typing import Any

import pytest

from app.core import amqp, jobs


@pytest.fixture(autouse=True)
async def reset_amqp() -> Any:
    """每用例前复位共享 amqp 连接，避免跨测试复用同一 fake/broken 状态。"""
    await amqp.close_amqp()
    yield
    await amqp.close_amqp()


async def _patch_publish(monkeypatch: Any, *, fail: bool = False) -> list[tuple]:
    """monkeypatch amqp._publish 返回可检查的列表。"""
    published: list[tuple] = []

    async def fake_pub(rk: str, payload: dict) -> bool:
        if fail:
            raise RuntimeError("broker down")
        published.append((rk, payload))
        return True

    monkeypatch.setattr(amqp, "_publish", fake_pub)
    return published


async def test_send_code_enqueues(monkeypatch: Any) -> None:
    published = await _patch_publish(monkeypatch)
    await jobs.send_code("email", "a@b.com", "123456")
    rk, payload = published[0]
    assert rk == jobs.RKEY_SEND_CODE
    assert payload == {"fn": "send_code", "args": ["email", "a@b.com", "123456"]}


async def test_send_code_falls_back_when_publish_false(monkeypatch: Any) -> None:
    sent: list[tuple[str, str]] = []

    class _Fake:
        async def send_code(self, c: str, code: str) -> None:
            sent.append((c, code))

    async def fake_pub(rk: str, payload: dict) -> bool:
        return False  # 未配置/失败 → fail-open 返回 False

    from app.modules.auth import channels as ch

    monkeypatch.setattr(amqp, "_publish", fake_pub)
    monkeypatch.setattr(ch, "CHANNELS", {"email": _Fake()})
    await jobs.send_code("email", "a@b.com", "123456")
    assert sent == [("a@b.com", "123456")]


async def test_send_code_falls_back_when_publish_raises(monkeypatch: Any) -> None:
    called = False

    class _Fake:
        async def send_code(self, c: str, code: str) -> None:
            nonlocal called
            called = True

    async def broken_pub(rk: str, payload: dict) -> bool:
        raise RuntimeError("connect fail")

    from app.modules.auth import channels as ch

    monkeypatch.setattr(amqp, "_publish", broken_pub)
    monkeypatch.setattr(ch, "CHANNELS", {"email": _Fake()})
    await jobs.send_code("email", "a@b.com", "123456")  # 应降级、不抛
    assert called


async def test_send_magic_link_falls_back(monkeypatch: Any) -> None:
    sent: list[tuple[str, str]] = []

    class _Fake:
        async def send_magic_link(self, email: str, link: str) -> None:
            sent.append((email, link))

    async def fake_pub(rk: str, payload: dict) -> bool:
        return False

    from app.modules.auth import deps

    monkeypatch.setattr(amqp, "_publish", fake_pub)
    monkeypatch.setattr(deps, "get_email_provider", lambda: _Fake())
    await jobs.send_magic_link("e@x.com", "https://link")
    assert sent == [("e@x.com", "https://link")]


async def test_enqueue_upload_notify_rk(monkeypatch: Any) -> None:
    published = await _patch_publish(monkeypatch)
    assert await jobs.enqueue_upload_notify("up123") is True
    assert published[0][0] == jobs.RKEY_NOTIFY
    assert published[0][1]["args"] == ["up123"]
