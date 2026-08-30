"""基于 Redis 有序集合（ZSET）的精确滑动窗口限流器（async）。

与旧内存滑动窗口语义一致；Redis 不可用时放行（fail-open）。
"""

import time
import uuid
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis

from app.core import redis as _redis_core

# 原子脚本：清过期 -> 判限 -> 加戳 -> 设 TTL。返回 1 放行 / 0 拦截。
_LUA_ALLOW_SCRIPT = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_count = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
if redis.call('ZCARD', KEYS[1]) >= max_count then
  return 0
end
redis.call('ZADD', KEYS[1], now, member)
redis.call('EXPIRE', KEYS[1], math.ceil(window))
return 1
"""

_script_sha_local: str | None = None


async def _ensure_script(redis: Redis) -> str:
    """在连接上注册脚本并缓存 SHA（每个进程首次调用一次，并发下幂等）。"""
    global _script_sha_local
    if _script_sha_local is None:
        _script_sha_local = await redis.script_load(_LUA_ALLOW_SCRIPT)
    return _script_sha_local


class RedisRateLimiter:
    """每个 key 维护一个 ZSET（score=时间戳、member=随机 UUID）。

    ``fail_open=True``（默认）时 Redis 不可用/异常即放行，适合读缓存等非安全场景；
    登录、验证码、2FA 等安全限流应传 ``fail_open=False``，Redis 故障时宁可拒绝
    （fail-close），避免暴力破解防线在依赖抖动瞬间消失。
    """

    async def check(
        self,
        key: str,
        max_count: int,
        window_seconds: float,
        *,
        fail_open: bool = True,
    ) -> bool:
        """允许继续则 True；否则 False。失败时按 *fail_open* 决定放行或拒绝。"""
        redis = await _redis_core.get_redis()
        if redis is None:
            return fail_open
        try:
            now = time.time()
            sha = await _ensure_script(redis)
            # 数字参数转 str 传入(redis 5.x stub 仅收 str)；Lua 内用 tonumber 还原。
            # 返回值 cast 成 Awaitable[int] 以符合 5.x 的 `Awaitable[str]|str` 存根。
            awaitable = cast(
                Awaitable[int],
                redis.evalsha(
                    sha,
                    1,
                    key,
                    str(now),
                    str(float(window_seconds)),
                    str(int(max_count)),
                    uuid.uuid4().hex,
                ),
            )
            return await awaitable == 1
        except Exception:
            return fail_open  # 运行期异常按 fail_open 决定

    async def reset(self, key: str) -> None:
        """清除 *key*。Redis 不可用或 key 不存在时静默无操作。"""
        redis = await _redis_core.get_redis()
        if redis is None:
            return
        try:
            await redis.delete(key)
        except Exception:
            return
