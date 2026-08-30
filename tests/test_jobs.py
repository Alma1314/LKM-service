"""jobs 入队封装测试：入队优先，Redis 不可用/失败降级同步发送。"""

from typing import Any

import pytest

from app.core import jobs
from app.core import redis as redis_core


@pytest.fixture(autouse=True)
async def reset_jobs_pool() -> Any:
    """每用例前复位共享入队 pool，避免跨测试复用同一 fake/broken pool。"""
    await jobs.close_jobs_pool()
    jobs._pool = None
    yield
    await jobs.close_jobs_pool()
    jobs._pool = None


class _FakeJob:
    pass


class _FakePool:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.enqueued: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, func: str, *args: Any, **kwargs: Any) -> Any:
        if self.fail:
            raise RuntimeError("broker down")
        self.enqueued.append((func, args, kwargs))
        return _FakeJob()

    async def aclose(self) -> None:
        pass


async def test_send_code_enqueues_when_redis_ready(monkeypatch: Any) -> None:
    fake_pool = _FakePool()

    async def _fake_pool_maker(*a: Any, **k: Any) -> Any:
        return fake_pool

    async def _ready() -> Any:
        return object()

    monkeypatch.setattr(redis_core, "get_redis", _ready)
    monkeypatch.setattr(jobs, "create_pool", _fake_pool_maker)
    await jobs.send_code("email", "a@b.com", "123456")
    assert fake_pool.enqueued[0][0] == "send_code"
    assert fake_pool.enqueued[0][1] == ("email", "a@b.com", "123456")


async def test_send_code_falls_back_when_redis_none(monkeypatch: Any) -> None:
    sent: list[tuple[str, str]] = []

    class _Fake:
        async def send_code(self, c: str, code: str) -> None:
            sent.append((c, code))

    async def _none() -> Any:
        return None

    from app.modules.auth import channels as ch

    monkeypatch.setattr(ch, "CHANNELS", {"email": _Fake()})
    monkeypatch.setattr(redis_core, "get_redis", _none)
    await jobs.send_code("email", "a@b.com", "123456")
    assert sent == [("a@b.com", "123456")]


async def test_send_code_falls_back_when_enqueue_fails(monkeypatch: Any) -> None:
    called = False

    class _Fake:
        async def send_code(self, c: str, code: str) -> None:
            nonlocal called
            called = True

    async def _ready() -> Any:
        return object()

    async def _broken_pool(*a: Any, **k: Any) -> Any:
        raise RuntimeError("connect fail")

    from app.modules.auth import channels as ch

    monkeypatch.setattr(ch, "CHANNELS", {"email": _Fake()})
    monkeypatch.setattr(redis_core, "get_redis", _ready)
    monkeypatch.setattr(jobs, "create_pool", _broken_pool)
    await jobs.send_code("email", "a@b.com", "123456")  # 应降级、不抛
    assert called


async def test_send_magic_link_falls_back(monkeypatch: Any) -> None:
    sent: list[tuple[str, str]] = []

    class _Fake:
        async def send_magic_link(self, email: str, link: str) -> None:
            sent.append((email, link))

    async def _none() -> Any:
        return None

    from app.modules.auth import deps

    monkeypatch.setattr(deps, "get_email_provider", lambda: _Fake())
    monkeypatch.setattr(redis_core, "get_redis", _none)
    await jobs.send_magic_link("e@x.com", "https://link")
    assert sent == [("e@x.com", "https://link")]
