"""对象事件通知任务：消费 notify 队列，把已直传对象登记为 PENDING（worker 侧执行）。

入口是 MinIO/S3 桶通知回调的 webhook（见 modules/files/notify.py）：回调只负责入队
（把 ``upload_id`` 丢进 notify 队列并立刻 200），真正的登记由本任务异步完成——
复用 ``_register_from_upload``（与前端 confirm 共用同一登记核心）。

worker 无请求上下文，数据库会话经 ``app.db.session.new_session()`` 自建，独立事务
（与 FastAPI 请求的 get_session 依赖引擎一致，但本任务结束时显式 commit + close）。
Redis 标记用 ``getdel`` 原子取走：取到即处理、取不到即视为已登记或已清扫，
天然幂等（同 upload_id 仅处理一次）。真正处理中失败抛异常 → 死信 DLQ（不重试）。
"""

import json
from contextlib import suppress

from app.core.redis import get_redis
from app.db.session import new_session
from app.modules.files.service import _get_storage, _register_from_upload, _upload_key
from app.ws.broker import publish_upload_bound


async def notify_upload(upload_id: str) -> None:
    """任务：登记直传上传。

    流程：GETDEL 标记（幂等）→ 解析 meta → ``_register_from_upload`` 登记 PENDING。
    标记缺失 = 已登记或已被清扫，静默返回（幂等 soft-return，不触发死信）；
    标记在而登记抛错 → 先按原值恢复标记（保 created_at），再向上抛进死信 DLQ
    （登记未完成，死信后由前端/重投流程处理，避免标记缺失被测为已登记而丢失）。
    """
    redis = await get_redis()
    if redis is None:
        # Redis 未启用：没有标记可读，无从登记（fail-close：无 Redis 即无直传流程）。
        return
    meta_raw = await redis.getdel(_upload_key(upload_id))
    if not meta_raw:
        return  # 已登记 or 已被清扫：幂等 no-op，标记本就缺失 → 无需恢复
    try:
        meta = json.loads(meta_raw)
    except json.JSONDecodeError:
        raise ValueError(f"upload marker corrupt: upload_id={upload_id}") from None

    db = await new_session()
    try:
        reg = await _register_from_upload(
            db, meta, int(meta["uploader_id"]), _get_storage()
        )
        await db.commit()
        # 登记成功后广播给 uploader 的 WebSocket(仅成功路径；失败走下方恢复标记+重试)。
        # 广播自身 fail-open(见 broker),异常被吞,不影响任务成功语义。
        await publish_upload_bound(
            int(meta["uploader_id"]),
            {
                "event": "upload_registered",
                "upload_id": upload_id,
                # 登记结果作为附带数据(broadcast 失败不影响主流程)；理论非 None，
                # 防御性保留 None 以兼容 mock/异常路径。
                "file": reg.model_dump(mode="json") if reg is not None else None,
            },
        )
    except Exception:
        # 登记失败（存储/DB 错误）：GETDEL 已把标记取走，若不恢复，后续处理会因标记缺失
        # 被当成幂等 no-op 而静默吞掉本次上传。恢复原标记（保留原始 created_at，孤儿
        # 清扫年龄逻辑不变）后重新抛出进死信。恢复本身尽力而为：
        # redis 恰好不可用也不覆盖原始异常（suppress 保证不 double-fail）。
        with suppress(Exception):
            await redis.set(_upload_key(upload_id), meta_raw)
        raise
    finally:
        await db.close()
