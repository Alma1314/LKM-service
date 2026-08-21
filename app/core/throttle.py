"""登录限流：委托 Redis 滑动窗口限流器；Redis 不可用时放行（fail-open）。

限流参数（IP/全局次数、窗口秒）统一读 settings（LKM_LOGIN_* 可覆盖），见
backend_auth_security 记忆。
"""

from app.core.config import settings
from app.core.err import BizError
from app.core.redis_limiter import RedisRateLimiter
from app.modules.auth.errors import AuthErr


async def check_password_login_rate_limit(ip_address: str) -> None:
    """对密码登录尝试应用 IP 和全局限流。Redis 不可用时静默放行。"""
    limiter = RedisRateLimiter()
    if not await limiter.check(
        "__global__", settings.login_global_max_per_min, settings.login_window_seconds
    ):
        raise BizError(
            AuthErr.ACCOUNT_LOCKED, "Too many login attempts, please try again later"
        )
    if ip_address and not await limiter.check(
        f"ip:{ip_address}", settings.login_ip_max_per_min, settings.login_window_seconds
    ):
        raise BizError(AuthErr.ACCOUNT_LOCKED, "Too many login attempts from this IP")
