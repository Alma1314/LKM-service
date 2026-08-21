"""worker 配置测试：RedisSettings 由 redis_url 正确解析、发送 worker 用发送队列。"""

from typing import Any

from app.core import worker


def test_redis_settings_parses_url(monkeypatch: Any) -> None:
    monkeypatch.setattr(worker.settings, "redis_url", "redis://u:p@h1:7000/3")
    rs = worker._redis_settings()
    assert rs.host == "h1"
    assert rs.port == 7000
    assert rs.database == 3
    assert rs.username == "u"
    assert rs.password == "p"


def test_redis_settings_defaults(monkeypatch: Any) -> None:
    monkeypatch.setattr(worker.settings, "redis_url", "redis://localhost:6379/0")
    rs = worker._redis_settings()
    assert rs.host == "localhost"
    assert rs.port == 6379
    assert rs.database == 0
    assert rs.password is None


def test_send_worker_uses_send_queue() -> None:
    assert worker.SEND_QUEUE == "arq:queue:send"
    assert worker.SEND_FUNCTIONS[0].__name__ == "send_code"
    assert worker.SEND_FUNCTIONS[1].__name__ == "send_magic_link"
