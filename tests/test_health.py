"""可观测基座（模块0）：/health 聚合 DB+Redis 状态。"""

from app.modules.health.router import DependencyStatus


async def test_health_endpoint_aggregates_status(client, monkeypatch) -> None:
    """health 端点把 db/redis 状态聚合进响应体。db up + redis disabled → degraded。"""

    import app.modules.health.router as health_mod

    async def _fake_probe_db() -> DependencyStatus:
        return DependencyStatus(status="up")

    async def _fake_probe_redis() -> DependencyStatus:
        return DependencyStatus(status="disabled", detail="未配置")

    monkeypatch.setattr(health_mod, "_probe_db", _fake_probe_db)
    monkeypatch.setattr(health_mod, "_probe_redis", _fake_probe_redis)

    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    payload: dict = resp.json()
    assert payload["data"]["db"]["status"] == "up"
    assert payload["data"]["redis"]["status"] == "disabled"
    assert payload["data"]["status"] == "degraded"
