import asyncio
import io
from unittest.mock import Mock

import boto3
import pytest
from moto import mock_aws

from app.core.err import BizError
from app.modules.storage.errors import StorageErr
from app.modules.storage.s3 import S3Storage


@pytest.fixture
def s3_client():
    with mock_aws():
        bucket = "lkm"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)
        yield client


@pytest.fixture
def storage(s3_client) -> S3Storage:
    return S3Storage(
        bucket="lkm",
        prefix="files",
        client=s3_client,
    )


def _stream(data: bytes):
    return io.BytesIO(data)


async def test_save_puts_with_prefix_key(storage: S3Storage, s3_client):
    out = await storage.save(_stream(b"s3data"), max_bytes=100, bucket_key="ab/hash123")
    assert out["size"] == 6
    assert out["bucket_key"] == "ab/hash123"
    assert out["storage_path"] == "files/ab/hash123"
    body = s3_client.get_object(Bucket="lkm", Key="files/ab/hash123")["Body"].read()
    assert body == b"s3data"


async def test_save_rejects_over_limit(storage: S3Storage):
    with pytest.raises(BizError) as ei:
        await storage.save(_stream(b"x" * 10), max_bytes=5, bucket_key="k")
    assert ei.value.errcode == StorageErr.TOO_LARGE


async def test_delete_and_exists(storage: S3Storage):
    await storage.save(_stream(b"data"), max_bytes=100, bucket_key="ab/x")
    assert await storage.exists("ab/x") is True
    await storage.delete("ab/x")
    assert await storage.exists("ab/x") is False


async def test_open_reads_back(storage: S3Storage):
    await storage.save(_stream(b"hello s3"), max_bytes=100, bucket_key="ab/read1")
    data = b"".join([c async for c in storage.open("ab/read1")])
    assert data == b"hello s3"


async def test_open_missing_raises_not_found(storage: S3Storage):
    with pytest.raises(BizError) as ei:
        agen = storage.open("ab/missing")
        await agen.__anext__()
    assert ei.value.errcode == StorageErr.NOT_FOUND


async def test_s3_copy_object(storage: S3Storage, s3_client):
    await storage.save(_stream(b"src data"), max_bytes=100, bucket_key="up/rand1")
    await storage.copy("up/rand1", "ab/srcdatahash")
    body = s3_client.get_object(Bucket="lkm", Key="files/ab/srcdatahash")["Body"].read()
    assert body == b"src data"


async def test_s3_copy_missing_src_raises(storage: S3Storage):
    with pytest.raises(BizError) as ei:
        await storage.copy("up/missing", "files/ab/x")
    assert ei.value.errcode == StorageErr.STORE_ERROR


# ---- 分块上传：多块拼接落盘，超限中止并 abort multipart ----

class _ChunkedStream:
    """按固定块吐数据，模拟非全量缓冲的可重复读流。"""

    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks
        self._i = 0

    def read(self, n: int = -1):
        if self._i >= len(self._chunks):
            return b""
        c = self._chunks[self._i]
        self._i += 1
        return c


def _make_s3_storage(client):
    return S3Storage(bucket="lkm", prefix="files", client=client)


@pytest.mark.asyncio
async def test_save_multipart_uses_create_upload_and_complete():
    # 用 mock client 断言分块序列：create -> upload_part*n -> complete
    client = Mock()
    client.create_multipart_upload.return_value = {"UploadId": "up-1"}
    client.upload_part.return_value = {"ETag": '"etag-N"'}
    client.complete_multipart_upload.return_value = {"ETag": "final"}

    storage = _make_s3_storage(client)
    out = await storage.save(
        _ChunkedStream([b"aaa", b"bbb", b"ccc"]), max_bytes=100, bucket_key="ab/mp"
    )
    assert out["size"] == 9
    assert out["storage_path"] == "files/ab/mp"
    client.create_multipart_upload.assert_called_once_with(Bucket="lkm", Key="files/ab/mp")
    assert client.upload_part.call_count == 3
    parts = client.complete_multipart_upload.call_args.kwargs["MultipartUpload"]["Parts"]
    assert [p["PartNumber"] for p in parts] == [1, 2, 3]


@pytest.mark.asyncio
async def test_save_multipart_aborts_and_raises_too_large():
    # 累计超限：必须在 complete 前 abort，并向调用方抛 TOO_LARGE
    client = Mock()
    client.create_multipart_upload.return_value = {"UploadId": "up-1"}
    client.upload_part.return_value = {"ETag": '"etag"'}
    client.abort_multipart_upload.return_value = {}

    storage = _make_s3_storage(client)
    with pytest.raises(BizError) as ei:
        await storage.save(
            _ChunkedStream([b"x" * 5_000, b"y" * 5_000]), max_bytes=8_000, bucket_key="ab/over"
        )
    assert ei.value.errcode == StorageErr.TOO_LARGE
    client.abort_multipart_upload.assert_called_once()
    assert not client.complete_multipart_upload.called
