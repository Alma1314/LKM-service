"""认证与用户档案模块：登录/OAuth/2FA/passkey/恢复/引导/设置。

模块公共 API——跨模块 import 的唯一合法入口。所有 router 均惰性 import，
保证 `import app.modules.auth` 绝对轻量且零循环。
"""

from __future__ import annotations

from typing import Any

_exported_routers: list[Any] | None = None
_exported_graphql: list[Any] | None = None
_exported_snapshot: Any | None = None


def __getattr__(name: str) -> Any:
    global _exported_routers, _exported_graphql, _exported_snapshot
    # 统一只读身份缝（A1）：惰性载入，保持 `import app.modules.auth` 绝对轻量零循环。
    # 业务域展示性身份读取只经 auth.snapshot（见 M3 spec 读缝契约）。
    if name in ("UserSnapshot", "get_user_snapshot", "get_user_snapshot_batch"):
        if _exported_snapshot is None:
            from app.modules.auth import snapshot as _exported_snapshot
        return getattr(_exported_snapshot, name)
    if name == "ROUTERS":
        if _exported_routers is None:
            from app.modules.auth.router import router
            from app.modules.auth.router_2fa import router as router_2fa
            from app.modules.auth.router_oauth import router as router_oauth
            from app.modules.auth.router_onboarding import router as router_onboarding
            from app.modules.auth.router_passkey import router as router_passkey
            from app.modules.auth.router_read import (
                router as router_read,  # B1.2 内部读面
            )
            from app.modules.auth.router_recovery import router as router_recovery
            from app.modules.auth.router_settings import router as router_settings

            _exported_routers = [
                router,
                router_2fa,
                router_oauth,
                router_onboarding,
                router_passkey,
                router_read,
                router_recovery,
                router_settings,
            ]
        return _exported_routers
    if name == "GRAPHQL":
        if _exported_graphql is None:
            _exported_graphql = []
        return _exported_graphql
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
