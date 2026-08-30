import pytest

from app.core.config import Settings


def test_rabbit_url_default_empty() -> None:
    s = Settings(env="test")
    assert s.rabbit_url == ""


def test_rabbit_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LKM_RABBIT_URL", "amqp://u:p@h:5672/vh")
    s = Settings(env="test")
    assert s.rabbit_url == "amqp://u:p@h:5672/vh"
