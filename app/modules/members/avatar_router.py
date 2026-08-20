"""预置成员头像代理端点：从 storage 后端流式返回，替代本地静态服务。

预置头像按 ``avatars/{name(.webp)}`` 存于 storage（可切 Local/S3/MinIO）。前端经
``/api/v1/avatars/{name}.webp`` 获取；头像内容不变（文件名即指纹），附加
``public, max-age=31536000, immutable`` 长缓存头，与旧 ``_ImmutableStaticFiles`` 策略一致。
"""

from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.err import BizError
from app.modules.storage.base import StorageBackend
from app.modules.storage.factory import get_storage
from app.modules.storage.errors import StorageErr

router = APIRouter(prefix="/avatars", tags=["avatars"])

_PRESET_PREFIX = "avatars"


def _key(name: str) -> str:
    """预置头像存储 key：``avatars/{name}``（name 即 .webp 文件名）。"""
    # 只取 basename 防路径穿越：任何 ../ 或子路径都被折叠为单文件名
    return f"{_PRESET_PREFIX}/{Path(name).name}"


@router.get("/{name}")
async def serve_preset_avatar(name: str) -> StreamingResponse:
    """从 storage 流式返回预置头像。缺失抛 NOT_FOUND（404）。

    头像公开，immutable 长缓存。storage key = ``avatars/{name}``。
    """
    storage = get_storage()
    key = _key(name)
    if not await storage.exists(key):
        raise BizError(StorageErr.NOT_FOUND)
    return _stream(_yield(storage, key))


async def _yield(storage: StorageBackend, key: str) -> AsyncIterator[bytes]:
    async for chunk in storage.open(key):
        yield chunk


def _stream(agen: AsyncIterator[bytes]) -> StreamingResponse:
    return StreamingResponse(
        agen,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Disposition": "inline",
        },
    )
