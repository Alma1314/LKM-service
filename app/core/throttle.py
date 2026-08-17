"""登录限流：委托 Redis 滑动窗口限流器；Redis 不可用时放行（fail-open）。"""

from app.core.err import BizError
from app.core.redis_limiter import RedisRateLimiter
from app.modules.auth.errors import AuthErr

_LOGIN_IP_MAX = 20  # 每 IP 每分钟最大尝试次数
_LOGIN_GLOBAL_MAX = 200  # 每分钟全局最大尝试次数
_LOGIN_WINDOW = 60


async def check_password_login_rate_limit(ip_address: str) -> None:
    """对密码登录尝试应用 IP 和全局限流。Redis 不可用时静默放行。"""
    limiter = RedisRateLimiter()
    if not await limiter.check("__global__", _LOGIN_GLOBAL_MAX, _LOGIN_WINDOW):
        raise BizError(
            AuthErr.ACCOUNT_LOCKED, "Too many login attempts, please try again later"
        )
    if ip_address and not await limiter.check(
        f"ip:{ip_address}", _LOGIN_IP_MAX, _LOGIN_WINDOW
    ):
        raise BizError(AuthErr.ACCOUNT_LOCKED, "Too many login attempts from this IP")
