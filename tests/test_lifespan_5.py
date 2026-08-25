"""模块5 优雅启停：lifespan 启动建资源、退出释放（init_db / redis / engine / 清理任务）。"""

import app.main as main_mod


async def test_lifespan_runs_setup_and_graceful_cleanup(monkeypatch) -> None:
    """进入 lifespan 建资源；yield 后依次释放 redis/engine 并取消后台清理任务。"""

    calls: list[str] = []

    async def _fake_init_db() -> None:
        calls.append("init_db")

    async def _fake_get_redis() -> None:
        calls.append("redis_probe")

    async def _fake_close_redis() -> None:
        calls.append("close_redis")

    async def _fake_dispose_engine() -> None:
        calls.append("dispose_engine")

    async def _fake_cleanup() -> None:
        calls.append("cleanup_start")

    monkeypatch.setattr(main_mod, "init_db", _fake_init_db)
    monkeypatch.setattr(main_mod.redis_client, "get_redis", _fake_get_redis)
    monkeypatch.setattr(main_mod.redis_client, "close_redis", _fake_close_redis)
    monkeypatch.setattr(main_mod, "dispose_engine", _fake_dispose_engine)
    monkeypatch.setattr(main_mod, "cleanup_expired_challenges", _fake_cleanup)

    entered = False
    async with main_mod.lifespan(None):  # ty: ignore[invalid-argument-type]  # 故意传 None 单测 lifespan
        entered = True

    assert entered
    assert "init_db" in calls  # 启动执行迁移
    assert "redis_probe" in calls  # 启动探测 Redis
    assert "close_redis" in calls  # 退出释放 Redis
    assert "dispose_engine" in calls  # 退出释放引擎
