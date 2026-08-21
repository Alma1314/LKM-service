"""对象事件回调端点：MinIO/S3 桶通知 webhook 入口。

事件驱动的登记路径：对象 PUT 落桶后 MinIO 触发 bucket-notification，POST 到
``/api/v1/notify/object`` → 校验共享令牌（Authorization: Bearer）→ 只对
``s3:ObjectCreated:Put`` 且 key 以 ``up/``（直传随机 key）开头的事件提取
``upload_id`` → 入队到 notify 队列（worker 异步登记）→ 立即 200。

回调内绝不执行登记（DB 读哈希/拷贝在 worker 侧做），只负责快速入队回执，
避免阻塞 MinIO 重投、保证吞吐。

令牌：``settings.files_notify_token``；空串视为未启用 → 一律 401。
"""

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi import Header as FastAPIHeader
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.jobs import enqueue_upload_notify

router = APIRouter(prefix="/notify", tags=["notify"])

# 直传随机 key 前缀（见 files/service.upload_init）：up/<upload_id>
_UP_PREFIX = "up/"


def _normalize_upload_key(key: str) -> str | None:
    """把事件里的真实 S3 key 规范化成 ``up/<upload_id>``，无法识别返回 None。

    预签名直传对象在桶里的真实 key 是 ``<s3_prefix>/up/<upload_id>``（S3Storage 拼
    ``s3_prefix`` 前缀，默认 ``files``）；而 ``notify_upload`` 按 marker 里的裸 ``up/``
    读对象。事件收到的 key 两种形态都需落到 ``up/<id>``：先剥掉 ``<prefix>/``，再认
    ``up/`` 前缀。其余（avatar？``files/<hash>`` 内容寻址对象等）返回 None 忽略。
    """
    if settings.s3_prefix:
        bare = key.lstrip("/")
        if bare.startswith(f"{settings.s3_prefix}/"):
            key = bare[len(settings.s3_prefix) + 1 :]
    if key.startswith(_UP_PREFIX):
        return key
    return None


def _authorized(authorization: str | None) -> bool:
    """校验 Bearer 令牌与 ``files_notify_token`` 一致；令牌未配置则拒绝一切。"""
    token = settings.files_notify_token
    if not token:
        return False
    if not authorization:
        return False
    scheme, _, value = authorization.partition(" ")
    return scheme.lower() == "bearer" and value == token


def _extract_uploads(payload: Any) -> list[str]:
    """从 MinIO S3 事件记录里提取需登记的 ``up/`` 上传 key。

    仅处理 ``s3:ObjectCreated:Put`` 事件且 key 能规范化为 ``up/<id>``（裸 ``up/…``
    或带 ``<s3_prefix>/up/…`` 前缀均可）；其余（avatar、``<prefix>`` 内容寻址对象等）
    一律忽略。返回规范化后的 ``up/<id>`` key（非 upload_id）。
    """
    uploads: list[str] = []
    records = payload.get("Records", []) if isinstance(payload, dict) else []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        event_name = rec.get("eventName", "")
        if "ObjectCreated" not in event_name:
            continue  # 仅 PUT/COPY 等创建事件；删除等忽略
        s3 = rec.get("s3")
        if not isinstance(s3, dict):
            continue
        obj = s3.get("object")
        if not isinstance(obj, dict):
            continue
        key = obj.get("key")
        if isinstance(key, str):
            nk = _normalize_upload_key(key)
            if nk is not None:
                uploads.append(nk)
    return uploads


@router.post("/object")
async def notify_object(
    request: Request,
    authorization: str | None = FastAPIHeader(default=None, alias="Authorization"),
) -> JSONResponse:
    """桶通知 webhook：校验令牌 → 抽取 up/<upload_id> → 入队 → 立即 200。"""
    if not _authorized(authorization):
        return JSONResponse(
            status_code=401,
            content={"code": 401, "msg": "Unauthorized", "data": None},
        )

    try:
        payload: Any = await request.json()
    except (json.JSONDecodeError, ValueError):
        payload = {}

    uploads = _extract_uploads(payload)
    for key in uploads:
        upload_id = key[len(_UP_PREFIX) :]
        # fire-and-forget：入队失败不影响回执（worker 侧可重投/恢复）
        await enqueue_upload_notify(upload_id)

    return JSONResponse(status_code=200, content={"code": 0, "msg": "OK", "data": None})
