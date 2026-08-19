"""S3/MinIO 存储后端：把 ``bucket_key`` 存到 ``prefix`` 下的真实 S3 key。

与 :class:`~app.modules.storage.local.LocalStorage` 一样字节级、不负责内容寻址/去重
（由 files 层决定 key 形状）。所有网络 I/O 经 ``asyncio.to_thread`` 调度，避免阻塞事件循环。
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.core.err import BizError
from app.modules.storage.base import SavedFile
from app.modules.storage.errors import StorageErr

_CHUNK = 1024 * 1024  # 分块下载读取


class S3Storage:
    """实现 :class:`StorageBackend` 的 S3/MinIO 后端。

    ``bucket_key`` 是 files 层传入的**裸逻辑 key**（形如 ``ab/<hash>``，不带 ``files/``
    前缀）；真实 S3 key = ``f"{prefix}/{bucket_key.lstrip('/')}"``（prefix 常为 ``files``）。
    构造入参里 ``client`` 可注入 mock（moto 测试用），否则按连接参数自建。
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str,
        client: Any = None,
        endpoint_url: str = "",
        region_name: str = "",
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix
        # 客户端构造为同步一次性调用，在工厂/注入处完成，常驻；网络回调走 to_thread
        self._client = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region_name or None,
            aws_access_key_id=aws_access_key_id or None,
            aws_secret_access_key=aws_secret_access_key or None,
        )

    def _key(self, bucket_key: str) -> str:
        # bucket_key 已是 files/<...> 逻辑 key，直接拼 prefix；避免双斜杠
        if not self.prefix:
            return bucket_key
        return f"{self.prefix}/{bucket_key.lstrip('/')}"

    async def save(
        self, stream: Any, /, *, max_bytes: int, bucket_key: str
    ) -> SavedFile:
        # 一次性读全受 max_bytes（100MB）约束校验；分块/预签名留到后续阶段
        data = stream.read()
        if len(data) > max_bytes:
            raise BizError(StorageErr.TOO_LARGE)
        key = self._key(bucket_key)
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self.bucket,
                Key=key,
                Body=data,
            )
        except ClientError as exc:
            raise BizError(
                StorageErr.STORE_ERROR, detail=f"Failed to store: {exc}"
            ) from exc
        return {"size": len(data), "bucket_key": bucket_key, "storage_path": key}

    async def open(self, bucket_key: str) -> AsyncIterator[bytes]:
        try:
            resp = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self.bucket,
                Key=self._key(bucket_key),
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "NoSuchKey":
                raise BizError(StorageErr.NOT_FOUND) from exc
            raise BizError(
                StorageErr.STORE_ERROR, detail=f"Failed to read: {exc}"
            ) from exc
        # 逐块读取经 to_thread 调度，避免 StreamingBody 的同步 socket I/O 阻塞事件循环
        body = resp["Body"]
        while True:
            chunk = await asyncio.to_thread(body.read, _CHUNK)
            if not chunk:
                break
            yield chunk

    async def copy(self, src: str, dest: str) -> None:
        # confirm 流程把随机 key 的对象复制到内容寻址 key；阻塞网络调用走 to_thread
        try:
            await asyncio.to_thread(
                self._client.copy_object,
                Bucket=self.bucket,
                CopySource={"Bucket": self.bucket, "Key": self._key(src)},
                Key=self._key(dest),
            )
        except ClientError as exc:
            raise BizError(
                StorageErr.STORE_ERROR, detail=f"Failed to copy: {exc}"
            ) from exc

    async def delete(self, bucket_key: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self.bucket,
                Key=self._key(bucket_key),
            )
        except ClientError as exc:
            raise BizError(
                StorageErr.STORE_ERROR, detail=f"Failed to delete: {exc}"
            ) from exc

    async def exists(self, bucket_key: str) -> bool:
        try:
            await asyncio.to_thread(
                self._client.head_object,
                Bucket=self.bucket,
                Key=self._key(bucket_key),
            )
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return False
            raise BizError(
                StorageErr.STORE_ERROR, detail=f"Failed to check: {exc}"
            ) from exc

    def presign_download(self, bucket_key: str, *, expires: int) -> str:
        # 预签名 URL 为本地签名计算（无网络），可同步调用
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(bucket_key)},
            ExpiresIn=expires,
        )

    def presign_upload(self, bucket_key: str, *, expires: int) -> str:
        return self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": self._key(bucket_key)},
            ExpiresIn=expires,
        )
