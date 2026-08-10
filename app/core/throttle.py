"""基于滑动窗口的内存限流器。"""

import time
from collections import defaultdict


class RateLimiter:
    """每个键维护一个时间戳列表。每次 ``check`` 调用时，先清除窗口外的过期条目，再评估是否超限。"""

    def __init__(self) -> None:
        self._store: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, max_count: int, window_seconds: float) -> bool:
        """检查 *key* 是否被允许继续执行。"""
        now = time.time()
        timestamps = self._store[key]
        cutoff = now - window_seconds

        # 就地清除过期的时间戳。
        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)

        if len(timestamps) >= max_count:
            return False

        timestamps.append(now)
        return True

    def reset(self, key: str) -> None:
        """清除 *key* 的所有已存储时间戳。"""
        self._store.pop(key, None)


# 密码登录全局限流器
_login_ip_limiter = RateLimiter()
_login_global_limiter = RateLimiter()
_LOGIN_IP_MAX = 20          # 每 IP 每分钟最大尝试次数
_LOGIN_GLOBAL_MAX = 200     # 每分钟全局最大尝试次数
_LOGIN_WINDOW = 60


def check_password_login_rate_limit(ip_address: str) -> None:
    """对密码登录尝试应用 IP 和全局限流。"""
    from app.core.err import BizError
    from app.modules.auth.errors import AuthErr

    if not _login_global_limiter.check("__global__", _LOGIN_GLOBAL_MAX, _LOGIN_WINDOW):
        raise BizError(AuthErr.ACCOUNT_LOCKED, "Too many login attempts, please try again later")
    if ip_address and not _login_ip_limiter.check(f"ip:{ip_address}", _LOGIN_IP_MAX, _LOGIN_WINDOW):
        raise BizError(AuthErr.ACCOUNT_LOCKED, "Too many login attempts from this IP")
