"""B1.1 AUTH 独立进程：main_auth 可导入装配 + 专属 liveness/readiness 健康缝。

不依赖真实 DB/Redis（liveness 本就零外部依赖；readiness 用 monkeypatch 替换探子成
up/disabled 回报，保持 hermetic，不触碰真实 lkm.db / 外部 redis）。
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

import app.health_auth as health_auth
import app.main_auth  # 顶层 `app = create_auth_app()` 即验证入口可装配
from app.health_auth import AuthDepStatus


@pytest.fixture
async def auth_client() -> AsyncGenerator[AsyncClient]:
    """httpx 客户端直挂 auth-only ASGI 应用；不触发 app.lifespan，零外部副作用。"""
    transport = ASGITransport(app=app.main_auth.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_auth_entry_imports_and_app_assembles() -> None:
    """main_auth 顶层装配成功：进程入口可被 import，且健康 router 只携带所命两个端点。"""
    # main_auth 顶层 `app = create_auth_app()` 已跑过 → import 即装配成功。
    # health router 直接定义 /liveness 与 /readiness（挂载进 app 后子 router 惰性展开）。
    from fastapi.routing import APIRoute

    paths = {r.path for r in health_auth.router.routes if isinstance(r, APIRoute)}
    assert {"/liveness", "/readiness"} <= paths
    # auth 域每个 router 都被聚合进了本进程装配清单（B1.2 内部读缝 + M3.B S2 内部授权写缝 → 9）
    assert len(app.main_auth._AUTH_ROUTERS) == 9


async def test_liveness_returns_ok_without_external_deps(auth_client) -> None:
    """liveness 自足：无 DB/Redis 也可达且返回 ok。"""
    resp = await auth_client.get("/liveness")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "auth"


async def test_readiness_degraded_when_db_down_redis_up(
    auth_client, monkeypatch
) -> None:
    """readiness 聚合探子状态：db error + redis up → degraded（探子被替换，hermetic）。"""

    async def _db_err() -> AuthDepStatus:
        return AuthDepStatus(status="error", detail="boom")

    async def _redis_up() -> AuthDepStatus:
        return AuthDepStatus(status="up")

    monkeypatch.setattr(health_auth, "probe_db", _db_err)
    monkeypatch.setattr(health_auth, "probe_redis", _redis_up)

    resp = await auth_client.get("/readiness")
    assert resp.status_code == 200
    p = resp.json()
    assert p["status"] == "degraded"
    assert p["db"]["status"] == "error"
    assert p["redis"]["status"] == "up"


async def test_readiness_ok_when_both_up(auth_client, monkeypatch) -> None:
    """db up + redis up → ok（探子替换返回，无需真实外部依赖）。"""

    async def _up() -> AuthDepStatus:
        return AuthDepStatus(status="up")

    monkeypatch.setattr(health_auth, "probe_db", _up)
    monkeypatch.setattr(health_auth, "probe_redis", _up)

    resp = await auth_client.get("/readiness")
    assert resp.status_code == 200
    p = resp.json()
    assert p["status"] == "ok"
    assert p["db"]["status"] == "up"
    assert p["redis"]["status"] == "up"
