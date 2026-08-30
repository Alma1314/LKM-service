"""读热点缓存 Redis（模块4）：columns/articles 公开只读接口键缓存。

- **键规范**：`lkm:{env}:{prefix}:{parts...}`；parts 逐一 str，None 归并为空段。
  env 命名空间隔离 dev/prod 共用同一 Redis 时的互相污染。
- **TTL 分级**：明细长、列表短，平衡一致性与命中。
- **失效**：写路径显式失效（集合用版本号、单条目删键），TTL 仅兜底。
- **fail-open**：Redis 未启用/不可用 → 一律返回 None/直接落库，服务不挂。
- **可观测**：命中/未命中用 `lkm.cache` 的 DEBUG 级日志，配合模块0结构化日志观测命中率。
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import app.core.redis as redis_client
from app.core import logging as lkm_logging
from app.core.config import settings

logger = logging.getLogger("lkm.cache")

# TTL 分级（秒）：单条目长缓存、列表短缓存
TTL_ITEM_S = 300  # 5 min：单条目（如 get_by_slug / get）
TTL_LIST_S = 60  # 1 min：列表/分页


def _cache_env() -> str:
    """当前 env 命名空间：读到即缓存，避免同一 Redis 不同环境互相污染。"""
    return settings.env or "dev"


def make_key(prefix: str, *parts: Any) -> str:
    """键规范：`lkm:{env}:{prefix}:{parts...}`。parts 的 None 归并为空段。"""
    seg = [str(p) if p is not None else "" for p in parts]
    return f"lkm:{_cache_env()}:{prefix}:{'|'.join(seg)}"


async def cache_get(key: str) -> Any | None:
    """读缓存；Redis 不可用/未配置 → None（fail-open 直查库）。"""
    client = await redis_client.get_redis()
    if client is None:
        return None
    request_id = lkm_logging.get_request_id()
    try:
        raw = await client.get(key)
    except Exception:
        logger.debug("cache get fail-open key=%s req=%s", key, request_id)
        return None
    if raw is None:
        logger.debug("cache miss key=%s req=%s", key, request_id)
        return None
    logger.debug("cache hit key=%s req=%s", key, request_id)
    try:
        return json.loads(raw)
    except Exception:
        return None


async def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    """写缓存；Redis 不可用静默跳过（不影响主路径）。"""
    client = await redis_client.get_redis()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
    except Exception:
        logger.debug("cache set skip key=%s", key)


async def cache_invalidate(*keys: str) -> None:
    """显式失效一个或多个键；Redis 不可用静默跳过。"""
    client = await redis_client.get_redis()
    if client is None:
        return
    try:
        if keys:
            await client.delete(*keys)
    except Exception:
        logger.debug("cache invalidate skip keys=%s", keys)


async def collection_version(name: str) -> str:
    """读集合版本号（用于列表键前缀，写后 bump 使旧列表立即失效）。

    未启用 Redis → 返回固定 "v0"，此时缓存键退化但 fail-open 直接落库也成立。
    """
    client = await redis_client.get_redis()
    if client is None:
        return "v0"
    try:
        val = await client.get(make_key("ver", name))
    except Exception:
        return "v0"
    return val or "v0"


async def bump_collection_version(name: str) -> None:
    """写操作后递增集合版本号，使该集合所有旧列表键失效（原子，免 SCAN）。"""
    client = await redis_client.get_redis()
    if client is None:
        return
    try:
        await client.incr(make_key("ver", name))
    except Exception:
        logger.debug("bump version skip name=%s", name)


# 单飞（single-flight）：同一事件循环内，同一 key 的并发 miss 只让一个协程执行
# loader／回填，其余协程复用其结果，避免热点 key 击穿时同时打穿 DB。进程内锁即可
# 覆盖单 worker 内的并发；跨 worker 的击穿由 Redis SET NX 接续（此处未启用）。
# 锁字典按 key 常驻，key 数量受「不同缓存端点 × 过滤器组合」约束、天然有界，不做
# 清理——若动态增删锁，释放与移除之间会产生窗口让后到者拿到新锁、并发挤进 loader。
_flight_locks: dict[str, asyncio.Lock] = {}

# 空值缓存标记：loader 返回 None（业务上不存在）时写入该标记 + 短 TTL，读取端据此
# 在窗口内直接返回 None 而不反复调 loader，防御无效 slug/id 的缓存穿透。
_NULL_MARKER = "\x00__CACHE_NULL__"


async def cached_read[T](
    key: str,
    ttl_seconds: int,
    loader: Callable[[], Awaitable[T]],
    null_ttl: int | None = None,
) -> T:
    """读缓存命中直接返回；未命中执行 loader 并回填。loader 输出需 JSON 可序列化。

    - 并发 miss 走单飞：同一 key 同时仅有一个 loader 在执行。
    - 传 ``null_ttl`` 时，loader 返回 None 会以该短 TTL 写入空值标记缓存，
      在窗口内让无效查询（如不存在的 slug/id）命中缓存而不再穿透到 DB。
      未命中缓存时返回 None，语义与不缓存一致。
    """
    cached = await cache_get(key)
    if cached is not None:
        if cached == _NULL_MARKER:  # 空值标记：视为不存在，短窗口内不调 loader
            return None  # type: ignore[return-value]
        return cached  # type: ignore[return-value]

    lock = _flight_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _flight_locks[key] = lock
    async with lock:
        # 已持有锁：可能之前协程已回填，先重读；仍 miss 才执行 loader
        cached2 = await cache_get(key)
        if cached2 is not None:
            if cached2 == _NULL_MARKER:
                return None  # type: ignore[return-value]
            return cached2  # type: ignore[return-value]
        value = await loader()
        if value is not None:
            await cache_set(key, value, ttl_seconds)
        elif null_ttl is not None:
            await cache_set(key, _NULL_MARKER, null_ttl)
        return value
