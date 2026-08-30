"""事件发布侧：worker 进程把登记结果发布到 Redis pub/sub，供 API 进程转发给 WebSocket。

通道命名约定集中在业务侧语义 —— ``ws:upload:<uploader_id>``（按用户订阅粒度）。
worker（如 ``app.tasks.notify``）只 import 本模块的 ``publish_upload_bound`` 发布；
不持有任何 WebSocket 连接（连接只存在于 API 进程的 ``manager``）。
"""

import json
from typing import Any

from app.core.redis import get_redis

# 通道前缀：ws:upload:<uploader_id>
_UPLOAD_CHANNEL_PREFIX = "ws:upload:"


def upload_channel(uploader_id: int) -> str:
    """返回某用户上传事件所属的 Redis 通道名。"""
    return f"{_UPLOAD_CHANNEL_PREFIX}{uploader_id}"


async def publish_upload_bound(uploader_id: int, payload: dict[str, Any]) -> None:
    """把登记完成的 payload 发布到该 uploader 的通道。

    Redis 不可用或发布异常一律静默 no-op（fail-open，与 ``app.core.redis`` 语义一致）：
    广播只是体验增强，缺失时前端回退到「稍后刷新列表」即可，不该阻塞/影响登记流程
    与任务成功语义。
    """
    redis = await get_redis()
    if redis is None:
        return
    try:
        await redis.publish(
            upload_channel(uploader_id), json.dumps(payload, ensure_ascii=False)
        )
    except Exception:
        # 广播失败不影响登记主流程；下次成功触发前前端靠超时兜底
        return
