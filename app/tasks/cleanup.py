"""孤儿随机 key 清扫：扫描过期的 upload:* Redis 标记，删除其对应随机对象 key 及标记。

arq cron 周期任务，每小时整点执行。Redis 未启用时静默降级（fail-open，不报错）。

过期判定按"年龄"而非 Redis TTL（R1）：标记持久化落 Redis，靠 ``created_at`` 记录写入时刻；
年龄超过 ``_UPLOAD_TTL`` 窗口即视为过期。这样清扫的 scan_iter 每次都能看到标记（含已过期
的），才能真正清理掉对应的 up/<uid> 孤儿对象——旧实现用 pttl 判断，而带 TTL 的标记到过期时
已被 Redis 自动删除，scan 永远扫不到，孤儿永不被回收。
"""

import json
from contextlib import suppress
from datetime import UTC, datetime

from app.core.redis import get_redis
from app.modules.files.service import _UPLOAD_TTL, _get_storage

_MATCH = "upload:*"


def _parse_created_at(meta_raw: str) -> datetime | None:
    """从标记 JSON 解析 ``created_at``；标记残缺/坏 JSON 视为不可判龄（返回 None）。"""
    try:
        meta = json.loads(meta_raw)
    except json.JSONDecodeError:
        return None
    raw = meta.get("created_at")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


async def cleanup_expired_uploads(ctx: dict) -> None:
    """arq 周期任务：清掉已过期(created_at 早于 _UPLOAD_TTL 窗口)但未确认的直传随机 key 及标记。

    *ctx* 为 ARQ 注入的 TaskContext（含 ctx["redis"]）；本项目 tasks 统一起
    ``get_redis()`` 获取客户端（与 send 系列一致），故忽略 ctx 内容。
    Redis 未启用（get_redis 返回 None）直接 return，不报错。
    """
    redis = await get_redis()
    if redis is None:
        return
    storage = _get_storage()
    now = datetime.now(UTC)
    # redis.asyncio 的 scan_iter 是异步迭代器，直接 async for 消费
    async for marker in redis.scan_iter(match=_MATCH):
        meta_raw = await redis.get(marker)
        if meta_raw is None:
            continue  # 已被他人清扫/删除，跳过
        created_at = _parse_created_at(meta_raw)
        # 年龄窗口按"创建后至少 _UPLOAD_TTL 秒"判定过期；created_at 缺失/坏 JSON →
        # 保守不删（无法判龄），避免误删仍在直传中的标记。
        if created_at is None or (now - created_at).total_seconds() <= _UPLOAD_TTL:
            continue
        # 过期：尽力删除对应随机 key 对象（key 字段存在时），再删标记
        try:
            meta = json.loads(meta_raw)
        except json.JSONDecodeError:
            meta = {}
        key = meta.get("key")
        if isinstance(key, str) and key:
            with suppress(Exception):
                await storage.delete(key)  # 尽力清扫，单次失败不中断
        await redis.delete(marker)
