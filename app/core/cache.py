"""读热点缓存 Redis（模块4）：columns/articles 公开只读接口键缓存。

- **键规范**：`lkm:{prefix}:{parts...}`；parts 逐一 str，None 归并为空段。
- **TTL 分级**：明细长、列表短，平衡一致性与命中。
- **失效**：写路径显式失效（集合用版本号、单条目删键），TTL 仅兜底。
- **fail-open**：Redis 未启用/不可用 → 一律返回 None/直接落库，服务不挂。
- **可观测**：命中/未命中用 `lkm.cache` 的 DEBUG 级日志，配合模块0结构化日志观测命中率。
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import app.core.redis as redis_client
from app.core import logging as lkm_logging

logger = logging.getLogger("lkm.cache")

# TTL 分级（秒）：单条目长缓存、列表短缓存
TTL_ITEM_S = 300  # 5 min：单条目（如 get_by_slug / get）
TTL_LIST_S = 60  # 1 min：列表/分页


def make_key(prefix: str, *parts: Any) -> str:
    """键规范：`lkm:{prefix}:{parts...}`。parts 的 None 归并为空段。"""
    seg = [str(p) if p is not None else "" for p in parts]
    return f"lkm:{prefix}:{'|'.join(seg)}"


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


async def cached_read[T](
    key: str,
    ttl_seconds: int,
    loader: Callable[[], Awaitable[T]],
) -> T:
    """读缓存命中直接返回；未命中执行 loader 并回填。loader 输出需 JSON 可序列化。"""
    cached = await cache_get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    value = await loader()
    if value is not None:
        await cache_set(key, value, ttl_seconds)
    return value
