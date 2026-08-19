import io

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
